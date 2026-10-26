from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel


class ObservationRecord(BaseModel):
    id: int
    source: str
    run_id: str
    asset_id: str
    sequence: int
    observed_at: datetime
    source_timestamp: datetime | None
    raw_source_timestamp: str | None
    telemetry_values: dict[str, Any] | None
    valid: bool
    fresh: bool
    quality_source: str
    reason: str | None


class MachineEventRecord(BaseModel):
    id: int
    source: str
    run_id: str
    asset_id: str
    sequence: int
    observed_at: datetime
    kind: Literal['state_observed', 'state_changed', 'fault_observed', 'fault_started', 'fault_recovered']
    previous_value: str | None
    value: str | None
