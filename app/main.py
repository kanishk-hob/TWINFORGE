import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app.config import SOURCE_STALE_AFTER_SECONDS, DATABASE_URL, DATABASE_TIMEOUT_SECONDS
from app.storage.postgres import PostgresStore, PersistenceError, HistoryWindowTooLarge
from app.health.models import Assessment, utc
from app.health.service import asset_health
from app.predictive.models import PredictiveHealthResult
from app.predictive.service import assess_predictive_health
from app.storage.models import ObservationRecord, MachineEventRecord
from app.kpi.models import KpiResult
from app.kpi.service import asset_kpis
from app.kpi.engine import validate_window
from app.config import KPI_MAX_GAP_SECONDS
from app.twin.registry import TwinRegistry
from app.services.sync_service import SyncService
from app.simulation.models import MaintenanceComparisonRequest, MaintenanceComparison
from app.simulation.service import compare_maintenance
from app.simulation.snapshot import ContextConflict
from app.recommendation.models import MaintenanceRecommendationRequest, MaintenanceRecommendation
from app.recommendation.service import recommend_maintenance


registry = TwinRegistry()
store = PostgresStore(DATABASE_URL, DATABASE_TIMEOUT_SECONDS) if DATABASE_URL else None
sync_service = SyncService(registry, store=store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start automatic simulator synchronization
    sync_task = asyncio.create_task(
        sync_service.run_forever()
    )

    try:
        yield
    finally:
        # Wake the polling loop and wait for it to finish cleanly.
        sync_service.stop()
        # Cancellation is awaited, including database transaction cleanup.
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        finally:
            if store is not None:
                await store.close()


app = FastAPI(
    title="TWINFORGE",
    lifespan=lifespan
)

app.mount("/dashboard", StaticFiles(
    directory=Path(__file__).resolve().parent / "static" / "dashboard", html=True
), name="dashboard")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "TWINFORGE"
    }


@app.post("/sync")
async def sync_twins():
    try:
        result = await sync_service.sync_once()
    except PersistenceError:
        raise HTTPException(503, "Database persistence failed; snapshot not accepted") from None

    return {
        "status": "synced",
        **result
    }


@app.get("/api/twins")
def get_twins():
    return registry.get_all()


@app.get("/api/twins/{asset_id}")
def get_twin(asset_id: str):
    twin = registry.get(asset_id)

    if twin is None:
        raise HTTPException(
            status_code=404,
            detail="Twin not found"
        )

    return twin

@app.get("/api/source-status")
def source_status():
    sync_lag_seconds = None

    if registry.last_sync_at is not None:
        now = datetime.now(timezone.utc)
        sync_lag_seconds = (
            now - registry.last_sync_at
        ).total_seconds()

    return {
        "source": "factory_simulator",
        "connected": registry.is_source_connected(SOURCE_STALE_AFTER_SECONDS),
        "run_id": registry.current_run_id,
        "last_sync_at": registry.last_sync_at,
        "last_sync_attempt_at": registry.last_sync_attempt_at,
        "last_sync_error": registry.last_sync_error,
        "consecutive_failures": registry.consecutive_failures,
        "sync_lag_seconds": sync_lag_seconds,
        "stale_after_seconds": SOURCE_STALE_AFTER_SECONDS,
    }


@app.get("/api/persistence-status")
def persistence_status():
    return {
        "enabled": store is not None,
        "last_persisted_at": sync_service.last_persisted_at,
        "last_error": sync_service.last_persistence_error,
    }


async def read_history(asset_id, kind, limit, after_id, run_id):
    if store is None:
        raise HTTPException(503, "Persistence is not configured")
    try:
        return await store.history(asset_id, kind, limit, after_id, run_id)
    except PersistenceError:
        raise HTTPException(503, "Historical storage is unavailable") from None


@app.get("/api/twins/{asset_id}/telemetry", response_model=list[ObservationRecord])
async def telemetry_history(asset_id: str, limit: int = Query(100, ge=1, le=1000),
                            after_id: int = Query(0, ge=0), run_id: str | None = None):
    return await read_history(asset_id, "telemetry", limit, after_id, run_id)


@app.get("/api/twins/{asset_id}/history", response_model=list[MachineEventRecord])
async def machine_history(asset_id: str, limit: int = Query(100, ge=1, le=1000),
                          after_id: int = Query(0, ge=0), run_id: str | None = None):
    return await read_history(asset_id, "history", limit, after_id, run_id)


@app.get("/api/twins/{asset_id}/predictive-health", response_model=PredictiveHealthResult)
async def get_predictive_health(
    asset_id: str, run_id: str = Query(..., min_length=1, max_length=200),
    method: Literal['rolling_z_score', 'z_score_ewma'] = 'rolling_z_score',
):
    if not asset_id.strip() or not run_id.strip():
        raise HTTPException(422, "Nonblank asset_id and run_id required")
    if store is None:
        raise HTTPException(503, "Persistence is not configured")
    try:
        return await assess_predictive_health(store, asset_id=asset_id, run_id=run_id, method=method)
    except PersistenceError:
        raise HTTPException(503, "Historical storage is unavailable") from None
    except Exception:
        raise HTTPException(500, "Predictive assessment failed") from None


@app.get("/api/twins/{asset_id}/kpis", response_model=KpiResult)
async def get_kpis(asset_id: str, start: datetime, end: datetime,
                   run_id: str = Query(..., min_length=1, max_length=200),
                   source: str = Query("factory_simulator", min_length=1, max_length=200)):
    try:
        start, end = validate_window(start, end)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if store is None:
        raise HTTPException(503, "Persistence is not configured")
    try:
        return await asset_kpis(store, source=source, run_id=run_id, asset_id=asset_id,
                                start=start, end=end, max_gap_seconds=KPI_MAX_GAP_SECONDS)
    except PersistenceError:
        raise HTTPException(503, "Historical storage is unavailable") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/twins/{asset_id}/health-assessment", response_model=Assessment)
async def get_health_assessment(
    asset_id: str, start: datetime, end: datetime, assessment_generated_at: datetime,
    source: str = Query(..., min_length=1, max_length=200),
    run_id: str = Query(..., min_length=1, max_length=200),
):
    # Validate request data separately: ValueErrors from persisted evidence are
    # internal failures, not client errors, and must not expose their details.
    try:
        start, end, generated = map(utc, (start, end, assessment_generated_at))
        if not asset_id.strip() or not source.strip() or not run_id.strip():
            raise ValueError("Nonblank asset_id, source and run_id required")
        if not 0 < (end-start).total_seconds() <= 86400:
            raise ValueError("Health window must be positive and at most 24 hours")
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if store is None:
        raise HTTPException(503, "Persistence is not configured")
    try:
        return await asset_health(
            store, source=source, run_id=run_id, asset_id=asset_id,
            window_start=start, window_end=end, assessment_generated_at=generated,
        )
    except HistoryWindowTooLarge:
        raise HTTPException(422, "Health evidence exceeds supported bounds; use a smaller window") from None
    except PersistenceError:
        raise HTTPException(503, "Historical storage is unavailable") from None
    except Exception:
        raise HTTPException(500, "Health assessment failed") from None


@app.post('/api/scenarios/maintenance/compare', response_model=MaintenanceComparison)
async def compare_maintenance_scenarios(request: MaintenanceComparisonRequest):
    # No await: freeze and calculate on one event-loop turn, before sync can update context.
    try:
        return compare_maintenance(registry, request)
    except ContextConflict as error:
        raise HTTPException(409, str(error)) from None
    except KeyError:
        raise HTTPException(404, 'Twin not found') from None


@app.post('/api/recommendations/maintenance', response_model=MaintenanceRecommendation)
async def get_maintenance_recommendation(request: MaintenanceRecommendationRequest):
    try:
        return await recommend_maintenance(registry, store, request)
    except ContextConflict as error:
        raise HTTPException(409, str(error)) from None
    except KeyError:
        raise HTTPException(404, 'Twin not found') from None
    except Exception:
        raise HTTPException(500, 'Maintenance recommendation failed') from None
