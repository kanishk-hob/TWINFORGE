"""Small, explicit timing model, not a second factory execution simulator."""
from app.kpi.models import Metric
from app.simulation.models import ScenarioResult

ASSUMPTIONS = [
    'Maintenance duration is a caller-supplied modeled stop, not a measured repair time',
    'Remaining batch time, if supplied, is a caller estimate at the frozen observation',
    'The current job ID is used only as a label; it does not prove batch size or progress',
    'Immediate maintenance pauses work and resumes without scrap, restart or setup penalty',
    'Deferred maintenance starts immediately after the modeled current batch completes',
    'No additional faults, repairs, blocking, starvation, crew waits or scheduling constraints are modeled',
    'Both alternatives use the same remaining work and maintenance duration',
    'A zero remaining duration means the current batch is already complete at scenario time zero',
    'Maintenance has no modeled effect on predictive risk or future fault likelihood',
    'Only the selected machine is modeled; factory and related-job propagation are unavailable',
]


def estimate(value, reason):
    return Metric(value=value, unit='seconds', status='estimated', reason=reason)


def model_maintenance(context, request, action):
    d, r = request.maintenance_duration_seconds, request.remaining_batch_seconds
    supported = (context.source_connected and context.valid and context.fresh
                 and context.state == 'RUNNING' and not context.active_fault
                 and bool(context.current_job_id and context.current_job_id.strip()) and r is not None)
    unknown_reason = ('Requires connected valid/fresh RUNNING context without an active fault, '
                      'a current job ID and caller-supplied remaining_batch_seconds')
    metrics = {
        'projected_maintenance_downtime_seconds': estimate(d, 'Caller-modeled maintenance duration'),
        'maintenance_start_offset_seconds': estimate(0, 'Immediate start by definition')
            if action == 'maintenance_now' else Metric(unit='seconds', reason=unknown_reason),
        'maintenance_end_offset_seconds': estimate(d, 'Immediate start plus caller-modeled stop')
            if action == 'maintenance_now' else Metric(unit='seconds', reason=unknown_reason),
    }
    for key in ('current_batch_completion_offset_seconds', 'current_batch_delay_seconds',
                'scenario_duration_seconds'):
        metrics[key] = Metric(unit='seconds', reason=unknown_reason)
    if supported:
        immediate = action == 'maintenance_now'
        delay = d if immediate and r > 0 else 0
        metrics.update(
            maintenance_start_offset_seconds=estimate(0 if immediate else r, 'Offset from frozen scenario time zero'),
            maintenance_end_offset_seconds=estimate(d if immediate else r+d, 'Maintenance start plus modeled stop'),
            current_batch_completion_offset_seconds=estimate(r+delay, 'Remaining work plus interruption; an already completed batch is not delayed'),
            current_batch_delay_seconds=estimate(delay, 'Delay relative to no-maintenance completion at remaining_batch_seconds'),
            scenario_duration_seconds=estimate(r+d, 'Common horizon: both current batch and maintenance completed'),
        )
    for key, unit, reason in (
        ('good_unit_impact', 'good units', 'No batch quantity, yield or validated production-rate model'),
        ('throughput_impact', 'good units/hour', 'No validated future production-rate or common-horizon output model'),
        ('energy_impact', 'kWh', 'No running/maintenance/restart power model'),
    ):
        metrics[key] = Metric(unit=unit, reason=reason)
    return ScenarioResult(action=action, status='estimated' if supported else 'partial',
        metrics=metrics, affected_jobs=[context.current_job_id] if supported else [],
        assumptions=list(ASSUMPTIONS),
        unavailable=[f'{key}: {metric.reason}' for key, metric in metrics.items() if metric.value is None]
                    + ['Other affected jobs and downstream completion impacts are unknown'])
