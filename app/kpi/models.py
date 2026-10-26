from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class Observation:
    source: str
    run_id: str
    asset_id: str
    sequence: int
    source_timestamp: datetime | None
    valid: bool
    fresh: bool
    state: str
    active_fault: str | None = None
    good_count: int | None = None
    reject_count: int | None = None
    total_count: int | None = None
    interval_power_kw: float | None = None
    interval_seconds: float | None = None


class Metric(BaseModel):
    value: float | None = None
    unit: str
    status: Literal['ok', 'estimated', 'unknown', 'not_applicable'] = 'unknown'
    reason: str | None = None


class KpiResult(BaseModel):
    contract_version: Literal['kpi.v1'] = 'kpi.v1'
    source: str
    run_id: str
    asset_id: str
    start: datetime
    end: datetime
    window_seconds: float
    max_gap_seconds: float
    coverage: float
    observation_count: int
    completeness: Literal['complete', 'incomplete']
    reasons: list[str]
    metrics: dict[str, Metric]
    downtime_reasons_seconds: dict[str, float] | None = None
