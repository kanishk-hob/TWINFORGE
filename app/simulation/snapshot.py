"""Freeze canonical context synchronously before any asynchronous work."""
from datetime import datetime, timezone
from app.config import SOURCE_STALE_AFTER_SECONDS
from app.simulation.models import CurrentContext


class ContextConflict(ValueError):
    pass


def freeze_context(registry, request):
    if registry.current_run_id != request.run_id:
        raise ContextConflict('Requested run does not match current canonical run')
    twin = registry.get(request.asset_id)
    if twin is None:
        raise KeyError(request.asset_id)
    if request.expected_sequence is not None and twin.sequence != request.expected_sequence:
        raise ContextConflict('Requested sequence does not match current canonical observation')
    now = datetime.now(timezone.utc)
    return CurrentContext(
        run_id=request.run_id, asset_id=twin.asset_id, factory_id=twin.factory_id,
        line_id=twin.line_id, sequence=twin.sequence, state=twin.state,
        current_job_id=twin.current_job_id, active_fault=twin.active_fault,
        upstream=twin.relationships.upstream, downstream=twin.relationships.downstream,
        source_timestamp=twin.telemetry.timestamp, captured_at=now,
        last_sync_at=registry.last_sync_at,
        source_connected=registry.is_source_connected(SOURCE_STALE_AFTER_SECONDS, now),
        valid=twin.quality.valid, fresh=twin.quality.fresh, quality_reason=twin.quality.reason,
    )
