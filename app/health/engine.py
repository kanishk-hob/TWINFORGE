"""Pure recorded-condition rules: no I/O, configuration or clock access."""
from app.health.models import Assessment, DataQuality, Indicator, Reference, utc


def reference(row, kind):
    return Reference(kind=kind, id=row.id, sequence=row.sequence,
                     observed_at=row.observed_at, source_timestamp=row.source_timestamp)


def select(rows, context, start, end):
    seen = {}
    for row in rows:
        if (row.source, row.run_id, row.asset_id) != context:
            raise ValueError("Mixed source/run/asset context")
        if row.id in seen and seen[row.id] != row:
            raise ValueError("Conflicting duplicate evidence ID")
        seen[row.id] = row
    return sorted((r for r in seen.values() if start <= r.observed_at < end),
                  key=lambda r: (r.observed_at, r.id))


def calculate(observations, events, *, asset_id, source, run_id,
              window_start, window_end, assessment_generated_at,
              evidence_complete=False):
    """Inputs are Observation/Event models; completeness is a caller assertion.

    A complete retrieval is not proof of complete physical sampling. No scores,
    physical health classification or unobserved events are inferred.
    """
    start, end, generated = map(utc, (window_start, window_end, assessment_generated_at))
    if end <= start:
        raise ValueError("Window must be positive")
    if not all(isinstance(v, str) and v for v in (asset_id, source, run_id)):
        raise ValueError("Nonempty source/run/asset context required")
    if not isinstance(evidence_complete, bool):
        raise ValueError("evidence_complete must be boolean")
    context = (source, run_id, asset_id)
    rows = select(observations, context, start, end)
    logs = select(events, context, start, end)
    if len({r.sequence for r in rows}) != len(rows):
        raise ValueError("Multiple observation IDs for one sequence")

    counts = dict(missing_source_timestamps=0, invalid_observations=0,
                  stale_observations=0, missing_telemetry=0, sequence_gaps=0,
                  sequence_reversals=0, nonincreasing_source_timestamps=0)
    affected = {}
    usable = 0
    for row in rows:
        issues = dict(missing_source_timestamps=row.source_timestamp is None,
                      invalid_observations=not row.valid,
                      stale_observations=not row.fresh,
                      missing_telemetry=not row.telemetry_values)
        for key, present in issues.items():
            if present:
                counts[key] += 1
                affected[row.id] = row
        if not any(issues.values()):
            usable += 1
    for previous, row in zip(rows, rows[1:]):
        key = None
        if row.sequence > previous.sequence + 1:
            key = 'sequence_gaps'
        elif row.sequence <= previous.sequence:
            key = 'sequence_reversals'
        elif (previous.source_timestamp is not None and row.source_timestamp is not None
              and row.source_timestamp <= previous.source_timestamp):
            key = 'nonincreasing_source_timestamps'
        if key:
            counts[key] += 1
            affected[previous.id], affected[row.id] = previous, row
    findings = [f'{key}: {value}' for key, value in counts.items() if value]
    reasons = list(findings)
    if not evidence_complete:
        reasons.append('Evidence retrieval completeness not established')
    if not rows:
        reasons.append('No observations in receipt window')
    sufficient = bool(rows) and evidence_complete and not findings
    absence = 'Insufficient evidence for a negative finding'

    def indicator(matches, kind, value, negative_value=False):
        if matches:
            return Indicator(status='observed', value=value,
                             reason='Explicit recorded evidence; not a physical-health diagnosis',
                             evidence=[reference(r, kind) for r in matches])
        if sufficient:
            return Indicator(status='not_observed', value=negative_value,
                             reason='Not present in supplied complete evidence; not proof of absence between samples',
                             evidence=[reference(r, 'observation') for r in rows])
        return Indicator(status='unavailable', reason=absence)

    latest = rows[-1] if rows else None
    indicators = {
        'fault_reported_at_last_observation': indicator(
            [latest] if latest and latest.active_fault is not None else [],
            'observation', latest.active_fault if latest else None, None),
        'fault_state_observed': indicator([r for r in rows if r.state == 'FAULT'], 'observation', True),
        'offline_state_observed': indicator([r for r in rows if r.state == 'OFFLINE'], 'observation', True),
    }
    for name, kind in [('fault_start_observations', 'fault_started'),
                       ('fault_clear_observations', 'fault_recovered')]:
        matches = [e for e in logs if e.kind == kind]
        indicators[name] = indicator(matches, 'event', len(matches), 0)
        if matches:
            indicators[name].reason = ('Count of distinct recorded events only; not total physical incidents, '
                                       'known repair or independently verified recovery')
    indicators['evidence_discontinuity'] = indicator(
        sorted(affected.values(), key=lambda r: (r.observed_at, r.id)), 'observation', True)
    if not affected and len(rows) < 2:
        indicators['evidence_discontinuity'] = Indicator(
            status='unavailable', reason='At least two observations needed to compare continuity')
        if rows:
            reasons.append('Only one observation; continuity cannot be compared')
    elif not affected and sufficient:
        indicators['evidence_discontinuity'].reason = 'No discontinuity detected; this does not prove continuous sampling'

    availability = 'available' if sufficient and len(rows) >= 2 else 'partial'
    if not rows and not logs:
        availability = 'unavailable'
        reasons.append('No evidence in receipt window')
    elif all(i.status == 'unavailable' for i in indicators.values()):
        availability = 'unavailable'
        reasons.append('No evidence usable by the approved indicators')
    all_evidence = rows + logs
    source_times = [r.source_timestamp for r in all_evidence if r.source_timestamp is not None]
    return Assessment(
        asset_id=asset_id, source=source, run_id=run_id,
        assessment_generated_at=generated, window_start=start, window_end=end,
        latest_source_timestamp=max(source_times, default=None),
        latest_observed_at=max((r.observed_at for r in all_evidence), default=None),
        availability=availability, reasons=reasons,
        data_quality=DataQuality(evidence_complete=evidence_complete,
                                 observation_count=len(rows), event_count=len(logs),
                                 usable_observation_count=usable, findings=findings, **counts),
        indicators=indicators)
