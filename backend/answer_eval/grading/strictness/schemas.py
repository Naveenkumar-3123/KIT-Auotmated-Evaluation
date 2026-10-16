"""Strictness policy schemas (Module 13)."""

from typing import Any

from pydantic import BaseModel, Field


class SemanticEquivalencePolicy(BaseModel):
    accept_synonyms: bool = True
    accept_paraphrases: bool = True
    accept_implicit_concepts: bool = True
    precision_required: str = "normal"  # broad | normal | high | very_high


class PartialCreditPolicy(BaseModel):
    enabled: bool = True
    generosity: str = "normal"  # very_generous | generous | normal | conservative | minimal


class WordCountPolicy(BaseModel):
    grace_percentage: float = 10.0  # % of minimum_words granted as grace
    maximum_penalty_percentage: float = 15.0  # cap on deterministic word-count penalty (% of max)


class TerminologyPolicy(BaseModel):
    precision: str = "standard"  # flexible | standard | important | highly_important
    standard_abbreviations_allowed: bool = True
    enforce_mandatory_terms: bool = False  # deterministic penalty when missing terms
    mandatory_missing_penalty_percentage: float = 10.0  # % of question maximum, capped


class ContradictionPolicy(BaseModel):
    severity: str = "medium"  # low | medium | high


class DiagramPolicy(BaseModel):
    layout_tolerance: str = "moderate"
    label_tolerance: str = "moderate"


class StrictnessPolicy(BaseModel):
    """Versioned, explicit translation of a teacher strictness score.

    Strictness may change tolerance / generosity / precision expectations.
    It must NEVER change facts, truth, maximum marks, rubric weights, whether
    evidence exists, or whether arithmetic is valid.
    """

    policy_version: str = "strictness-v1"
    score: int = Field(ge=0, le=100)
    profile: str  # very_lenient | lenient | standard | strict | very_strict

    semantic_equivalence: SemanticEquivalencePolicy = Field(default_factory=SemanticEquivalencePolicy)
    partial_credit: PartialCreditPolicy = Field(default_factory=PartialCreditPolicy)
    word_count: WordCountPolicy = Field(default_factory=WordCountPolicy)
    terminology: TerminologyPolicy = Field(default_factory=TerminologyPolicy)
    contradictions: ContradictionPolicy = Field(default_factory=ContradictionPolicy)
    diagram: DiagramPolicy = Field(default_factory=DiagramPolicy)

    overrides_applied: dict[str, Any] = Field(
        default_factory=dict,
        description="Teacher overrides applied on top of the band defaults (audit trail)",
    )

    def effective_minimum_words(self, minimum_words: int) -> tuple[int, int]:
        """Return (grace_words, effective_minimum) for a rubric minimum word count."""
        if minimum_words <= 0:
            return 0, 0
        import math

        grace_words = int(math.floor(minimum_words * self.word_count.grace_percentage / 100.0))
        return grace_words, max(0, minimum_words - grace_words)

    def max_word_count_penalty(self, question_maximum: float) -> float:
        return round(question_maximum * self.word_count.maximum_penalty_percentage / 100.0, 2)

    def max_mandatory_term_penalty(self, question_maximum: float) -> float:
        if not self.terminology.enforce_mandatory_terms:
            return 0.0
        return round(question_maximum * self.terminology.mandatory_missing_penalty_percentage / 100.0, 2)
