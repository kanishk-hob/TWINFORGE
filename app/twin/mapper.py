import math

from app.twin.models import (
    OperationalMeasurements,
    MachineTwin,
    TwinTelemetry,
    TwinHealth,
    TwinQuality,
    TwinRelationships,
)


def measurement(value, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (integer and not isinstance(value, int)):
        return None
    return value


def simulator_asset_to_twin(asset: dict, interval_seconds=None) -> MachineTwin:
    identity = asset["identity"]
    dynamic = asset["dynamic_state"]
    production = asset.get("production") or {}
    extensions = asset.get("extensions") or {}

    return MachineTwin(
        operations=OperationalMeasurements(
            good_count=measurement(production.get("good_quantity"), integer=True),
            reject_count=measurement(production.get("rejected_quantity"), integer=True),
            total_count=measurement(production.get("total_quantity"), integer=True),
            interval_power_kw=measurement(extensions.get("last_interval_power_kw")),
            interval_seconds=measurement(interval_seconds),
        ),
        asset_id=asset["asset_id"],
        asset_type=identity["type"],
        factory_id=identity["factory_id"],
        line_id=identity["line_id"],

        state=dynamic["state"],
        current_job_id=dynamic["current_job_id"],
        active_fault=dynamic["active_fault"],
        sequence=dynamic["seq"],

        telemetry=TwinTelemetry(
            timestamp=dynamic["last_telemetry_timestamp"],
            values=dynamic["values"],
        ),

        health=TwinHealth(
            health_score=asset["health"]["health_score"],
            anomaly_score=asset["health"]["anomaly_score"],
        ),

        quality=TwinQuality(
            valid=asset["data_quality"]["valid"],
            fresh=asset["data_quality"]["fresh"],
            source=asset["data_quality"]["source"],
            reason=asset["data_quality"]["reason"],
        ),

        relationships=TwinRelationships(
            upstream=asset["relationships"]["upstream"],
            downstream=asset["relationships"]["downstream"],
        ),
    )
