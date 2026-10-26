import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import app.main as main
from app.services.sync_service import SyncService
from app.storage.postgres import PersistenceError, PostgresStore, source_time
from app.twin.registry import TwinRegistry
from test_source_connectivity import make_snapshot


class PersistenceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_preserves_registry_and_retry_succeeds(self):
        store = AsyncMock()
        registry = TwinRegistry()
        fetcher = AsyncMock(return_value=make_snapshot(sequence=1))
        service = SyncService(registry, fetcher, store=store)
        await service.sync_once()
        success = registry.last_sync_at
        fetcher.return_value = make_snapshot("new-run", 0)
        store.save.side_effect = PersistenceError("secret credential")
        with self.assertRaises(PersistenceError):
            await service.sync_once()
        self.assertEqual(registry.current_run_id, "run-1")
        self.assertEqual(registry.get("CNC_01").sequence, 1)
        self.assertEqual(registry.last_sync_at, success)
        self.assertNotIn("secret", registry.last_sync_error)
        store.save.side_effect = None
        await service.sync_once()
        self.assertEqual(registry.current_run_id, "new-run")
        self.assertEqual(registry.get("CNC_01").sequence, 0)
        self.assertIsNone(service.last_persistence_error)

    async def test_duplicate_poll_does_not_submit_duplicate_observations(self):
        store = AsyncMock()
        service = SyncService(TwinRegistry(), AsyncMock(return_value=make_snapshot()), store=store)
        await service.sync_once()
        result = await service.sync_once()
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(store.save.call_args.args[1], [])

    async def test_bad_snapshot_never_reaches_storage(self):
        store = AsyncMock()
        snapshot = make_snapshot()
        snapshot["assets"][0]["dynamic_state"]["values"] = [1, 2]
        service = SyncService(TwinRegistry(), AsyncMock(return_value=snapshot), store=store)
        with self.assertRaises(ValueError):
            await service.sync_once()
        store.save.assert_not_awaited()

    async def test_connection_error_is_sanitized(self):
        store = PostgresStore("postgresql://secret", timeout=.05)
        with patch("app.storage.postgres.asyncpg.create_pool", AsyncMock(side_effect=RuntimeError("password"))):
            with self.assertRaises(PersistenceError) as caught:
                await store.save("run", [], datetime.now(timezone.utc))
        self.assertNotIn("password", str(caught.exception))

    async def test_connection_has_total_deadline(self):
        async def blocked(*args, **kwargs):
            await asyncio.Event().wait()
        store = PostgresStore("unused", timeout=.02)
        with patch("app.storage.postgres.asyncpg.create_pool", blocked):
            with self.assertRaises(PersistenceError):
                await asyncio.wait_for(store.save("run", [], datetime.now(timezone.utc)), .5)

    async def test_history_api_bounds_empty_results_and_database_failure(self):
        transport = httpx.ASGITransport(app=main.app)
        store = AsyncMock()
        store.history.return_value = []
        with patch.object(main, "store", store):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for path in ("telemetry", "history"):
                    response = await client.get(f"/api/twins/missing/{path}")
                    self.assertEqual(response.json(), [])
                    self.assertEqual((await client.get(f"/api/twins/a/{path}?limit=1001")).status_code, 422)
                    self.assertEqual((await client.get(f"/api/twins/a/{path}?after_id=-1")).status_code, 422)
                store.history.side_effect = PersistenceError("private")
                response = await client.get("/api/twins/a/history")
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private", response.text)
                self.assertEqual((await client.get("/health")).status_code, 200)

    async def test_manual_sync_database_failure_returns_503(self):
        with patch.object(main.sync_service, "sync_once", AsyncMock(side_effect=PersistenceError("private"))):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                response = await client.post("/sync")
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private", response.text)

    async def test_lifespan_cancels_inflight_write_and_closes_storage(self):
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_save(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        store = AsyncMock()
        store.save.side_effect = blocked_save
        service = SyncService(TwinRegistry(), AsyncMock(return_value=make_snapshot()), store=store)
        with patch.object(main, "store", store), patch.object(main, "sync_service", service):
            async with main.lifespan(main.app):
                await asyncio.wait_for(entered.wait(), .5)
            self.assertTrue(cancelled.is_set())
            self.assertFalse(service.running)
            self.assertEqual(service.registry.get_all(), [])
            store.close.assert_awaited_once()

    async def test_unconfigured_history_is_explicitly_unavailable(self):
        with patch.object(main, "store", None):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                response = await client.get("/api/twins/CNC_01/history")
                self.assertEqual(response.status_code, 503)
                self.assertFalse((await client.get("/api/persistence-status")).json()["enabled"])

    def test_source_timestamp_does_not_invent_timezone(self):
        self.assertIsNone(source_time(None))
        self.assertIsNone(source_time("invalid"))
        self.assertIsNone(source_time("2026-01-01T00:00:00"))
        self.assertEqual(source_time("2026-01-01T02:00:00+02:00"), datetime(2026, 1, 1, tzinfo=timezone.utc))
