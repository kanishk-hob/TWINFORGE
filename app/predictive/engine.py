"""Pure rolling baseline screening; no simulator scores, I/O or clock access."""
from math import isfinite
from statistics import fmean, pstdev

from app.predictive.models import PredictiveHealthResult, SignalAssessment
from app.storage.models import ObservationRecord

from app.predictive.config import BASELINE_SIZE, MIN_OBSERVATIONS, WARNING_THRESHOLD, CRITICAL_THRESHOLD
SUPPORTED_SIGNALS = frozenset({
    'temperature', 'temperature_c', 'temp_c', 'vibration', 'vibration_rms',
    'current', 'current_a', 'power', 'power_kw',
})


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def normalize_risk(z):
    return min(1.0, max(0.0, (abs(z) - 1) / 3))


def predict_health(asset_id: str, observations: list[ObservationRecord], *,
                   source: str, run_id: str) -> PredictiveHealthResult:
    seen = {}
    for row in observations:
        if (row.asset_id, row.source, row.run_id) != (asset_id, source, run_id):
            raise ValueError('Mixed predictive evidence context')
        if row.id in seen and seen[row.id] != row:
            raise ValueError('Conflicting observation ID')
        seen[row.id] = row
    rows = sorted(seen.values(), key=lambda r: r.id)[-(BASELINE_SIZE + 1):]
    if len({r.sequence for r in rows}) != len(rows):
        raise ValueError('Duplicate observation sequence')
    latest = rows[-1] if rows else None
    result = PredictiveHealthResult(
        asset_id=asset_id, source=source, run_id=run_id,
        latest_observed_at=latest.observed_at if latest else None,
        status='INSUFFICIENT_DATA', recommendation='Collect valid, fresh telemetry and review data quality',
        observations_used=0,
    )
    if latest is None or not (latest.valid and latest.fresh and latest.telemetry_values):
        result.reason = 'Latest persisted observation has no usable telemetry'
        return result

    assessments = []
    useful_ids = set()
    for signal in sorted(SUPPORTED_SIGNALS):
        current = latest.telemetry_values.get(signal)
        if not numeric(current):
            continue
        baseline_rows = [r for r in rows[:-1] if r.valid and r.fresh and r.telemetry_values
                         and numeric(r.telemetry_values.get(signal))]
        result.observations_used = max(result.observations_used, len(baseline_rows) + 1)
        if len(baseline_rows) + 1 < MIN_OBSERVATIONS:
            continue
        baseline = [r.telemetry_values[signal] for r in baseline_rows]
        avg, sd = fmean(baseline), pstdev(baseline)
        z = (current - avg) / sd if sd else (0.0 if current == avg else None)
        if not all(isfinite(v) for v in (avg, sd)):
            continue
        if z is not None and not isfinite(z):
            z = None
        useful_ids.update(r.id for r in baseline_rows)
        useful_ids.add(latest.id)
        assessments.append(SignalAssessment(
            signal=signal, current_value=current, baseline_mean=avg, baseline_std=sd,
            z_score=z, risk=normalize_risk(z) if z is not None else None,
            observations_used=len(baseline)+1,
            reason='Deviation cannot be standardized against this baseline' if z is None else None,
        ))
    assessments.sort(key=lambda s: (-(s.risk if s.risk is not None else -1), s.signal))
    result.top_signals = assessments[:3]
    if useful_ids:
        result.observations_used = len(useful_ids)
    scored = [s.risk for s in assessments if s.risk is not None]
    if not scored:
        result.reason = 'No current signal has 10 useful observations and a scorable baseline'
        return result
    risk = max(scored)
    if any(s.risk is None for s in assessments) and risk < WARNING_THRESHOLD:
        result.reason = 'A changed signal has an unscorable baseline; inspect telemetry'
        return result
    result.risk_score = risk
    result.status = 'CRITICAL' if risk >= CRITICAL_THRESHOLD else 'WARNING' if risk >= WARNING_THRESHOLD else 'NORMAL'
    result.recommendation = {
        'CRITICAL': 'Promptly inspect contributing signals and machine operating conditions',
        'WARNING': 'Review contributing signals and schedule an inspection',
        'NORMAL': 'Continue monitoring',
    }[result.status]
    if any(s.risk is None for s in assessments):
        result.reason = 'Some signals have unscorable baselines; risk uses scored signals only'
    return result
