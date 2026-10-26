"""Historical assessment orchestration; no HTTP or source-score dependency."""
from datetime import timedelta

from app.health.engine import calculate
from app.health.models import Observation, Event, utc
from app.storage.postgres import PersistenceError


async def asset_health(store, *, source, run_id, asset_id, window_start,
                       window_end, assessment_generated_at):
    if not all(isinstance(v, str) and v.strip() for v in (source, run_id, asset_id)):
        raise ValueError("Nonempty source/run/asset required")
    start, end, generated = map(utc, (window_start, window_end, assessment_generated_at))
    if not 0 < (end-start).total_seconds() <= 86400:
        raise ValueError("Health window must be positive and at most 24 hours")
    if store is None:
        raise PersistenceError("Persistence is not configured")
    evidence = await store.health_evidence(source, run_id, asset_id, start, end)
    rows = [Observation(**row) for row in evidence['observations']]
    events = [Event(**event) for event in evidence['events']]
    context = dict(source=source, run_id=run_id, asset_id=asset_id,
                   assessment_generated_at=generated, evidence_complete=True)
    result = calculate(rows, events, window_start=start, window_end=end, **context)
    if not evidence['asset_exists']:
        result.reasons.append('Unknown persisted asset')
    if not evidence['run_exists']:
        result.reasons.append('Unknown persisted source/run')
    if not rows and evidence['asset_exists'] and evidence['run_exists']:
        result.reasons.append('Empty receipt window' if evidence['before'] or evidence['after']
                              else 'No persisted observations for this asset/source/run combination')

    # The approved engine excludes external records. Evaluate boundary pairs
    # separately with that same engine, adding context notes only, never counts.
    ordered = sorted(rows, key=lambda r: (r.observed_at, r.id))
    for side, edge in [('before', ordered[:1]), ('after', ordered[-1:])]:
        raw = evidence[side]
        if not raw or not edge:
            continue
        outside = Observation(**raw)
        pair = [outside, edge[0]] if side == 'before' else [edge[0], outside]
        boundary = calculate(pair, [], window_start=pair[0].observed_at,
                             window_end=pair[1].observed_at+timedelta(microseconds=1), **context)
        for finding in boundary.data_quality.findings:
            if finding.startswith(('sequence_gaps:', 'sequence_reversals:',
                                   'nonincreasing_source_timestamps:')):
                result.reasons.append(
                    f'Boundary context {side} window (observation IDs {pair[0].id}, {pair[1].id}): {finding}; '
                    'outside record excluded from in-window indicators')
    return result
