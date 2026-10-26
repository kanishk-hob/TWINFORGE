"""Independent EWMA detector with a held-out reference baseline."""
from math import isfinite, sqrt
from statistics import fmean, pstdev

from app.predictive.config import EWMA_ALPHA
from app.predictive.engine import normalize_risk
from app.predictive.models import TrendAssessment


def assess_ewma(baseline: list[float], monitoring: list[float]) -> TrendAssessment:
    mean, std = fmean(baseline), pstdev(baseline)
    value = mean
    for current in monitoring:
        value += EWMA_ALPHA * (current - value)
    n = len(monitoring)
    scale = std * sqrt(EWMA_ALPHA / (2 - EWMA_ALPHA)
                       * (1 - (1 - EWMA_ALPHA) ** (2 * n)))
    score = (value - mean) / scale if scale else (0.0 if value == mean else None)
    if score is not None and not isfinite(score):
        score = None
    return TrendAssessment(
        alpha=EWMA_ALPHA, value=value, baseline_mean=mean, baseline_std=std,
        standardized_deviation=score, risk=normalize_risk(score) if score is not None else None,
        baseline_observations=len(baseline), monitoring_observations=n,
        reason='Changed zero-variance or numerically unscorable reference baseline' if score is None else None,
    )
