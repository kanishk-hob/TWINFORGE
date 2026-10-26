from app.kpi.engine import calculate, validate_window
from app.kpi.models import Observation


async def asset_kpis(store, *, source, run_id, asset_id, start, end, max_gap_seconds):
    start, end = validate_window(start, end)
    rows = await store.kpi_observations(source, run_id, asset_id, start, end)
    return calculate([Observation(**row) for row in rows], source=source, run_id=run_id,
                     asset_id=asset_id, start=start, end=end, max_gap_seconds=max_gap_seconds)
