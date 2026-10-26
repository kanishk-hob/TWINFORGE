"""Reuse existing services with one recorded telemetry read and explicit context checks."""
from datetime import datetime, timezone

from app.predictive.service import assess_predictive_health
from app.recommendation.models import EvidenceReference
from app.recommendation.policy import evaluate
from app.simulation.models import MaintenanceComparisonRequest
from app.simulation.service import compare_maintenance
from app.simulation.snapshot import ContextConflict, freeze_context
from app.storage.models import ObservationRecord
from app.storage.postgres import PersistenceError


class EvidenceReader:
    """Observe the predictive service's existing read, without a second SQL query."""
    def __init__(self, store):
        self.store = store
        self.observations = []

    async def history(self, *args, **kwargs):
        rows = await self.store.history(*args, **kwargs)
        self.observations = [ObservationRecord(**row) for row in rows]
        return rows


async def recommend_maintenance(registry, store, request):
    scenario_request = MaintenanceComparisonRequest(**request.model_dump(exclude={'predictive_method'}))
    comparison = compare_maintenance(registry, scenario_request)
    baseline = comparison.baseline
    predictive, issues = None, []
    reader = EvidenceReader(store)
    if store is None:
        issues.append('Persistence is not configured; predictive evidence unavailable')
    else:
        try:
            predictive = await assess_predictive_health(reader, asset_id=request.asset_id,
                run_id=request.run_id, method=request.predictive_method)
        except PersistenceError:
            issues.append('Historical storage is unavailable; predictive evidence unavailable')
        except (ValueError, ArithmeticError):
            issues.append('Persisted predictive evidence could not be validated or calculated')

    # SQL is awaited: sync may publish a different run/sequence while it runs.
    current = freeze_context(registry, scenario_request.model_copy(update={'expected_sequence': baseline.sequence}))
    excluded = {'captured_at', 'last_sync_at', 'source_connected'}
    if current.model_dump(exclude=excluded) != baseline.model_dump(exclude=excluded):
        raise ContextConflict('Canonical state changed during recommendation; refresh and retry')
    if not current.source_connected:
        issues.append('Source is disconnected or stale at recommendation completion')
    generated = datetime.now(timezone.utc)
    reference = EvidenceReference()
    if reader.observations:
        rows = sorted(reader.observations, key=lambda r: r.id)
        latest = rows[-1]
        reference = EvidenceReference(latest_observation_id=latest.id, latest_sequence=latest.sequence,
            latest_observed_at=latest.observed_at,
            receipt_age_seconds=(generated-latest.observed_at).total_seconds()
                if latest.observed_at.utcoffset() is not None else None,
            matches_canonical_sequence=(latest.sequence == baseline.sequence and
                (latest.asset_id, latest.run_id, latest.source) == (baseline.asset_id, baseline.run_id, baseline.source)))
        if any(not r.valid or not r.fresh for r in rows):
            issues.append('Predictive evidence window includes invalid or stale observations')
        if any(b.sequence != a.sequence+1 for a, b in zip(rows, rows[1:])):
            issues.append('Predictive evidence window has duplicate, reversed or missing sequences')
    return evaluate(comparison, predictive, reference, generated_at=generated, evidence_issues=issues)
