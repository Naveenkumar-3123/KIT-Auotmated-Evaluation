"""Bridge: resolved per-question policies (M5 question_policies) → the rubric +
teacher rules the evaluation workflow consumes.

The workflow grades from two state slices:
  state["rubrics"]          — {question_id: QuestionRubric.dump}
  state["teacher_rules"]    — {question_id: TeacherQuestionRules.dump} (optional)

This module is the single place that turns the immutable resolved-policy rows
(frozen at finalize time) into those runtime inputs, so starting an assessment
and the actual grading always agree with what the teacher configured.
"""

from __future__ import annotations

from typing import Any

from answer_eval.grading.math_schemas import MathRubric
from answer_eval.grading.rubric import AnswerType, DiagramRequirements, ExpectedConcept, QuestionRubric
from answer_eval.grading.rules.schemas import DiagramPolicyRule, TeacherQuestionRules, WordCountPolicyRule

# Level (as stored in question_policies.strictness_level) -> strictness score.
# The StrictnessEngine maps the score to a versioned band.
STRICTNESS_LEVEL_SCORES: dict[str, int] = {
    "lenient": 40,
    "moderate": 60,
    "strict": 80,
}

# ANSWER_TYPES from the answer-key parser map into the richer grading rubric
# AnswerType enum (the two vocabularies differ on a few labels).
_ANSWER_TYPE_MAP: dict[str, AnswerType] = {
    "descriptive": AnswerType.describe,
    "explain": AnswerType.explain,
    "short_answer": AnswerType.short_answer,
    "numerical": AnswerType.numerical,
    "formula": AnswerType.formula,
    "diagram": AnswerType.diagram_only,
    "mixed": AnswerType.text_with_diagram,
}


def _map_answer_type(value: str | None) -> AnswerType:
    return _ANSWER_TYPE_MAP.get(str(value or "").strip().lower(), AnswerType.explain)


def _as_dict(value: Any) -> dict[str, Any]:
    """jsonb columns arrive as dicts (asyncpg codec) or JSON strings (raw
    connections/scripts). Normalize both so every caller behaves identically."""
    if isinstance(value, str):
        import json

        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    if isinstance(value, str):
        import json

        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return value if isinstance(value, list) else []


def _math_rubric_or_none(snapshot: dict[str, Any]) -> MathRubric | None:
    raw = _as_list(snapshot.get("math_rubric"))
    if not raw:
        return None
    try:
        steps = [
            {
                "step_id": str(s.get("step_id")),
                "description": str(s.get("description") or ""),
                "marks": float(s.get("marks") or 0),
                "expression": s.get("expression"),
                "is_final_answer": bool(s.get("is_final_answer", False)),
            }
            for s in raw
        ]
        return MathRubric(steps=steps)
    except Exception:  # noqa: BLE001 - a malformed math block must not sink the whole job
        return None
def build_question_rubric(row: dict[str, Any]) -> QuestionRubric:
    """Build one QuestionRubric from a resolved question_policies row."""
    number = int(row.get("question_number") or 0)
    if number <= 0:
        raise ValueError(f"Resolved policy has no valid question_number: {row!r}")
    qid = f"Q{number}"
    snapshot = _as_dict(row.get("rubric_snapshot"))

    concepts: list[ExpectedConcept] = []
    for c in _as_list(snapshot.get("concepts")):
        cid = c.get("concept_code") or c.get("concept_id")
        concepts.append(
            ExpectedConcept(
                concept_id=str(cid) if cid else f"C{len(concepts) + 1}",
                description=str(c.get("description") or ""),
                maximum_marks=float(c.get("maximum_marks") or 0),
            )
        )

    maximum_marks = float(snapshot.get("maximum_marks") or row.get("maximum_marks") or 0)
    if maximum_marks <= 0:
        # The workflow rejects zero/negative maxima (rubric arithmetic valid).
        maximum_marks = 1.0

    strictness = STRICTNESS_LEVEL_SCORES.get(str(row.get("strictness_level") or "moderate").lower(), 60)

    return QuestionRubric(
        question_id=qid,
        question_text=str(snapshot.get("question_text") or ""),
        answer_type=_map_answer_type(snapshot.get("answer_type")),
        maximum_marks=maximum_marks,
        expected_concepts=concepts,
        keywords=list(snapshot.get("keywords") or []),
        mandatory_terms=list(snapshot.get("mandatory_terms") or []),
        minimum_words=int(row.get("minimum_words") or 0),
        diagram=DiagramRequirements(
            required=bool(row.get("diagram_required")),
            minimum_components=int(row.get("min_diagrams") or 0),
        ),
        strictness=strictness,
        math_rubric=_math_rubric_or_none(snapshot),
        # Parsed keys are provisional — the teacher review step resolves concept
        # totals. Demand exact sums would reject valid partial keys.
        require_exact_criteria_total=False,
    )


def build_teacher_rules(row: dict[str, Any]) -> TeacherQuestionRules:
    """Build the resolved per-question teacher rules (explicit deduction amounts).

    When present these override strictness-derived penalty amounts; strictness
    then governs semantic precision only. Terminology has no stored explicit
    deduction in question_policies, so it is left None and falls back to the
    strictness-derived enforcement.
    """
    number = int(row.get("question_number") or 0)
    qid = f"Q{number}"

    minimum_words = int(row.get("minimum_words") or 0)
    marks_deducted = float(row.get("marks_deducted") or 0)
    word_count: WordCountPolicyRule | None = None
    if minimum_words > 0 or marks_deducted > 0:
        trigger = int(row.get("trigger_shortfall_words") or 0)
        if minimum_words > 0 and trigger >= minimum_words:
            trigger = max(0, minimum_words - 1)
        word_count = WordCountPolicyRule(
            minimum_words=minimum_words,
            trigger_shortfall_words=trigger,
            marks_deducted=marks_deducted,
            mode=str(row.get("word_count_mode") or "once"),
        )

    diagram: DiagramPolicyRule | None = None
    if bool(row.get("diagram_required")):
        required_count = int(row.get("min_diagrams") or 1)
        deductions = [float(x) for x in _as_list(row.get("missing_diagram_deductions"))]
        deductions = (deductions[:required_count] + [0.0] * required_count)[:required_count]
        diagram = DiagramPolicyRule(
            required=True,
            minimum_diagrams=required_count,
            missing_diagram_deductions=deductions,
        )

    return TeacherQuestionRules(
        question_id=qid,
        version=int(row.get("version") or 1),
        word_count=word_count,
        diagram=diagram,
        terminology=None,
    )


def build_workflow_inputs(
    resolved_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (rubrics, teacher_rules) keyed by "Q{n}", in question order."""
    rubrics: dict[str, dict[str, Any]] = {}
    teacher_rules: dict[str, dict[str, Any]] = {}
    for row in sorted(resolved_rows, key=lambda r: int(r.get("question_number") or 0)):
        rubric = build_question_rubric(row)
        rules = build_teacher_rules(row)
        question_id = rubric.question_id
        rubrics[question_id] = rubric.model_dump()
        teacher_rules[question_id] = rules.model_dump()
    return rubrics, teacher_rules
