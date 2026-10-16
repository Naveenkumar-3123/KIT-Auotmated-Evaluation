"""Answer-key / rubric schemas for the grading pipeline (Modules 12-14).

The rubric is the teacher's authoritative grading contract. It is validated
BEFORE any LLM sees it: an invalid rubric must never reach the evaluator.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from answer_eval.core.errors import RubricValidationError  # noqa: F401  (public re-export)
from answer_eval.grading.math_schemas import MathRubric

RUBRIC_SCHEMA_VERSION = "rubric-v1"


class AnswerType(StrEnum):
    """Supported question answer types. Rubric criteria drive scoring per type."""

    definition = "definition"
    short_answer = "short_answer"
    explain = "explain"
    describe = "describe"
    list = "list"
    enumerate = "enumerate"
    compare = "compare"
    differentiate = "differentiate"
    process = "process"
    steps = "steps"
    advantages_disadvantages = "advantages_disadvantages"
    justification = "justification"
    example_based = "example_based"
    essay = "essay"
    long_answer = "long_answer"
    numerical = "numerical"
    formula = "formula"
    code = "code"
    pseudocode = "pseudocode"
    table = "table"
    diagram_only = "diagram_only"
    text_with_diagram = "text_with_diagram"


class ExpectedConcept(BaseModel):
    """Primary semantic grading target. The student may express it in different wording."""

    concept_id: str = Field(description="Unique criterion/concept id (e.g. C1)")
    description: str = Field(description="Concept the answer must convey (semantic target)")
    maximum_marks: float = Field(ge=0, description="Marks awarded when fully supported")
    required: bool = Field(default=True, description="Whether this concept is required")


class DiagramRequiredRelationship(BaseModel):
    """Expected relationship between diagram components (vs Module 10 observations)."""

    from_component: str = Field(description="Expected source label")
    to_component: str = Field(description="Expected target label")
    relationship_type: str = Field(default="arrow")


class DiagramRequirements(BaseModel):
    """What Module 14 compares against Module 10's neutral visual observations."""

    required: bool = Field(default=False)
    minimum_components: int = Field(default=0, ge=0)
    required_labels: list[str] = Field(default_factory=list)
    required_relationships: list[DiagramRequiredRelationship] = Field(default_factory=list)
    description: str | None = None


class QuestionRubric(BaseModel):
    """Teacher-defined rubric / answer key for one question."""

    schema_version: str = Field(default=RUBRIC_SCHEMA_VERSION)
    version: str = Field(default=RUBRIC_SCHEMA_VERSION, description="Rubric version tag")
    question_id: str
    question_text: str = ""
    answer_type: AnswerType = AnswerType.explain
    maximum_marks: float = Field(gt=0)
    expected_answer: str | None = Field(default=None, description="Model answer; NOT enforced verbatim")
    expected_concepts: list[ExpectedConcept] = Field(default_factory=list)
    keywords: list[str] = Field(
        default_factory=list,
        description="Supporting-evidence signals only — never a grading mechanism by themselves",
    )
    mandatory_terms: list[str] = Field(
        default_factory=list,
        description="Required terminology; carries deterministic policy consequences",
    )
    minimum_words: int = Field(default=0, ge=0)
    grace_words: int | None = Field(default=None, ge=0, description="Overrides strictness-derived grace")
    diagram: DiagramRequirements = Field(default_factory=DiagramRequirements)
    strictness: int = Field(default=60, ge=0, le=100)
    overrides: dict[str, Any] = Field(default_factory=dict, description="Strictness policy overrides")
    require_exact_criteria_total: bool = Field(
        default=True,
        description="When True, expected-concept maxima must sum exactly to maximum_marks",
    )
    math_rubric: MathRubric | None = Field(
        default=None,
        description="Step-aware marking scheme for numerical/formula questions (#44); drives deterministic math grading",
    )

    @field_validator("question_id")
    @classmethod
    def _non_empty_question_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("question_id must be a non-empty string")
        return v.strip()

    @model_validator(mode="after")
    def _validate_structure(self) -> "QuestionRubric":
        ids = [c.concept_id for c in self.expected_concepts]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"expected_concepts contains duplicate concept_id values: {dupes}")
        for c in self.expected_concepts:
            if not c.description.strip():
                raise ValueError(f"concept '{c.concept_id}' has an empty description")
        total = sum(c.maximum_marks for c in self.expected_concepts)
        eps = 1e-9
        if self.expected_concepts and self.require_exact_criteria_total and abs(total - self.maximum_marks) > eps:
            raise ValueError(
                f"expected_concepts maxima sum to {total} but question maximum is "
                f"{self.maximum_marks}; totals must match when require_exact_criteria_total=True"
            )
        if self.expected_concepts and not self.require_exact_criteria_total and total > self.maximum_marks + eps:
            raise ValueError(
                f"expected_concepts maxima sum to {total} which exceeds question maximum {self.maximum_marks}"
            )
        if self.math_rubric is not None:
            math_total = sum(s.marks for s in self.math_rubric.steps)
            if math_total > self.maximum_marks + eps:
                raise ValueError(
                    f"math_rubric steps allocate {math_total} marks but question maximum is {self.maximum_marks}"
                )
        return self

    def validate_rubric(self) -> None:
        """Explicit validation entry point used before evaluation."""

        try:
            QuestionRubric.model_validate(self.model_dump())
        except Exception as e:
            raise RubricValidationError(
                f"Invalid rubric for question '{self.question_id}': {e}",
                details={"question_id": self.question_id},
            ) from e
