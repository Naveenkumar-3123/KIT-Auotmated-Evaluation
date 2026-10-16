"""Final graded-answer record (assembled by grading.service — Modules 12-16).

All arithmetic is computed in Python. The evaluator/verifier self-reported
totals are never trusted. Raw chain-of-thought is never stored: only criterion
decisions, evidence, short reasons, feedback, flags and versions.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from answer_eval.grading.confidence.schemas import RiskAssessment
from answer_eval.grading.evaluation.schemas import EvaluationResult
from answer_eval.grading.rules.schemas import DeterministicPenalty, RuleEvaluationResult
from answer_eval.grading.verification.comparator import VerificationComparison


class MarksBreakdown(BaseModel):
    criteria_total: float = 0.0
    deterministic_penalty: float = 0.0
    final_proposed_marks: float = 0.0
    maximum_marks: float = 0.0
    minimum_allowed_marks: float = 0.0
    penalty_components: list[DeterministicPenalty] = Field(
        default_factory=list,
        description="Itemized penalties — every deduction is auditable and applied exactly once",
    )


class VersionInfo(BaseModel):
    rubric: str = "rubric-v1"
    strictness_policy: str = "strictness-v1"
    evaluation_prompt: str = "evaluation-v2"
    verification_prompt: str = "verification-v2"
    risk_policy: str = "heuristic-risk-v1"
    model: str = ""
    quantization: str | None = None
    provider: str = ""
    teacher_rules_version: int | None = Field(
        default=None, description="Resolved question_policies version applied (spec #81)"
    )


class ReviewInfo(BaseModel):
    required: bool = False
    reasons: list[str] = Field(default_factory=list)
    status: str = "auto_approved"  # auto_approved | waiting_for_review | reviewed
    reviewer_notes: str | None = None
    final_marks_override: float | None = Field(default=None, ge=0)


class GradedAnswer(BaseModel):
    """Complete grading record for one question."""

    schema_version: str = "graded-answer-v1"
    submission_id: str
    question_id: str

    rule_result: RuleEvaluationResult
    evaluation: EvaluationResult
    verification: EvaluationResult
    comparison: VerificationComparison
    risk: RiskAssessment

    marks: MarksBreakdown
    versions: VersionInfo = Field(default_factory=VersionInfo)
    review: ReviewInfo = Field(default_factory=ReviewInfo)
    flags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def status(self) -> str:
        """Workflow-facing status: finalized or waiting_for_review."""
        return "finalized" if not self.review.required else "waiting_for_review"
