import asyncio
import logging
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from app.config import SYNC_POLL_INTERVAL_SECONDS
from app.connectors.simulator import get_snapshot
from app.twin.mapper import simulator_asset_to_twin
from app.twin.registry import TwinRegistry
from app.storage.postgres import PersistenceError


logger = logging.getLogger(__name__)


def summarize_sync_error(error: Exception) -> str:
    if isinstance(error, PersistenceError):
        return "Database persistence failed; snapshot not accepted"
    if isinstance(error, httpx.TimeoutException):
        return "Simulator request timed out"
    if isinstance(error, httpx.HTTPStatusError):
        return f"Simulator returned HTTP {error.response.status_code}"
    if isinstance(error, httpx.RequestError):
        return f"Simulator unavailable ({type(error).__name__})"
    if isinstance(error, (KeyError, TypeError, ValueError, ValidationError)):
        return f"Invalid simulator snapshot ({type(error).__name__})"
    return f"Synchronization failed ({type(error).__name__})"


class SyncService:
    def __init__(
        self,
        registry: TwinRegistry,
        snapshot_fetcher=get_snapshot,
        poll_interval_seconds: float = SYNC_POLL_INTERVAL_SECONDS,
        store=None,
    ):
        self.registry = registry
        self.snapshot_fetcher = snapshot_fetcher
        self.poll_interval_seconds = poll_interval_seconds
        self.running = False
        self.store = store
        self.last_persistence_error = None
        self.last_persisted_at = None
        self._sync_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def sync_once(self):
        async with self._sync_lock:
            self.registry.mark_sync_attempt()

            try:
                snapshot = await self.snapshot_fetcher()
                run_id = snapshot["run_id"]
                if not isinstance(run_id, str) or not run_id:
                    raise ValueError("Invalid run ID")
                twins = [
                    simulator_asset_to_twin(
                        asset, snapshot.get("factory", {}).get("config", {}).get("step_seconds")
                    )
                    for asset in snapshot["assets"]
                ]

                if len({t.asset_id for t in twins}) != len(twins) or any(t.sequence < 0 for t in twins):
                    raise ValueError("Invalid asset sequences or duplicate assets")
                candidates = [t for t in twins if (
                    self.registry.current_run_id != run_id
                    or self.registry.get(t.asset_id) is None
                    or t.sequence > self.registry.get(t.asset_id).sequence
                )]
                if self.store is not None:
                    try:
                        await self.store.save(run_id, candidates, datetime.now(timezone.utc))
                    except PersistenceError:
                        self.last_persistence_error = "Database persistence failed; snapshot not accepted"
                        raise
                    self.last_persisted_at = datetime.now(timezone.utc)
                    self.last_persistence_error = None

                if self.registry.current_run_id != run_id:
                    self.registry.reset_for_new_run(run_id)

                accepted = 0
                rejected = 0

                for twin in twins:
                    if self.registry.update(twin):
                        accepted += 1
                    else:
                        rejected += 1

                self.registry.mark_sync_success()

                return {
                    "run_id": run_id,
                    "accepted": accepted,
                    "rejected": rejected,
                }
            except Exception as error:
                self.registry.mark_sync_failure(summarize_sync_error(error))
                raise

    async def run_forever(self):
        if self.running:
            return

        self.running = True
        self._stop_event.clear()

        try:
            while self.running:
                try:
                    await self.sync_once()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if (
                        self.registry.consecutive_failures == 1
                        or self.registry.consecutive_failures % 30 == 0
                    ):
                        logger.warning(
                            "Simulator sync failed (%s consecutive): %s",
                            self.registry.consecutive_failures,
                            summarize_sync_error(error),
                        )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self.running = False

    def stop(self):
        self.running = False
        self._stop_event.set()
