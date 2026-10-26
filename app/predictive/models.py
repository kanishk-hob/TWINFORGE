"""Independent statistical screening; risk is not a failure probability."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class TrendAssessment(BaseModel):
    alpha: float
    value: float
    baseline_mean: float
    baseline_std: float
    standardized_deviation: float | None
    risk: float | None = Field(default=None, ge=0, le=1)
    baseline_observations: int
    monitoring_observations: int
    reason: str | None = None


class SignalAssessment(BaseModel):
    signal: str
    z_score_risk: float | None = Field(default=None, ge=0, le=1)
    ewma: TrendAssessment | None = None
    dominant_method: Literal['rolling_z_score', 'ewma'] | None = None
    current_value: float
    baseline_mean: float
    baseline_std: float = Field(ge=0)
    z_score: float | None
    risk: float | None = Field(default=None, ge=0, le=1)
    observations_used: int
    reason: str | None = None


class PredictiveHealthResult(BaseModel):
    contract_version: Literal['predictive.v1', 'predictive.v2'] = 'predictive.v1'
    method: Literal['rolling_z_score', 'z_score_ewma'] = 'rolling_z_score'
    z_score_risk: float | None = Field(default=None, ge=0, le=1)
    ewma_risk: float | None = Field(default=None, ge=0, le=1)
    dominant_signal: str | None = None
    dominant_method: Literal['rolling_z_score', 'ewma'] | None = None
    explanation: str | None = None
    asset_id: str
    source: str
    run_id: str
    latest_observed_at: datetime | None = None
    status: Literal['NORMAL', 'WARNING', 'CRITICAL', 'INSUFFICIENT_DATA']
    risk_score: float | None = Field(default=None, ge=0, le=1)
    top_signals: list[SignalAssessment] = Field(default_factory=list)
    recommendation: str
    observations_used: int
    reason: str | None = None
