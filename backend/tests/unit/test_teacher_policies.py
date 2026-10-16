"""Milestone 9 unit tests: teacher-configured deterministic deductions.

Covers spec #20 (word-count once/per_step), #22/#38 (missing-diagram
deductions), #41 (keywords never auto-score), #54 (final arithmetic with
clamping), #39 (no double penalties).
"""

from __future__ import annotations

import pytest

from answer_eval.agents.diagram.schemas import DiagramResult
from answer_eval.agents.reconstruction.schemas import AnswerSegment, CanonicalStructuredAnswer
from answer_eval.core.provenance import Provenance
from answer_eval.grading.evaluation.schemas import (
    CriterionEvaluation,
    CriterionStatus,
    EvaluationResult,
    MatchType,
)
from answer_eval.grading.rubric import ExpectedConcept, QuestionRubric
from answer_eval.grading.rules.engine import evaluate_answer, match_literal_terms
from answer_eval.grading.rules.schemas import (
    DiagramPolicyRule,
    TeacherQuestionRules,
    TerminologyPolicyRule,
    WordCountPolicyRule,
)
from answer_eval.grading.service import compute_final_marks
from answer_eval.grading.strictness.engine import StrictnessEngine

MAX_MARKS = 16.0


def make_provenance() -> Provenance:
    return Provenance(
        submission_id="SUB-TP",
        page_number=1,
        region_id="REG-1",
        question_id="Q1",
        source_image_hash="hash",
        request_id="req-1",
        model_id="mock",
    )


def make_answer(text: str, diagrams: list[DiagramResult] | None = None) -> CanonicalStructuredAnswer:
    words_list = text.split() if text else []
    return CanonicalStructuredAnswer(
        submission_id="SUB-TP",
        question_id="Q1",
        source_pages=[1],
        raw_text=text,
        word_count=len(words_list),
        segments=[AnswerSegment(page_number=1, region_id="REG-1", reading_order=1, raw_text=text)],
        diagrams=diagrams or [],
        provenance=make_provenance(),
    )


def make_rubric(minimum_words: int = 0, **rubric_overrides) -> QuestionRubric:
    defaults = dict(
        question_id="Q1",
        maximum_marks=MAX_MARKS,
        expected_concepts=[
            ExpectedConcept(concept_id="C1", description="concept one", maximum_marks=4),
            ExpectedConcept(concept_id="C2", description="concept two", maximum_marks=4),
            ExpectedConcept(concept_id="C3", description="concept three", maximum_marks=4),
            ExpectedConcept(concept_id="C4", description="concept four", maximum_marks=4),
        ],
        minimum_words=minimum_words,
    )
    defaults.update(rubric_overrides)
    return QuestionRubric(**defaults)


def teacher_rules(**kw) -> TeacherQuestionRules:
    return TeacherQuestionRules(question_id="Q1", version=3, **kw)


def words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


def diagram(present: bool) -> DiagramResult:
    return DiagramResult(diagram_present=present, provenance=make_provenance())


def get_penalty(result, penalty_type: str):
    return next((p for p in result.deterministic_penalties if p.penalty_type == penalty_type), None)


# ---------------------------------------------------------------------------
# Spec #20 — word-count policy (exact example from the master spec)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actual_words", "expected_penalty"),
    [(100, 0.0), (90, 0.0), (81, 0.0), (80, 1.0), (70, 1.0)],
)
def test_word_count_once_mode_spec_example(actual_words: int, expected_penalty: float) -> None:
    rubric = make_rubric(minimum_words=100)
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(
        word_count=WordCountPolicyRule(minimum_words=100, trigger_shortfall_words=20, marks_deducted=1, mode="once")
    )
    result = evaluate_answer(make_answer(words(actual_words)), rubric, policy, rules)
    assert result.total_deterministic_penalty == expected_penalty


def test_word_count_per_step_mode() -> None:
    rubric = make_rubric(minimum_words=100)
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(
        word_count=WordCountPolicyRule(minimum_words=100, trigger_shortfall_words=20, marks_deducted=1, mode="per_step")
    )
    assert evaluate_answer(make_answer(words(80)), rubric, policy, rules).total_deterministic_penalty == 1.0
    assert evaluate_answer(make_answer(words(59)), rubric, policy, rules).total_deterministic_penalty == 2.0
    assert evaluate_answer(make_answer(words(39)), rubric, policy, rules).total_deterministic_penalty == 3.0


def test_teacher_word_count_replaces_strictness_amount() -> None:
    """Strictness must not invent deductions (#18): the teacher amount is exact."""
    rubric = make_rubric(minimum_words=100)
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(
        word_count=WordCountPolicyRule(minimum_words=100, trigger_shortfall_words=20, marks_deducted=1, mode="once")
    )
    result = evaluate_answer(make_answer(words(70)), rubric, policy, rules)
    penalty = get_penalty(result, "word_count_teacher")
    assert penalty is not None and penalty.marks == 1.0
    assert get_penalty(result, "word_count_deficit") is None  # legacy path absent


def test_empty_answer_gets_no_word_count_penalty() -> None:
    rubric = make_rubric(minimum_words=100)
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(
        word_count=WordCountPolicyRule(minimum_words=100, trigger_shortfall_words=20, marks_deducted=1, mode="once")
    )
    result = evaluate_answer(make_answer(""), rubric, policy, rules)
    assert result.answer_empty
    assert result.total_deterministic_penalty == 0.0


# ---------------------------------------------------------------------------
# Specs #22/#38 — missing-diagram deductions
# ---------------------------------------------------------------------------


def diagram_rule() -> TeacherQuestionRules:
    return teacher_rules(
        diagram=DiagramPolicyRule(required=True, minimum_diagrams=2, missing_diagram_deductions=[2.0, 1.0])
    )


def test_both_diagrams_present_no_penalty() -> None:
    rubric = make_rubric()
    policy = StrictnessEngine.build(rubric.strictness, {})
    answer = make_answer(words(30), diagrams=[diagram(True), diagram(True)])
    result = evaluate_answer(answer, rubric, policy, diagram_rule())
    assert result.total_deterministic_penalty == 0.0


def test_one_of_two_missing_takes_second_ordinal_deduction() -> None:
    rubric = make_rubric()
    policy = StrictnessEngine.build(rubric.strictness, {})
    answer = make_answer(words(30), diagrams=[diagram(True)])
    result = evaluate_answer(answer, rubric, policy, diagram_rule())
    assert result.total_deterministic_penalty == 1.0  # D2 missing -> its own deduction
    assert len([p for p in result.deterministic_penalties if p.penalty_type == "missing_diagram"]) == 1


def test_all_diagrams_missing_sums_fixed_deductions() -> None:
    rubric = make_rubric()
    policy = StrictnessEngine.build(rubric.strictness, {})
    answer = make_answer(words(30))
    result = evaluate_answer(answer, rubric, policy, diagram_rule())
    assert result.total_deterministic_penalty == 3.0  # D1(-2) + D2(-1), applied once (#38/#39)


def test_diagram_not_required_no_penalty() -> None:
    rubric = make_rubric()
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(diagram=DiagramPolicyRule(required=False, minimum_diagrams=0, missing_diagram_deductions=[5.0]))
    result = evaluate_answer(make_answer(words(10)), rubric, policy, rules)
    assert result.total_deterministic_penalty == 0.0


# ---------------------------------------------------------------------------
# Spec #54 — terminology + final arithmetic with clamping
# ---------------------------------------------------------------------------


def test_teacher_terminology_penalty_amount() -> None:
    rubric = make_rubric(mandatory_terms=["retransmission"])
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(terminology=TerminologyPolicyRule(marks_deducted=0.5))
    result = evaluate_answer(make_answer(words(10)), rubric, policy, rules)
    penalty = get_penalty(result, "mandatory_terms_missing")
    assert penalty is not None and penalty.marks == 0.5
    assert "teacher-configured" in penalty.reason


def _evaluation_with_total(total: float) -> EvaluationResult:
    criteria = [
        CriterionEvaluation(
            criterion_id=f"C{i}",
            criterion=f"concept {i}",
            status=CriterionStatus.fully_supported if i <= 2 else CriterionStatus.unsupported,
            match_type=MatchType.semantic_equivalent,
            maximum_marks=4,
            proposed_marks=total if i == 1 else 0.0,
            reason="evidence quoted",
        )
        for i in range(1, 3)
    ]
    return EvaluationResult(question_id="Q1", criteria=criteria, feedback="partial")


def test_final_arithmetic_clamps_and_itemizes() -> None:
    rubric = make_rubric(minimum_words=100)
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(
        word_count=WordCountPolicyRule(minimum_words=100, trigger_shortfall_words=20, marks_deducted=1),
        diagram=DiagramPolicyRule(required=True, minimum_diagrams=2, missing_diagram_deductions=[2.0, 1.0]),
    )
    answer = make_answer(words(50))  # below trigger AND both diagrams missing
    result = evaluate_answer(answer, rubric, policy, rules)
    evaluation = _evaluation_with_total(8.0)
    marks = compute_final_marks(evaluation, result, rubric)
    assert marks.criteria_total == 8.0
    assert marks.deterministic_penalty == 4.0  # word -1, diagrams -3
    assert marks.final_proposed_marks == 4.0
    # Every deduction itemized exactly once (#39)
    assert {(p.penalty_type, p.marks) for p in marks.penalty_components} == {
        ("word_count_teacher", 1.0),
        ("missing_diagram", 3.0),
    }


def test_final_never_below_zero() -> None:
    rubric = make_rubric()
    policy = StrictnessEngine.build(rubric.strictness, {})
    rules = teacher_rules(
        diagram=DiagramPolicyRule(required=True, minimum_diagrams=2, missing_diagram_deductions=[3.0, 3.0])
    )
    answer = make_answer(words(5))
    result = evaluate_answer(answer, rubric, policy, rules)
    marks = compute_final_marks(_evaluation_with_total(1.0), result, rubric)
    assert marks.final_proposed_marks == 0.0  # clamped at zero, never negative


def test_keywords_are_facts_only_never_auto_credit() -> None:
    """Spec #41: keywords are recorded as facts; only the evaluator awards marks."""
    matched, _missing = match_literal_terms("retransmission occurred", ["retransmission"])
    assert matched == ["retransmission"]


