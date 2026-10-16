"""Pure policy resolution: teacher rules (ranges / per-question) → one
immutable policy per question.

Precedence (highest wins):
    1. per-question rule (latest in list)
    2. range rule covering the question (latest in list)
    3. answer-key derived defaults
    4. system defaults

This is deterministic Python — evaluation never consults raw ranges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


class PolicyValidationError(ValueError):
    """Raised when teacher-supplied rules are inconsistent."""


@dataclass(frozen=True)
class StrictnessRule:
    level: str
    question_number: int | None = None  # None => range
    question_from: int = 0
    question_to: int = 0
    rule_id: str = ""


@dataclass(frozen=True)
class WordCountRule:
    minimum_words: int = 0
    mode: str = "once"  # once | per_step
    trigger_shortfall_words: int = 0
    marks_deducted: float = 0
    question_number: int | None = None
    question_from: int = 0
    question_to: int = 0
    rule_id: str = ""


@dataclass(frozen=True)
class DiagramRule:
    required: bool = False
    minimum_diagrams: int = 1
    missing_diagram_deductions: tuple[float, ...] = ()
    question_number: int | None = None
    question_from: int = 0
    question_to: int = 0
    rule_id: str = ""


@dataclass(frozen=True)
class KeyQuestionFacts:
    maximum_marks: float = 0
    key_diagram_required: bool = False
    key_diagram_count: int = 0


@dataclass
class ResolvedQuestionPolicy:
    question_number: int
    strictness_level: str = "moderate"
    minimum_words: int = 0
    word_count_mode: str = "once"
    trigger_shortfall_words: int = 0
    marks_deducted: float = 0
    diagram_required: bool = False
    min_diagrams: int = 0
    missing_diagram_deductions: list[float] = field(default_factory=list)
    maximum_marks: float = 0
    source_rule_ids: list[str] = field(default_factory=list)


def _covers(rule_question: int | None, rule_from: int, rule_to: int, number: int) -> bool:
    if rule_question is not None:
        return rule_question == number
    return rule_from <= number <= rule_to


def resolve_policies(
    *,
    question_numbers: Sequence[int],
    strictness_rules: Sequence[StrictnessRule],
    word_count_rules: Sequence[WordCountRule],
    diagram_rules: Sequence[DiagramRule],
    key_facts: dict[int, KeyQuestionFacts] | None = None,
) -> dict[int, ResolvedQuestionPolicy]:
    facts = key_facts or {}
    resolved: dict[int, ResolvedQuestionPolicy] = {}

    for number in sorted(question_numbers):
        policy = ResolvedQuestionPolicy(
            question_number=number,
            maximum_marks=facts.get(number, KeyQuestionFacts()).maximum_marks,
            diagram_required=facts.get(number, KeyQuestionFacts()).key_diagram_required,
            min_diagrams=facts.get(number, KeyQuestionFacts()).key_diagram_count,
        )
        if policy.diagram_required and not policy.missing_diagram_deductions:
            policy.missing_diagram_deductions = [1.0] * max(policy.min_diagrams, 1)

        for rule in strictness_rules:
            if _covers(rule.question_number, rule.question_from, rule.question_to, number):
                policy.strictness_level = rule.level
                if rule.rule_id:
                    policy.source_rule_ids.append(rule.rule_id)

        for rule in word_count_rules:
            if _covers(rule.question_number, rule.question_from, rule.question_to, number):
                policy.minimum_words = rule.minimum_words
                policy.word_count_mode = rule.mode
                policy.trigger_shortfall_words = rule.trigger_shortfall_words
                policy.marks_deducted = float(rule.marks_deducted)
                if rule.rule_id:
                    policy.source_rule_ids.append(rule.rule_id)

        for rule in diagram_rules:
            if _covers(rule.question_number, rule.question_from, rule.question_to, number):
                policy.diagram_required = rule.required
                policy.min_diagrams = rule.minimum_diagrams if rule.required else 0
                deductions = [float(v) for v in rule.missing_diagram_deductions]
                if rule.required and len(deductions) < max(rule.minimum_diagrams, 1):
                    deductions = deductions + [1.0] * (max(rule.minimum_diagrams, 1) - len(deductions))
                policy.missing_diagram_deductions = deductions[: max(rule.minimum_diagrams, 1)] if rule.required else []
                if rule.rule_id:
                    policy.source_rule_ids.append(rule.rule_id)

        resolved[number] = policy
    return resolved


# -- validation ---------------------------------------------------------------


def validate_rules(
    *,
    question_count: int,
    strictness_rules: Sequence[StrictnessRule],
    word_count_rules: Sequence[WordCountRule],
    diagram_rules: Sequence[DiagramRule],
) -> None:
    def check_scope(kind: str, index: int, question_number: int | None, q_from: int, q_to: int) -> None:
        label = f"{kind} rule #{index + 1}"
        if question_number is not None and not 1 <= question_number <= question_count:
            raise PolicyValidationError(f"{label}: Q{question_number} is outside this assessment (Q1–Q{question_count})")
        if question_number is None:
            if q_from < 1 or q_to > question_count:
                raise PolicyValidationError(f"{label}: range Q{q_from}–Q{q_to} is outside this assessment (Q1–Q{question_count})")
            if q_from > q_to:
                raise PolicyValidationError(f"{label}: invalid range Q{q_from}–Q{q_to}")

    for index, rule in enumerate(strictness_rules):
        check_scope("strictness", index, rule.question_number, rule.question_from, rule.question_to)
        if rule.level not in ("lenient", "moderate", "strict"):
            raise PolicyValidationError(f"strictness rule #{index + 1}: unknown level '{rule.level}'")

    for index, rule in enumerate(word_count_rules):
        check_scope("word-count", index, rule.question_number, rule.question_from, rule.question_to)
        if rule.mode not in ("once", "per_step"):
            raise PolicyValidationError(f"word-count rule #{index + 1}: unknown mode '{rule.mode}'")
        if rule.minimum_words < 0 or rule.trigger_shortfall_words < 0 or rule.marks_deducted < 0:
            raise PolicyValidationError(f"word-count rule #{index + 1}: values cannot be negative")
        if rule.minimum_words > 0 and rule.trigger_shortfall_words >= rule.minimum_words:
            raise PolicyValidationError(
                f"word-count rule #{index + 1}: shortfall trigger must be smaller than the {rule.minimum_words}-word minimum"
            )

    for index, rule in enumerate(diagram_rules):
        check_scope("diagram", index, rule.question_number, rule.question_from, rule.question_to)
        if rule.required:
            if rule.minimum_diagrams < 1:
                raise PolicyValidationError(f"diagram rule #{index + 1}: minimum must be at least 1 when diagrams are required")
            if len(rule.missing_diagram_deductions) != rule.minimum_diagrams:
                raise PolicyValidationError(
                    f"diagram rule #{index + 1}: needs exactly {rule.minimum_diagrams} missing-diagram deduction value(s), got {len(rule.missing_diagram_deductions)}"
                )
            if any(value < 0 for value in rule.missing_diagram_deductions):
                raise PolicyValidationError(f"diagram rule #{index + 1}: deductions cannot be negative")


def snapshot_for_storage(resolved: dict[int, ResolvedQuestionPolicy]) -> list[dict[str, Any]]:
    """Row dicts ready for the question_policies table."""
    rows = []
    for number, policy in sorted(resolved.items()):
        rows.append(
            {
                "question_number": number,
                "strictness_level": policy.strictness_level,
                "minimum_words": policy.minimum_words,
                "word_count_mode": policy.word_count_mode,
                "trigger_shortfall_words": policy.trigger_shortfall_words,
                "marks_deducted": policy.marks_deducted,
                "diagram_required": policy.diagram_required,
                "min_diagrams": policy.min_diagrams,
                "missing_diagram_deductions": policy.missing_diagram_deductions,
                "maximum_marks": policy.maximum_marks,
                "source_rule_ids": policy.source_rule_ids,
            }
        )
    return rows
