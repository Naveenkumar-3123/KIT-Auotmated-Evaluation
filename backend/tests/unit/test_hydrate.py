"""Unit tests for the resolved-policy → workflow-rubric bridge (hydrate)."""

from __future__ import annotations

from answer_eval.grading.hydrate import (
    STRICTNESS_LEVEL_SCORES,
    build_question_rubric,
    build_teacher_rules,
    build_workflow_inputs,
)
from answer_eval.grading.rubric import QuestionRubric
from answer_eval.grading.rules.schemas import TeacherQuestionRules


def _row(number: int = 1, **overrides) -> dict:
    _SNAPSHOT_KEYS = {
        "answer_type",
        "maximum_marks",
        "concepts",
        "keywords",
        "mandatory_terms",
        "math_rubric",
        "question_text",
    }
    base = {
        "question_number": number,
        "version": 7,
        "strictness_level": "strict",
        "minimum_words": 100,
        "word_count_mode": "once",
        "trigger_shortfall_words": 20,
        "marks_deducted": 1.0,
        "diagram_required": True,
        "min_diagrams": 2,
        "missing_diagram_deductions": [2.0, 1.0],
        "source_rule_ids": ["q1"],
        "rubric_snapshot": {
            "maximum_marks": 10,
            "answer_type": "explain",
            "question_text": "Explain flow control.",
            "concepts": [
                {"concept_code": "C1", "description": "Acknowledgements", "maximum_marks": 5},
                {"concept_code": "C2", "description": "Windowing", "maximum_marks": 5},
            ],
            "keywords": ["acknowledgement", "window"],
            "mandatory_terms": ["acknowledgement"],
            "answer_key_version": 3,
        },
    }
    for key, value in overrides.items():
        if key in _SNAPSHOT_KEYS:
            base["rubric_snapshot"][key] = value
        else:
            base[key] = value
    return base


def test_build_workflow_inputs_keys_and_order() -> None:
    rubrics, teacher_rules = build_workflow_inputs([_row(2), _row(1)])
    assert list(rubrics) == ["Q1", "Q2"]  # sorted by question_number
    assert list(teacher_rules) == ["Q1", "Q2"]
    assert rubrics["Q1"]["maximum_marks"] == 10
    assert rubrics["Q1"]["strictness"] == STRICTNESS_LEVEL_SCORES["strict"]
    assert teacher_rules["Q1"]["question_id"] == "Q1"


def test_answer_type_mapping() -> None:
    assert build_question_rubric(_row(answer_type="diagram")).answer_type.value == "diagram_only"
    assert build_question_rubric(_row(answer_type="numerical")).answer_type.value == "numerical"
    assert build_question_rubric(_row(answer_type="descriptive")).answer_type.value == "describe"
    assert build_question_rubric(_row(answer_type="mixed")).answer_type.value == "text_with_diagram"
    assert build_question_rubric(_row(answer_type="")).answer_type.value == "explain"


def test_teacher_word_count_and_diagram_rules_encoded() -> None:
    rules = build_teacher_rules(_row())
    assert rules.word_count is not None
    assert rules.word_count.minimum_words == 100
    assert rules.word_count.trigger_shortfall_words == 20
    assert rules.word_count.marks_deducted == 1.0
    assert rules.diagram is not None
    assert rules.diagram.required is True
    assert rules.diagram.minimum_diagrams == 2
    assert rules.diagram.missing_diagram_deductions == [2.0, 1.0]
    # Terminology has no explicit stored amount -> strictness governs.
    assert rules.terminology is None


def test_no_rules_when_nothing_configured() -> None:
    rules = build_teacher_rules(
        _row(minimum_words=0, marks_deducted=0, diagram_required=False, missing_diagram_deductions=[])
    )
    assert rules.word_count is None
    assert rules.diagram is None


def test_malformed_math_rubric_does_not_sink_job() -> None:
    row = _row(math_rubric=[{"step_id": "M1", "marks": -5}, {}])  # marks ge=0 violated, missing description
    rubric = build_question_rubric(row)
    assert rubric.math_rubric is None
    assert isinstance(rubric, QuestionRubric)


def test_valid_math_rubric_preserved() -> None:
    row = _row(
        answer_type="numerical",
        math_rubric=[{"step_id": "M1", "description": "Setup equation", "marks": 2}],
    )
    rubric = build_question_rubric(row)
    assert rubric.math_rubric is not None
    assert rubric.math_rubric.steps[0].step_id == "M1"

    # The encoded dump must re-validate as a QuestionRubric (workflow contract).
    assert QuestionRubric.model_validate(rubric.model_dump()) is not None


def test_teacher_rules_round_trip_through_schema() -> None:
    rules = build_teacher_rules(_row())
    assert TeacherQuestionRules.model_validate(rules.model_dump()) == rules
