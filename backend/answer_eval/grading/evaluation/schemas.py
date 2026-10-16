"""Evaluation result schemas (Module 14).

Strict Pydantic contracts for LLM-produced semantic grading. The evaluator
PROPOSES criterion marks; Python performs all arithmetic, clamping and
validation afterwards (see grading.evaluation.validation).

The contract is deliberately tolerant of prompt-side naming variants
(``text`` vs ``quote``, ``expected_concept`` vs ``criterion``) so richer
system prompts cannot crash structured parsing.
"""

from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator


class CriterionStatus(StrEnum):
    fully_supported = "fully_supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    contradicted = "contradicted"
    uncertain = "uncertain"
    not_applicable = "not_applicable"


class MatchType(StrEnum):
    exact = "exact"
    exact_keyword_and_meaning = "exact_keyword_and_meaning"
    semantic_equivalent = "semantic_equivalent"
    implicit = "implicit"
    keyword_without_sufficient_meaning = "keyword_without_sufficient_meaning"
    diagram_evidence = "diagram_evidence"
    mixed_evidence = "mixed_evidence"
    none = "none"


class StudentEvidence(BaseModel):
    """Traceable quote from the student's canonical answer."""

    quote: str = Field(
        description="Verbatim (or near-verbatim) quote from the student answer",
        validation_alias=AliasChoices("quote", "text"),
    )
    segment_id: str | None = None
    region_id: str | None = None
    page_number: int | None = None
    verified_in_answer: bool = Field(
        default=False,
        description="Set by the deterministic evidence validator — never trusted from the model",
    )


class CriterionEvaluation(BaseModel):
    criterion_id: str
    criterion: str = Field(
        default="",
        validation_alias=AliasChoices("criterion", "expected_concept"),
    )
    status: CriterionStatus
    match_type: MatchType = MatchType.none
    student_evidence: list[StudentEvidence] = Field(default_factory=list)
    maximum_marks: float = Field(ge=0)
    proposed_marks: float = Field(ge=0)
    reason: str = ""


class Contradiction(BaseModel):
    criterion_id: str | None = None
    concept: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)

    @field_validator("supporting_evidence", "contradicting_evidence", mode="before")
    @classmethod
    def _coerce_str_to_list(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v


class EvaluationResult(BaseModel):
    """Evaluator output. `proposed_total` is COMPUTED by Python, never trusted from the model."""

    schema_version: str = "evaluation-v1"
    question_id: str
    criteria: list[CriterionEvaluation] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    feedback: str = ""
    flags: list[str] = Field(default_factory=list)

    # Richer prompt-side analytics (persisted for inspection; never trusted for arithmetic).
    evaluation_status: str | None = None
    semantic_summary: dict[str, Any] | None = None
    keyword_analysis: dict[str, Any] | None = None
    diagram_analysis: list[dict[str, Any]] | None = None
    semantic_marks: dict[str, Any] | None = None
    deterministic_policy_observations: dict[str, Any] | None = None
    review: dict[str, Any] | None = None

    def criteria_total(self) -> float:
        """Deterministic Python arithmetic — the model's self-reported total is never used."""
        return round(sum(c.proposed_marks for c in self.criteria), 2)
