"""Pure deterministic advisory rules; consumes evidence, never calculates predictions."""
from math import isfinite

from app.recommendation.config import (
    POLICY_VERSION, MAX_WARNING_DEFERRAL_SECONDS, MAX_PREDICTIVE_RECEIPT_AGE_SECONDS,
    MIN_MAINTENANCE_EVIDENCE_QUALITY, STATUS_RISK_BOUNDS,
)
from app.recommendation.models import MaintenanceRecommendation, RecommendationQuality

TIMING_METRICS = (
    'projected_maintenance_downtime_seconds', 'maintenance_start_offset_seconds',
    'maintenance_end_offset_seconds', 'current_batch_completion_offset_seconds',
    'current_batch_delay_seconds', 'scenario_duration_seconds',
)


def evaluate(comparison, predictive, reference, *, generated_at, evidence_issues=()):
    context = comparison.baseline
    canonical_usable = bool(context.source_connected and context.valid and context.fresh
                            and context.state == 'RUNNING' and not context.active_fault)
    findings = list(evidence_issues)
    if not canonical_usable:
        findings.append('Current canonical state must be connected, valid/fresh, RUNNING and without an active fault')

    predictive_issues = []
    if predictive is None:
        predictive_issues.append('Independent predictive evidence is unavailable')
    else:
        if (predictive.asset_id, predictive.run_id, predictive.source) != (context.asset_id, context.run_id, context.source):
            predictive_issues.append('Predictive evidence context does not match the frozen scenario')
        bounds = STATUS_RISK_BOUNDS.get(predictive.status)
        risk = predictive.risk_score
        if (bounds is None or risk is None or not isfinite(risk)
                or not bounds[0] <= risk <= bounds[1]
                or (predictive.status != 'CRITICAL' and risk == bounds[1])):
            predictive_issues.append('Predictive status/risk is insufficient or inconsistent')
        if not predictive.top_signals or predictive.reason or any(s.reason for s in predictive.top_signals):
            predictive_issues.append('Predictive result has missing or partial signal evidence')
    if not reference.matches_canonical_sequence:
        predictive_issues.append('Persisted predictive evidence is not aligned to the canonical sequence')
    age = reference.receipt_age_seconds
    if age is None or not isfinite(age) or not 0 <= age <= MAX_PREDICTIVE_RECEIPT_AGE_SECONDS:
        predictive_issues.append('Latest persisted observation is missing, future-dated or older than the receipt-age limit')
    predictive_usable = not predictive_issues and not evidence_issues
    findings.extend(predictive_issues)

    scenarios = (comparison.scenario_a, comparison.scenario_b)
    timing_complete = (
        comparison.scenario_a.action == 'maintenance_now'
        and comparison.scenario_b.action == 'maintenance_after_current_batch'
        and not comparison.data_quality
        and all(s.status == 'estimated' and all(
            key in s.metrics and s.metrics[key].status == 'estimated'
            and s.metrics[key].value is not None and isfinite(s.metrics[key].value)
            and s.metrics[key].value >= 0 and s.metrics[key].unit == 'seconds'
            for key in TIMING_METRICS) for s in scenarios)
    )
    if not timing_complete:
        findings.append('What-if timing comparison is incomplete for maintenance selection')
    findings.extend(comparison.data_quality)
    quality = ('unavailable' if predictive is None or predictive.status == 'INSUFFICIENT_DATA'
               else 'adequate' if canonical_usable and predictive_usable and timing_complete else 'partial')

    action, status, rule = 'manual_review_required', 'review_required', 'R1_EVIDENCE_INADEQUATE'
    explanation = 'Review missing, stale or inconsistent evidence before selecting a maintenance action'
    if canonical_usable and predictive_usable:
        if predictive.status == 'NORMAL':
            action, rule = 'continue_monitoring', 'R2_NORMAL'
            status = 'recommended' if timing_complete else 'degraded'
            explanation = 'NORMAL independent predictive evidence supports continued monitoring; this is not a guarantee of machine safety'
            if not timing_complete:
                explanation += '; incomplete what-if timing prevents maintenance comparison advice'
        elif quality != MIN_MAINTENANCE_EVIDENCE_QUALITY:
            rule = 'R3_TIMING_INCOMPLETE'
            explanation = 'Maintenance selection requires a complete supported timing comparison'
        elif predictive.status == 'WARNING':
            deferral = comparison.scenario_b.metrics['maintenance_start_offset_seconds'].value
            if deferral <= MAX_WARNING_DEFERRAL_SECONDS:
                action, status, rule = 'maintenance_after_current_batch', 'recommended', 'R4_WARNING_BOUNDED_DEFERRAL'
                explanation = (f'WARNING policy permits a caller-modeled deferral of {deferral:g} seconds, '
                               f'within the configured {MAX_WARNING_DEFERRAL_SECONDS:g}-second limit; operator approval is required')
            else:
                rule = 'R5_WARNING_DEFERRAL_EXCEEDED'
                explanation = (f'Caller-modeled deferral of {deferral:g} seconds exceeds the '
                               f'{MAX_WARNING_DEFERRAL_SECONDS:g}-second WARNING policy limit; review manually')
        elif predictive.status == 'CRITICAL':
            action, status, rule = 'maintenance_now', 'recommended', 'R6_CRITICAL'
            explanation = 'CRITICAL independent predictive evidence takes precedence over modeled batch delay under this policy; operator approval is required'

    missing = findings + [item for s in scenarios for item in s.unavailable]
    return MaintenanceRecommendation(
        policy_version=POLICY_VERSION,
        policy_parameters=dict(max_warning_deferral_seconds=MAX_WARNING_DEFERRAL_SECONDS,
                               max_predictive_receipt_age_seconds=MAX_PREDICTIVE_RECEIPT_AGE_SECONDS,
                               minimum_maintenance_evidence_quality=MIN_MAINTENANCE_EVIDENCE_QUALITY,
                               warning_risk_threshold=STATUS_RISK_BOUNDS['WARNING'][0],
                               critical_risk_threshold=STATUS_RISK_BOUNDS['CRITICAL'][0]),
        asset_id=context.asset_id, run_id=context.run_id, sequence=context.sequence,
        generated_at=generated_at, recommended_action=action, recommendation_status=status,
        rule_id=rule, explanation=explanation, human_approval_required=action != 'continue_monitoring',
        predictive_status_used=predictive.status if predictive else None,
        predictive_risk_used=predictive.risk_score if predictive else None,
        calculated_predictive_evidence=predictive, estimated_scenario_evidence=comparison,
        predictive_evidence_reference=reference,
        assumptions=list(comparison.assumptions) + [
            'Policy thresholds are provisional; the WARNING deferral limit is not a validated safe operating duration',
            'Predictive risk is statistical deviation, not failure probability or time to failure',
            'Adequate evidence means sufficient for this advisory policy, not complete sensor or factory coverage',
            'Only the outer recommendation policy decision selects an action; embedded predictive advice is evidence context',
            'All maintenance requires operator approval and separate execution procedures',
        ],
        missing_evidence=list(dict.fromkeys(missing)),
        data_quality=RecommendationQuality(classification=quality, canonical_usable=canonical_usable,
            predictive_usable=predictive_usable, timing_complete=timing_complete,
            findings=list(dict.fromkeys(findings))),
    )
