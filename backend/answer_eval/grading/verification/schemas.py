"""Deterministic evaluator/verifier comparison schemas (Module 15)."""

from pydantic import BaseModel, Field


class CriterionDisagreement(BaseModel):
    criterion_id: str
    criterion: str = ""
    evaluator_status: str = ""
    verifier_status: str = ""
    evaluator_marks: float
    verifier_marks: float
    mark_difference: float


class EvidenceDisagreement(BaseModel):
    criterion_id: str
    detail: str


class VerificationComparison(BaseModel):
    """Python-computed comparison. Never produced by a model."""

    schema_version: str = "verification-comparison-v1"
    question_id: str

    evaluator_total: float
    verifier_total: float
    total_difference: float = Field(description="abs(evaluator_total - verifier_total)")

    criteria_compared: int = 0
    criteria_agreed: int = 0
    criterion_agreement_rate: float = Field(ge=0.0, le=1.0)

    criterion_disagreements: list[CriterionDisagreement] = Field(default_factory=list)
    evidence_disagreements: list[EvidenceDisagreement] = Field(default_factory=list)
    contradiction_disagreements: list[str] = Field(default_factory=list)

    major_disagreement: bool = False
    reasons: list[str] = Field(default_factory=list)
