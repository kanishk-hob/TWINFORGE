"""Read the same persisted telemetry stream as the telemetry history route."""
from app.predictive.engine import BASELINE_SIZE, predict_health
from app.predictive.combined import EVIDENCE_SIZE, predict_combined
from app.storage.models import ObservationRecord


async def assess_predictive_health(store, *, asset_id: str, run_id: str, method: str = 'rolling_z_score'):
    if method not in ('rolling_z_score', 'z_score_ewma'):
        raise ValueError('Unsupported predictive method')
    limit = EVIDENCE_SIZE if method == 'z_score_ewma' else BASELINE_SIZE + 1
    rows = await store.history(asset_id, 'telemetry', limit, 0, run_id,
                               latest=True)
    detector = predict_combined if method == 'z_score_ewma' else predict_health
    return detector(asset_id, [ObservationRecord(**row) for row in rows],
                          source='factory_simulator', run_id=run_id)
