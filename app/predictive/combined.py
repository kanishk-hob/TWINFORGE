"""Combines independent Z-score and EWMA evidence without averaging alerts away."""
from app.predictive.config import (
    BASELINE_SIZE, EWMA_MONITOR_SIZE, EWMA_MIN_MONITOR_OBSERVATIONS,
    WARNING_THRESHOLD, CRITICAL_THRESHOLD,
)
from app.predictive.engine import predict_health, numeric, SUPPORTED_SIGNALS
from app.predictive.ewma import assess_ewma
from app.predictive.models import SignalAssessment

EVIDENCE_SIZE = BASELINE_SIZE + EWMA_MONITOR_SIZE


def predict_combined(asset_id, observations, *, source, run_id):
    # Reuse v1 validation, current-value handling and exact rolling calculation.
    result = predict_health(asset_id, observations, source=source, run_id=run_id)
    result.contract_version = 'predictive.v2'
    result.method = 'z_score_ewma'
    rows = sorted({r.id: r for r in observations}.values(), key=lambda r: r.id)[-EVIDENCE_SIZE:]
    result.z_score_risk = result.risk_score
    result.top_signals = []
    result.risk_score = None
    result.status = 'INSUFFICIENT_DATA'
    result.reason = None
    result.observations_used = 0
    if len(rows) < BASELINE_SIZE + EWMA_MIN_MONITOR_OBSERVATIONS:
        result.reason = 'EWMA requires 30 reference records and at least 10 monitoring records'
        result.recommendation = 'Collect valid, fresh telemetry and review data quality'
        return result
    if len({r.sequence for r in rows}) != len(rows):
        raise ValueError('Duplicate observation sequence')
    reference, monitor = rows[:BASELINE_SIZE], rows[BASELINE_SIZE:]
    latest = rows[-1]
    assessments, used = [], set()
    for signal in sorted(SUPPORTED_SIGNALS):
        def usable(row):
            return (row.valid and row.fresh and row.telemetry_values
                    and numeric(row.telemetry_values.get(signal)))
        # No compression across missing samples: EWMA requires an intact series.
        if not all(usable(r) for r in rows):
            continue
        trend = assess_ewma([r.telemetry_values[signal] for r in reference],
                            [r.telemetry_values[signal] for r in monitor])
        single = predict_health(asset_id, [r.model_copy(update={'telemetry_values':
            {signal:r.telemetry_values[signal]}}) for r in rows], source=source, run_id=run_id)
        if not single.top_signals:
            continue
        z = single.top_signals[0]
        risks = [v for v in (z.risk, trend.risk) if v is not None]
        combined = max(risks) if risks else None
        assessments.append(SignalAssessment(
            signal=signal, current_value=latest.telemetry_values[signal],
            baseline_mean=z.baseline_mean, baseline_std=z.baseline_std, z_score=z.z_score,
            risk=combined, z_score_risk=z.risk, ewma=trend,
            dominant_method='ewma' if trend.risk is not None and (z.risk is None or trend.risk > z.risk)
                            else 'rolling_z_score' if z.risk is not None else None,
            observations_used=len(rows),
            reason='One or more detectors are unscorable' if z.risk is None or trend.risk is None else None,
        ))
        used.update(r.id for r in rows)
    assessments.sort(key=lambda s: (-(s.risk if s.risk is not None else -1), s.signal))
    result.top_signals = assessments[:3]
    result.observations_used = len(used)
    z_risks = [s.z_score_risk for s in assessments if s.z_score_risk is not None]
    e_risks = [s.ewma.risk for s in assessments if s.ewma.risk is not None]
    result.z_score_risk = max(z_risks, default=None)
    result.ewma_risk = max(e_risks, default=None)
    scored = [s for s in assessments if s.risk is not None]
    if not scored:
        result.reason = 'No signal has complete useful evidence and a scorable detector'
        result.recommendation = 'Collect valid, fresh telemetry and review data quality'
        return result
    top = scored[0]
    if top.risk < WARNING_THRESHOLD and any(s.reason for s in assessments):
        result.reason = 'Unscorable detector evidence prevents a NORMAL assessment'
        result.recommendation = 'Review data quality and constant-baseline changes'
        return result
    result.risk_score = top.risk
    result.status = ('CRITICAL' if top.risk >= CRITICAL_THRESHOLD else
                     'WARNING' if top.risk >= WARNING_THRESHOLD else 'NORMAL')
    result.dominant_signal, result.dominant_method = top.signal, top.dominant_method
    result.explanation = f'{top.signal}: {top.dominant_method} contributed the highest risk ({top.risk:.3f})'
    result.recommendation = ('Continue monitoring' if result.status == 'NORMAL' else
                             'Review contributing signals and machine operating conditions; arrange inspection')
    result.reason = ('Some detectors are unscorable; risk uses scored evidence only'
                     if any(s.reason for s in assessments) else None)
    return result
