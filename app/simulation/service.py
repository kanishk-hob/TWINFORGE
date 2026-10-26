"""TWINFORGE owns comparisons; no simulator commands, persistence or source calls."""
from app.simulation.snapshot import freeze_context
from app.simulation.maintenance import model_maintenance, ASSUMPTIONS
from app.simulation.comparison import compare, COMPARISON_RULE
from app.simulation.models import MaintenanceComparison


def compare_maintenance(registry, request):
    context = freeze_context(registry, request)
    a = model_maintenance(context, request, 'maintenance_now')
    b = model_maintenance(context, request, 'maintenance_after_current_batch')
    quality = []
    if not context.source_connected:
        quality.append('Source disconnected or last synchronization stale; job timing unavailable')
    if not context.valid or not context.fresh:
        quality.append('Canonical observation invalid or stale; job timing unavailable')
    if context.state != 'RUNNING' or context.active_fault:
        quality.append('Current state/fault is outside the supported running-work model')
    if not context.current_job_id or not context.current_job_id.strip():
        quality.append('No current job label; after-current-batch timing unavailable')
    if request.remaining_batch_seconds is None:
        quality.append('Remaining batch duration is absent from canonical data and request')
    return MaintenanceComparison(baseline=context, inputs=request, scenario_a=a, scenario_b=b,
        deltas_b_minus_a=compare(a, b), comparison_rule=COMPARISON_RULE,
        assumptions=list(ASSUMPTIONS), data_quality=quality)
