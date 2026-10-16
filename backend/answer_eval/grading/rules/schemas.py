"""Deterministic rule evaluation output schemas (Module 12)."""

from pydantic import BaseModel, Field


class WordCountFacts(BaseModel):
    actual: int
    minimum: int
    grace_words: int
    effective_minimum: int
    within_requirement: bool
    deficit: int = Field(ge=0)


class KeywordFacts(BaseModel):
    matched: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)


class MandatoryTermFacts(BaseModel):
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class DiagramFacts(BaseModel):
    required: bool
    present: bool


class RubricValidationFacts(BaseModel):
    criteria_total: float
    question_maximum: float
    valid: bool


class DeterministicPenalty(BaseModel):
    """A bounded, Python-computed penalty. Never produced by an LLM."""

    penalty_type: str  # word_count_deficit | word_count_teacher | missing_diagram | mandatory_terms_missing
    marks: float = Field(ge=0)
    reason: str


class WordCountPolicyRule(BaseModel):
    """Teacher-configured word-count rule (spec #20).

    Deterministic Python arithmetic; STRICTNESS NEVER INVENTS these deductions.
    ``trigger_shortfall_words`` is the grace band below the minimum: the answer
    passes while ``actual >= minimum_words - trigger_shortfall_words + 1``
    (spec example: min 100, trigger 20 -> 81 passes, 80 is deducted).

    Modes:
      once    — a single ``marks_deducted`` once the shortfall reaches the trigger.
      per_step— one deduction per full ``trigger_shortfall_words`` block of shortfall.
    """

    minimum_words: int = Field(ge=0)
    trigger_shortfall_words: int = Field(default=0, ge=0)
    marks_deducted: float = Field(default=0, ge=0)
    mode: str = Field(default="once", pattern="^(once|per_step)$")

    @property
    def effective_minimum(self) -> int:
        """Lowest word count that avoids the deduction."""
        if self.minimum_words <= 0:
            return 0
        if self.trigger_shortfall_words <= 0:
            return self.minimum_words
        return max(0, self.minimum_words - self.trigger_shortfall_words + 1)

    def penalty_for(self, actual_words: int) -> tuple[float, int]:
        """Return (marks_deducted, shortfall_below_minimum) for this rule."""
        shortfall = max(0, self.minimum_words - actual_words)
        if self.marks_deducted <= 0 or self.minimum_words <= 0 or shortfall == 0:
            return 0.0, shortfall
        trigger = self.trigger_shortfall_words
        if trigger > 0 and shortfall < trigger:
            return 0.0, shortfall
        if self.mode == "once":
            return round(self.marks_deducted, 2), shortfall
        step = max(1, trigger)
        blocks = max(1, shortfall // step)
        return round(self.marks_deducted * blocks, 2), shortfall


class DiagramPolicyRule(BaseModel):
    """Teacher-configured missing-diagram rule (specs #22/#38)."""

    required: bool = False
    minimum_diagrams: int = Field(default=0, ge=0)
    missing_diagram_deductions: list[float] = Field(default_factory=list)

    def missing_penalty(self, present_count: int) -> float:
        """Sum deductions for the MISSING ordinals (D1 keeps its own deduction).

        Example: required 2, deductions [2, 1]:
          present 0 -> 2 + 1 = 3 ; present 1 -> 1 (D2 missing) ; present 2 -> 0.
        """
        if not self.required:
            return 0.0
        required_count = max(self.minimum_diagrams, 1 if self.required else 0)
        missing = max(0, required_count - present_count)
        if missing <= 0:
            return 0.0
        deductions = [
            d for d in self.missing_diagram_deductions[-missing:]
            if d > 0
        ]
        if not deductions:
            deductions = [0.0] * missing
        return round(sum(deductions), 2)


class TerminologyPolicyRule(BaseModel):
    """Teacher-configured mandatory-terminology consequence (spec #54).

    ``marks_deducted=None`` falls back to the strictness-derived cap.
    """

    enforce_mandatory_terms: bool = True
    marks_deducted: float | None = Field(default=None, ge=0)


class TeacherQuestionRules(BaseModel):
    """Resolved per-question teacher policies (from question_policies, M5).

    When supplied to the rule engine these OVERRIDE all strictness-derived
    penalty amounts — strictness then controls semantic precision only.
    """

    schema_version: str = "teacher-rules-v1"
    question_id: str
    version: int = 1
    word_count: WordCountPolicyRule | None = None
    diagram: DiagramPolicyRule | None = None
    terminology: TerminologyPolicyRule | None = None


class RuleEvaluationResult(BaseModel):
    """Objective, deterministic facts about one answer. NO semantic interpretation."""

    schema_version: str = "rule-evaluation-v1"
    question_id: str
    answer_empty: bool = False
    answer_too_short: bool = False

    word_count: WordCountFacts
    keywords: KeywordFacts = Field(default_factory=KeywordFacts)
    mandatory_terms: MandatoryTermFacts = Field(default_factory=MandatoryTermFacts)
    diagram: DiagramFacts
    rubric_validation: RubricValidationFacts

    deterministic_penalties: list[DeterministicPenalty] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    @property
    def total_deterministic_penalty(self) -> float:
        return round(sum(p.marks for p in self.deterministic_penalties), 2)
