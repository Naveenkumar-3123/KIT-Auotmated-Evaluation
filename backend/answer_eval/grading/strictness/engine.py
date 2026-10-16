"""Strictness policy engine (Module 13).

Converts a teacher strictness integer (0-100) plus optional teacher overrides
into a VERSIONED, EXPLICIT StrictnessPolicy. The policy — not a raw number —
is what evaluation prompts and deterministic rules consume.
"""

from typing import Any

from answer_eval.core.errors import StrictnessPolicyError
from answer_eval.grading.strictness.policies import STRICTNESS_POLICY_VERSION, band_for_score
from answer_eval.grading.strictness.schemas import (
    ContradictionPolicy,
    DiagramPolicy,
    PartialCreditPolicy,
    SemanticEquivalencePolicy,
    StrictnessPolicy,
    TerminologyPolicy,
    WordCountPolicy,
)

# Flat override keys teachers may set (validated; unknown keys are rejected so
# typos never silently change grading behaviour).
_OVERRIDE_KEYS = {
    "word_count_grace_percentage": ("word_count", "grace_percentage", float),
    "word_count_maximum_penalty_percentage": ("word_count", "maximum_penalty_percentage", float),
    "partial_credit_enabled": ("partial_credit", "enabled", bool),
    "partial_credit_generosity": ("partial_credit", "generosity", str),
    "semantic_precision_required": ("semantic_equivalence", "precision_required", str),
    "accept_implicit_concepts": ("semantic_equivalence", "accept_implicit_concepts", bool),
    "mandatory_terms_enforced": ("terminology", "enforce_mandatory_terms", bool),
    "mandatory_missing_penalty_percentage": ("terminology", "mandatory_missing_penalty_percentage", float),
    "terminology_precision": ("terminology", "precision", str),
    "contradiction_severity": ("contradictions", "severity", str),
    "diagram_layout_tolerance": ("diagram", "layout_tolerance", str),
    "diagram_label_tolerance": ("diagram", "label_tolerance", str),
}


class StrictnessEngine:
    """Builds deterministic, versioned StrictnessPolicy objects."""

    policy_version = STRICTNESS_POLICY_VERSION

    @classmethod
    def build(cls, score: int, overrides: dict[str, Any] | None = None) -> StrictnessPolicy:
        """Build a policy for a strictness score.

        Same (score, policy_version, overrides) ALWAYS yields an identical
        policy — grading must be reproducible.
        """
        if not isinstance(score, int) or isinstance(score, bool):
            raise StrictnessPolicyError(
                f"Strictness score must be an integer 0-100, got {score!r}",
                details={"score": score},
            )
        if score < 0 or score > 100:
            raise StrictnessPolicyError(
                f"Strictness score must be within 0-100, got {score}",
                details={"score": score},
            )

        band = band_for_score(score)
        policy = StrictnessPolicy(
            policy_version=STRICTNESS_POLICY_VERSION,
            score=score,
            profile=band["name"],
            semantic_equivalence=SemanticEquivalencePolicy(**band["semantic_equivalence"]),
            partial_credit=PartialCreditPolicy(**band["partial_credit"]),
            word_count=WordCountPolicy(**band["word_count"]),
            terminology=TerminologyPolicy(**band["terminology"]),
            contradictions=ContradictionPolicy(**band["contradictions"]),
            diagram=DiagramPolicy(**band["diagram"]),
        )

        applied: dict[str, Any] = {}
        for key, value in (overrides or {}).items():
            if key not in _OVERRIDE_KEYS:
                raise StrictnessPolicyError(
                    f"Unknown strictness override '{key}'. Valid keys: {sorted(_OVERRIDE_KEYS)}",
                    details={"override": key},
                )
            section, field, cast = _OVERRIDE_KEYS[key]
            try:
                if cast is bool and isinstance(value, str):
                    cast_value = value.strip().lower() in ("1", "true", "yes", "on")
                else:
                    cast_value = cast(value)
                setattr(getattr(policy, section), field, cast_value)
            except Exception as e:
                raise StrictnessPolicyError(
                    f"Invalid value for strictness override '{key}': {value!r} ({e})",
                    details={"override": key, "value": value},
                ) from e
            applied[key] = cast_value

        policy.overrides_applied = applied
        return policy

    @staticmethod
    def effective_minimum_words(policy: StrictnessPolicy, minimum_words: int) -> tuple[int, int]:
        """(grace_words, effective_minimum) honouring an optional explicit rubric grace."""
        return policy.effective_minimum_words(minimum_words)
