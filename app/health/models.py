"""Explicit health evidence, independent of MachineTwin.health."""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class Evidence(BaseModel):
    id: int = Field(gt=0, strict=True)
    asset_id: str
    source: str
    run_id: str
    sequence: int = Field(ge=0, strict=True)
    observed_at: datetime
    source_timestamp: datetime | None = None

    @field_validator('observed_at', 'source_timestamp')
    @classmethod
    def aware(cls, value):
        return utc(value) if value is not None else None


class Observation(Evidence):
    state: str
    active_fault: str | None = None
    valid: bool = Field(strict=True)
    fresh: bool = Field(strict=True)
    telemetry_values: dict[str, Any] | None = None
    quality_source: str
    reason: str | None = None


class Event(Evidence):
    kind: Literal['state_observed', 'state_changed', 'fault_observed',
                  'fault_started', 'fault_recovered']
    previous_value: str | None = None
    value: str | None = None


class Reference(BaseModel):
    kind: Literal['observation', 'event']
    id: int
    sequence: int
    observed_at: datetime
    source_timestamp: datetime | None = None


class Indicator(BaseModel):
    status: Literal['observed', 'not_observed', 'unavailable']
    value: str | bool | int | None = None
    reason: str
    evidence: list[Reference] = Field(default_factory=list)


class DataQuality(BaseModel):
    evidence_complete: bool
    observation_count: int
    event_count: int
    usable_observation_count: int
    missing_source_timestamps: int
    invalid_observations: int
    stale_observations: int
    missing_telemetry: int
    sequence_gaps: int
    sequence_reversals: int
    nonincreasing_source_timestamps: int
    findings: list[str]


class Assessment(BaseModel):
    contract_version: Literal['health.v1'] = 'health.v1'
    method: Literal['observed_condition_rules'] = 'observed_condition_rules'
    asset_id: str
    source: str
    run_id: str
    assessment_generated_at: datetime
    window_start: datetime
    window_end: datetime
    time_basis: Literal['receipt'] = 'receipt'
    latest_source_timestamp: datetime | None
    latest_observed_at: datetime | None
    availability: Literal['available', 'partial', 'unavailable']
    reasons: list[str]
    data_quality: DataQuality
    indicators: dict[str, Indicator]
