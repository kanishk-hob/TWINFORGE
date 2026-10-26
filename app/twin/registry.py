from datetime import datetime, timezone

from app.twin.models import MachineTwin


class TwinRegistry:
    def __init__(self):
        self.twins: dict[str, MachineTwin] = {}

        self.current_run_id: str | None = None

        self.last_sync_at: datetime | None = None
        self.last_sync_attempt_at: datetime | None = None
        self.last_sync_error: str | None = None
        self.consecutive_failures: int = 0
        self.source_connected: bool = False

    def reset_for_new_run(self, run_id: str):
        self.twins.clear()
        self.current_run_id = run_id

    def update(self, twin: MachineTwin):
        existing = self.twins.get(twin.asset_id)

        if existing is None:
            self.twins[twin.asset_id] = twin
            return True

        if twin.sequence <= existing.sequence:
            return False

        self.twins[twin.asset_id] = twin
        return True

    def mark_sync_attempt(self, at: datetime | None = None):
        self.last_sync_attempt_at = at or datetime.now(timezone.utc)

    def mark_sync_success(self, at: datetime | None = None):
        self.last_sync_at = at or datetime.now(timezone.utc)
        self.last_sync_error = None
        self.consecutive_failures = 0
        self.source_connected = True

    def mark_sync_failure(self, error: str):
        self.last_sync_error = error
        self.consecutive_failures += 1
        self.source_connected = False

    def is_source_connected(
        self,
        stale_after_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        if not self.source_connected or self.last_sync_at is None:
            return False

        current_time = now or datetime.now(timezone.utc)
        age_seconds = (current_time - self.last_sync_at).total_seconds()
        return age_seconds <= stale_after_seconds

    def get(self, asset_id: str):
        return self.twins.get(asset_id)

    def get_all(self):
        return list(self.twins.values())
