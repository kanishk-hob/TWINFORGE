"""Typed maintenance timing comparisons; no physical failure forecast."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.kpi.models import Metric

Action = Literal['maintenance_now', 'maintenance_after_current_batch']


class MaintenanceComparisonRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    asset_id: str = Field(min_length=1, max_length=200, pattern=r'\S')
    run_id: str = Field(min_length=1, max_length=200, pattern=r'\S')
    maintenance_duration_seconds: float = Field(gt=0, le=604800, strict=True, allow_inf_nan=False)
    remaining_batch_seconds: float | None = Field(default=None, ge=0, le=604800,
                                                 description='Caller-assumed remaining processing time for the current batch; not observed by TWINFORGE',
                                                 strict=True, allow_inf_nan=False)
    expected_sequence: int | None = Field(default=None, ge=0, strict=True)


class CurrentContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Literal['factory_simulator'] = 'factory_simulator'
    run_id: str
    asset_id: str
    factory_id: str
    line_id: str
    sequence: int
    state: str
    current_job_id: str | None
    active_fault: str | None
    upstream: str | None
    downstream: str | None
    source_timestamp: str | None
    captured_at: datetime
    last_sync_at: datetime | None
    source_connected: bool
    valid: bool
    fresh: bool
    quality_reason: str | None


class ScenarioResult(BaseModel):
    action: Action
    status: Literal['estimated', 'partial']
    metrics: dict[str, Metric]
    affected_jobs: list[str]
    affected_jobs_complete: bool = False
    assumptions: list[str]
    unavailable: list[str]


class MaintenanceComparison(BaseModel):
    contract_version: Literal['simulation.v1'] = 'simulation.v1'
    method: Literal['deterministic_maintenance_timing'] = 'deterministic_maintenance_timing'
    live_state_mutated: Literal[False] = False
    evidence_basis: Literal['canonical_source_observations_and_caller_assumptions'] = 'canonical_source_observations_and_caller_assumptions'
    baseline: CurrentContext
    inputs: MaintenanceComparisonRequest
    scenario_a: ScenarioResult
    scenario_b: ScenarioResult
    deltas_b_minus_a: dict[str, Metric]
    preferred_scenario: Action | None = None
    comparison_rule: str
    assumptions: list[str]
    data_quality: list[str]
