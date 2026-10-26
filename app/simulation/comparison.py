"""Transparent operational deltas; ranking belongs to a future recommendation layer."""
from app.kpi.models import Metric

COMPARISON_RULE = (
    'Deltas are scenario B minus A on a shared modeled horizon when available. '
    'No preferred scenario: earlier batch completion trades against later maintenance; '
    'failure likelihood, urgency and scheduling costs are not modeled.'
)


def compare(a, b):
    result = {}
    for key, left in a.metrics.items():
        right = b.metrics[key]
        if left.value is None or right.value is None:
            result[key] = Metric(unit=left.unit, reason='At least one scenario metric is unavailable')
        else:
            result[key] = Metric(value=right.value-left.value, unit=left.unit,
                                 status='estimated', reason='Scenario B minus A; conditional timing model')
    return result
