"""Observed, calculated, assumed and policy evidence remain separately labeled."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.predictive.models import PredictiveHealthResult
from app.simulation.models import MaintenanceComparison, MaintenanceComparisonRequest


class MaintenanceRecommendationRequest(MaintenanceComparisonRequest):
    predictive_method: Literal['rolling_z_score', 'z_score_ewma'] = 'z_score_ewma'


class EvidenceReference(BaseModel):
    latest_observation_id: int | None = None
    latest_sequence: int | None = None
    latest_observed_at: datetime | None = None
    receipt_age_seconds: float | None = None
    matches_canonical_sequence: bool = False


class RecommendationQuality(BaseModel):
    classification: Literal['adequate', 'partial', 'unavailable']
    canonical_usable: bool
    predictive_usable: bool
    timing_complete: bool
    findings: list[str]
    meaning: str = 'Evidence suitability for this policy, not statistical confidence or physical safety certification'


class MaintenanceRecommendation(BaseModel):
    contract_version: Literal['recommendation.v1'] = 'recommendation.v1'
    policy_version: str
    policy_parameters: dict[str, float | str]
    asset_id: str
    run_id: str
    sequence: int
    generated_at: datetime
    recommended_action: Literal['continue_monitoring', 'maintenance_after_current_batch',
                                'maintenance_now', 'manual_review_required']
    recommendation_status: Literal['recommended', 'degraded', 'review_required']
    rule_id: str
    explanation: str
    human_approval_required: bool
    automatic_execution_allowed: Literal[False] = False
    predictive_status_used: str | None
    predictive_risk_used: float | None = Field(ge=0, le=1)
    calculated_predictive_evidence: PredictiveHealthResult | None
    estimated_scenario_evidence: MaintenanceComparison
    predictive_evidence_reference: EvidenceReference
    assumptions: list[str]
    missing_evidence: list[str]
    data_quality: RecommendationQuality
