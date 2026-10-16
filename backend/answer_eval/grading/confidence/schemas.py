"""Heuristic risk engine output schemas (Module 16)."""

from pydantic import BaseModel, Field

RISK_POLICY_VERSION = "heuristic-risk-v1"


class RiskSignals(BaseModel):
    """Individual normalized 0-1 risk signals (deterministically computed)."""

    ocr_uncertainty: float = 0.0
    segmentation_uncertainty: float = 0.0
    diagram_uncertainty: float = 0.0
    grader_disagreement: float = 0.0
    evidence_risk: float = 0.0
    validation_risk: float = 0.0


class RiskAssessment(BaseModel):
    """Deterministic risk decision. NEVER derived from model self-reported confidence."""

    schema_version: str = RISK_POLICY_VERSION
    risk_policy_version: str = RISK_POLICY_VERSION
    question_id: str = ""

    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: str = "low"  # low | medium | high
    auto_approve: bool = False

    signals: RiskSignals = Field(default_factory=RiskSignals)
    review_reasons: list[str] = Field(default_factory=list)
    hard_validations_passed: bool = True
