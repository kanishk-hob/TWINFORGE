from typing import Optional, Any
from pydantic import BaseModel, Field


class OperationalMeasurements(BaseModel):
    good_count: int | None = None
    reject_count: int | None = None
    total_count: int | None = None
    interval_power_kw: float | None = None
    interval_seconds: float | None = None


class TwinTelemetry(BaseModel):
    timestamp: Optional[str] = None
    values: Optional[dict[str, Any]] = None


class TwinHealth(BaseModel):
    health_score: float
    anomaly_score: float


class TwinQuality(BaseModel):
    valid: bool
    fresh: bool
    source: str
    reason: Optional[str] = None


class TwinRelationships(BaseModel):
    upstream: Optional[str] = None
    downstream: Optional[str] = None


class MachineTwin(BaseModel):
    # Internal canonical data; preserve the existing twin JSON response contract.
    operations: OperationalMeasurements = Field(default_factory=OperationalMeasurements, exclude=True)
    asset_id: str
    asset_type: str
    factory_id: str
    line_id: str

    state: str
    current_job_id: Optional[str] = None
    active_fault: Optional[str] = None
    sequence: int

    telemetry: TwinTelemetry
    health: TwinHealth
    quality: TwinQuality
    relationships: TwinRelationships
