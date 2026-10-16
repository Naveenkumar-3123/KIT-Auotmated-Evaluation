"""Unit tests for Module 12 (deterministic rule engine) and Module 13 (strictness policy)."""

import pytest

from answer_eval.agents.diagram.schemas import DiagramResult
from answer_eval.agents.reconstruction.schemas import AnswerSegment, CanonicalStructuredAnswer
from answer_eval.core.errors import RubricValidationError, StrictnessPolicyError
from answer_eval.core.provenance import Provenance
from answer_eval.grading.rubric import DiagramRequirements, ExpectedConcept, QuestionRubric
from answer_eval.grading.rules.engine import evaluate_answer, match_literal_terms, normalize_for_matching
from answer_eval.grading.strictness.engine import StrictnessEngine


def make_provenance() -> Provenance:
    return Provenance(
        submission_id="SUB-001",
        page_number=1,
        region_id="REG-1",
        question_id="Q4",
        source_image_hash="hash",
        request_id="req-1",
        model_id="mock",
    )


def make_answer(text: str = "", diagrams: list | None = None, flags: list | None = None) -> CanonicalStructuredAnswer:
    return CanonicalStructuredAnswer(
        submission_id="SUB-001",
        question_id="Q4",
        source_pages=[1],
        raw_text=text,
        word_count=len(text.split()),
        segments=[AnswerSegment(page_number=1, region_id="REG-1", reading_order=1, raw_text=text)],
        diagrams=diagrams or [],
        flags=flags or [],
        provenance=make_provenance(),
    )


def present_diagram() -> DiagramResult:
    from answer_eval.agents.diagram.schemas import DiagramVisualQuality

    return DiagramResult(
        diagram_present=True, labels=[], visual_quality=DiagramVisualQuality(), provenance=make_provenance()
    )


def make_rubric(**overrides) -> QuestionRubric:
    base = dict(
        question_id="Q4",
        maximum_marks=10,
        expected_concepts=[
            ExpectedConcept(concept_id="C1", description="Connection-oriented communication", maximum_marks=5),
            ExpectedConcept(concept_id="C2", description="Acknowledgement mechanism", maximum_marks=5),
        ],
        keywords=["acknowledgement", "retransmission"],
        mandatory_terms=["TCP"],
        minimum_words=100,
        strictness=60,
    )
    base.update(overrides)
    return QuestionRubric(**base)


def policy_for(score: int):
    return StrictnessEngine.build(score)


# ---------------------------------------------------------------------------
# Module 13 — strictness boundaries & determinism
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("score", "profile"),
    [
        (0, "very_lenient"),
        (20, "very_lenient"),
        (21, "lenient"),
        (40, "lenient"),
        (41, "standard"),
        (60, "standard"),
        (61, "strict"),
        (80, "strict"),
        (81, "very_strict"),
        (100, "very_strict"),
    ],
)
def test_band_boundaries(score: int, profile: str) -> None:
    assert StrictnessEngine.build(score).profile == profile


@pytest.mark.parametrize("score", [-1, 101])
def test_invalid_strictness_scores(score: int) -> None:
    with pytest.raises(StrictnessPolicyError):
        StrictnessEngine.build(score)


def test_policy_deterministic_and_versioned() -> None:
    a, b = StrictnessEngine.build(60), StrictnessEngine.build(60)
    assert a.model_dump() == b.model_dump()
    assert a.policy_version == "strictness-v1"


def test_teacher_overrides_applied_and_audited() -> None:
    policy = StrictnessEngine.build(60, {"word_count_grace_percentage": 0, "mandatory_terms_enforced": True})
    assert policy.word_count.grace_percentage == 0.0
    assert policy.terminology.enforce_mandatory_terms is True
    assert policy.overrides_applied == {"word_count_grace_percentage": 0.0, "mandatory_terms_enforced": True}


def test_unknown_override_rejected() -> None:
    with pytest.raises(StrictnessPolicyError):
        StrictnessEngine.build(60, {"totally_bogus_key": 1})


def test_strictness_does_not_change_facts_or_maxima() -> None:
    """Truth / maxima / rubric weights are identical across strictness levels."""
    rubric = make_rubric()
    answer = make_answer("TCP is connection oriented. " * 30)
    lenient = evaluate_answer(answer, rubric, policy_for(10))
    strict = evaluate_answer(answer, rubric, policy_for(95))
    assert lenient.word_count.actual == strict.word_count.actual
    assert lenient.rubric_validation.question_maximum == strict.rubric_validation.question_maximum
    assert lenient.keywords.matched == strict.keywords.matched


# ---------------------------------------------------------------------------
# Module 12 — deterministic rules
# ---------------------------------------------------------------------------
def test_word_count_and_grace() -> None:
    result = evaluate_answer(make_answer("word " * 78), make_rubric(minimum_words=100), policy_for(60))
    assert result.word_count.actual == 78
    assert result.word_count.effective_minimum == 90  # 10% standard grace at strictness 60
    assert result.word_count.deficit == 12
    assert result.answer_too_short is True


def test_word_count_within_grace_passes() -> None:
    result = evaluate_answer(make_answer("word " * 91), make_rubric(), policy_for(60))
    assert result.word_count.within_requirement is True
    assert not any(p.penalty_type == "word_count_deficit" for p in result.deterministic_penalties)


def test_word_count_penalty_bounded_by_cap() -> None:
    rubric = make_rubric(minimum_words=200)
    result = evaluate_answer(make_answer("word " * 10), rubric, policy_for(60))
    penalty = next(p for p in result.deterministic_penalties if p.penalty_type == "word_count_deficit")
    assert penalty.marks <= policy_for(60).max_word_count_penalty(rubric.maximum_marks) + 1e-9


def test_empty_answer_flagged() -> None:
    result = evaluate_answer(make_answer(""), make_rubric(), policy_for(60))
    assert result.answer_empty is True and "answer_empty" in result.flags


def test_literal_keyword_matching_case_and_punctuation() -> None:
    matched, missing = match_literal_terms(
        "The ACKNOWLEDGEMENT was sent; re-transmission delayed!", ["acknowledgement"]
    )
    assert matched == ["acknowledgement"]  # 're-transmission' != whole-word 'retransmission'
    assert missing == []


def test_duplicate_keyword_counts_once() -> None:
    matched, _ = match_literal_terms("acknowledgement acknowledgement ACKNOWLEDGEMENT", ["acknowledgement"])
    assert matched == ["acknowledgement"]


def test_mandatory_term_penalty_only_when_policy_enforces() -> None:
    text = "word " * 120  # no TCP anywhere
    standard = evaluate_answer(make_answer(text), make_rubric(), policy_for(41))
    assert standard.mandatory_terms.missing == ["TCP"]
    assert not any(p.penalty_type == "mandatory_terms_missing" for p in standard.deterministic_penalties)

    strict = evaluate_answer(make_answer(text), make_rubric(), policy_for(70))
    assert any(p.penalty_type == "mandatory_terms_missing" for p in strict.deterministic_penalties)


def test_diagram_required_vs_present() -> None:
    rubric = make_rubric(diagram=DiagramRequirements(required=True))
    missing = evaluate_answer(make_answer("word " * 150), rubric, policy_for(60))
    assert missing.diagram.present is False and "diagram_required_missing" in missing.flags

    ok = evaluate_answer(make_answer("word " * 150, diagrams=[present_diagram()]), rubric, policy_for(60))
    assert ok.diagram.present is True and "diagram_required_missing" not in ok.flags


def test_invalid_rubrics_rejected() -> None:
    """Construction-time rejection (pydantic) and explicit validate_rubric entry point."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_rubric(
            expected_concepts=[
                ExpectedConcept(concept_id="C1", description="a", maximum_marks=6),
                ExpectedConcept(concept_id="C2", description="b", maximum_marks=6),
            ]
        )

    # Bypassing construction validation must still fail explicit validation.
    from answer_eval.grading.rubric import AnswerType

    bypassed = QuestionRubric.model_construct(
        schema_version="rubric-v1",
        version="rubric-v1",
        question_id="Q4",
        question_text="",
        answer_type=AnswerType.explain,
        maximum_marks=10,
        expected_answer=None,
        expected_concepts=[
            ExpectedConcept(concept_id="C1", description="a", maximum_marks=6),
            ExpectedConcept(concept_id="C2", description="b", maximum_marks=6),
        ],
        keywords=[],
        mandatory_terms=[],
        minimum_words=0,
        grace_words=None,
        diagram=DiagramRequirements(),
        strictness=60,
        overrides={},
        require_exact_criteria_total=True,
    )
    with pytest.raises(RubricValidationError):
        bypassed.validate_rubric()


def test_normalize_helper() -> None:
    assert normalize_for_matching("TCP/IP Protocol") == normalize_for_matching("tcp/ip protocol")
