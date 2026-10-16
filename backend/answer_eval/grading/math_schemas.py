"""Deterministic math step-evaluation contracts (Milestone 11, specs #44-#48).

The VLM interprets handwritten working and maps it onto rubric steps
(`StudentMathWork`). ALL arithmetic, equivalence checking, tolerance handling
and mark summation happens HERE in Python (SymPy) — never by the model.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class MathStep(BaseModel):
    """One teacher/rubric step with allocated marks (spec #44)."""

    step_id: str = Field(description="e.g. M1")
    description: str
    marks: float = Field(ge=0)
    expression: str | None = Field(
        default=None,
        description="Expected symbolic expression/value for this step (enables deterministic checking)",
    )
    is_final_answer: bool = False


class MathRubric(BaseModel):
    """Step-aware marking scheme for numerical/formula questions."""

    steps: list[MathStep] = Field(min_length=1)
    final_answer: str | None = Field(default=None, description="Expected final value/expression")
    numeric_tolerance: float = Field(default=1e-6, gt=0)

    @model_validator(mode="after")
    def _validate(self) -> "MathRubric":
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("math rubric contains duplicate step_ids")
        return self


class StudentStepClaim(BaseModel):
    """The model's interpretation of ONE piece of student working."""

    rubric_step_id: str | None = Field(default=None, description="Mapped rubric step (AI interpretation)")
    student_expression: str | None = Field(default=None, description="Transcribed value/expression")
    is_final_answer: bool = False
    ocr_uncertain: bool = Field(default=False, description="Operator/sign/digit could not be read reliably (#48)")
    internally_consistent: bool = Field(
        default=True,
        description="Method applied consistently with the student's own earlier (possibly wrong) values",
    )
    alternative_method: bool = Field(
        default=False, description="Valid but different route than the key (#45) — still verified where possible"
    )
    note: str = ""


class StudentMathWork(BaseModel):
    """VLM interpretation of the student's handwritten math working."""

    schema_version: str = "student-math-work-v1"
    question_id: str
    claims: list[StudentStepClaim] = Field(default_factory=list)
    overall_uncertain: bool = False


class StepStatus(StrEnum):
    correct = "correct"
    follow_through = "follow_through"  # consistent with an earlier student error (#47)
    incorrect = "incorrect"
    not_attempted = "not_attempted"
    uncertain = "uncertain"  # routes to teacher verification (#48)


class MathStepOutcome(BaseModel):
    step_id: str
    description: str
    max_marks: float
    awarded: float = Field(ge=0)
    status: StepStatus
    detail: str = ""


class MathEvaluationResult(BaseModel):
    """Python-computed step outcomes and totals. The model never sums."""

    schema_version: str = "math-evaluation-v1"
    question_id: str
    outcomes: list[MathStepOutcome] = Field(default_factory=list)
    total_awarded: float = 0.0
    total_possible: float = 0.0
    final_matches_key: bool | None = None
    flags: list[str] = Field(default_factory=list)
