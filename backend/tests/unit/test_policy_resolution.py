"""Unit tests for the deterministic policy resolver."""

from __future__ import annotations

import pytest

from answer_eval.grading.policy_resolution import (
    DiagramRule,
    KeyQuestionFacts,
    PolicyValidationError,
    StrictnessRule,
    WordCountRule,
    resolve_policies,
    snapshot_for_storage,
    validate_rules,
)


def _rules(**kwargs):
    return resolve_policies(question_numbers=list(range(1, kwargs.pop("count") + 1)), **kwargs)


def test_defaults_when_no_rules() -> None:
    resolved = _rules(count=3, strictness_rules=[], word_count_rules=[], diagram_rules=[])
    assert set(resolved) == {1, 2, 3}
    assert all(p.strictness_level == "moderate" for p in resolved.values())
    assert all(p.minimum_words == 0 for p in resolved.values())


def test_range_then_question_override() -> None:
    resolved = _rules(
        count=12,
        strictness_rules=[
            StrictnessRule(level="lenient", question_from=1, question_to=10),
            StrictnessRule(level="strict", question_from=11, question_to=12),
            StrictnessRule(level="moderate", question_number=7, rule_id="q7"),  # overrides range
        ],
        word_count_rules=[],
        diagram_rules=[],
    )
    assert resolved[7].strictness_level == "moderate"
    assert resolved[1].strictness_level == "lenient"
    assert resolved[12].strictness_level == "strict"
    assert any("q7" in rid for rid in resolved[7].source_rule_ids)


def test_later_range_wins_on_overlap() -> None:
    resolved = _rules(
        count=6,
        strictness_rules=[
            StrictnessRule(level="lenient", question_from=1, question_to=5),
            StrictnessRule(level="strict", question_from=4, question_to=6),
        ],
        word_count_rules=[],
        diagram_rules=[],
    )
    assert resolved[1].strictness_level == "lenient"
    assert resolved[4].strictness_level == "strict"
    assert resolved[6].strictness_level == "strict"


def test_word_count_teacher_values_win_over_key() -> None:
    facts = {2: KeyQuestionFacts(maximum_marks=8)}
    resolved = resolve_policies(
        question_numbers=[1, 2],
        strictness_rules=[],
        word_count_rules=[
            WordCountRule(minimum_words=150, mode="once", trigger_shortfall_words=20, marks_deducted=1.5, question_from=1, question_to=2)
        ],
        diagram_rules=[],
        key_facts=facts,
    )
    policy = resolved[2]
    assert (policy.minimum_words, policy.trigger_shortfall_words, policy.marks_deducted) == (150, 20, 1.5)
    assert policy.maximum_marks == 8


def test_diagram_rule_replaces_key_default_and_pads_deductions() -> None:
    facts = {4: KeyQuestionFacts(key_diagram_required=True, key_diagram_count=2)}
    resolved = resolve_policies(
        question_numbers=[4],
        strictness_rules=[],
        word_count_rules=[],
        diagram_rules=[DiagramRule(required=True, minimum_diagrams=2, missing_diagram_deductions=(2.0,), question_number=4)],
        key_facts=facts,
    )
    policy = resolved[4]
    assert policy.diagram_required and policy.min_diagrams == 2
    assert policy.missing_diagram_deductions == [2.0, 1.0]  # padded with default 1


def test_validation_out_of_range_and_bad_deduction_counts() -> None:
    with pytest.raises(PolicyValidationError, match="outside this assessment"):
        validate_rules(question_count=5, strictness_rules=[StrictnessRule(level="strict", question_number=6)], word_count_rules=[], diagram_rules=[])
    with pytest.raises(PolicyValidationError, match="deduction value"):
        validate_rules(
            question_count=5,
            strictness_rules=[],
            word_count_rules=[],
            diagram_rules=[DiagramRule(required=True, minimum_diagrams=2, missing_diagram_deductions=(1.0,), question_number=1)],
        )
    with pytest.raises(PolicyValidationError, match="shortfall trigger"):
        validate_rules(
            question_count=5,
            strictness_rules=[],
            word_count_rules=[WordCountRule(minimum_words=20, trigger_shortfall_words=25, marks_deducted=1, question_number=1)],
            diagram_rules=[],
        )


def test_snapshot_shape() -> None:
    resolved = _rules(
        count=1,
        strictness_rules=[StrictnessRule(level="strict", question_number=1)],
        word_count_rules=[WordCountRule(minimum_words=100, trigger_shortfall_words=15, marks_deducted=1, question_number=1)],
        diagram_rules=[],
    )
    rows = snapshot_for_storage(resolved)
    assert rows[0]["question_number"] == 1
    assert rows[0]["missing_diagram_deductions"] == []
    assert rows[0]["marks_deducted"] == 1
