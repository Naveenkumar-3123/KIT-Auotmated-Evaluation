"""Milestone 11 unit tests: math step evaluation + deterministic equivalence (#44-#48)."""

from __future__ import annotations

from answer_eval.grading.math_engine import (
    evaluate_math_work,
    expressions_equivalent,
    parse_expression,
)
from answer_eval.grading.math_schemas import (
    MathRubric,
    MathStep,
    StudentMathWork,
    StudentStepClaim,
)


def rubric_math(**kw) -> MathRubric:
    """The #44 example: formula(2) + substitution(2) + calculation(3) + final(2) + unit(1)."""
    defaults = dict(
        steps=[
            MathStep(step_id="M1", description="Select correct formula", marks=2, expression="v=u+a*t"),
            MathStep(step_id="M2", description="Substitute values correctly", marks=2, expression="10+2*5"),
            MathStep(step_id="M3", description="Perform calculation", marks=3, expression="20"),
            MathStep(step_id="M4", description="Final answer", marks=2, is_final_answer=True),
            MathStep(step_id="M5", description="Correct unit", marks=1),
        ],
        final_answer="20 m/s",
    )
    defaults.update(kw)
    return MathRubric(**defaults)


def claim(step_id: str | None = None, expr: str | None = None, **kw) -> StudentStepClaim:
    return StudentStepClaim(rubric_step_id=step_id, student_expression=expr, **kw)


# ---------------------------------------------------------------------------
# Spec #46 — deterministic equivalence (SymPy)
# ---------------------------------------------------------------------------


def test_symbolic_equivalence() -> None:
    assert expressions_equivalent("(a+b)^2", "a^2 + 2ab + b^2") is True
    assert expressions_equivalent("x^2", "x**2") is True
    assert expressions_equivalent("1/2", "0.5") is True
    assert expressions_equivalent("u+at", "u-at") is False


def test_numeric_tolerance() -> None:
    assert expressions_equivalent("3.14159", "3.14159265", tolerance=1e-4) is True
    assert expressions_equivalent("3.14159", "3.14159265", tolerance=1e-9) is False


def test_unparseable_returns_none_not_guess() -> None:
    assert expressions_equivalent("???garbled???", "20") is None
    assert parse_expression("???") is None


# ---------------------------------------------------------------------------
# Spec #45/#47 — independent steps, follow-through, final-only
# ---------------------------------------------------------------------------


def test_correct_method_wrong_final_calculation() -> None:
    """#45: correct formula/substitution but arithmetic slip -> earlier steps keep marks."""
    work = StudentMathWork(
        question_id="Q1",
        claims=[
            claim("M1", "v=u+a*t"),
            claim("M2", "10+2*5"),
            claim("M3", "25"),  # arithmetic error (should be 20)
            claim("M4", "25", is_final_answer=True),
            claim("M5", "m/s"),
        ],
    )
    result = evaluate_math_work(rubric_math(final_answer="20 m/s"), work)
    by_id = {o.step_id: o for o in result.outcomes}
    assert by_id["M1"].status.value == "correct"
    assert by_id["M2"].status.value == "correct"
    assert by_id["M3"].status.value == "incorrect"
    assert result.final_matches_key is False
    assert result.total_awarded == 5.0  # 2 + 2 + 0 + 0 + 1(unit)


def test_follow_through_error_not_zeroed() -> None:
    """#47: wrong substitution carried consistently -> later method steps earn marks."""
    work = StudentMathWork(
        question_id="Q1",
        claims=[
            claim("M1", "v=u+a*t"),
            claim("M2", "10+2*7"),  # wrong value substituted (14 not 10)
            claim("M3", "24", internally_consistent=True),  # consistent with their own value
            claim("M4", "24", is_final_answer=True),
        ],
    )
    result = evaluate_math_work(rubric_math(), work)
    by_id = {o.step_id: o for o in result.outcomes}
    assert by_id["M2"].status.value == "incorrect"
    assert by_id["M3"].status.value == "follow_through"
    assert by_id["M3"].awarded == 3.0


def test_correct_final_without_working_gets_only_final_marks() -> None:
    """#45: answer-only -> only the final-answer step's marks."""
    work = StudentMathWork(question_id="Q1", claims=[claim("M4", "20", is_final_answer=True)])
    result = evaluate_math_work(rubric_math(), work)
    by_id = {o.step_id: o for o in result.outcomes}
    assert by_id["M4"].awarded == 2.0
    assert by_id["M1"].status.value == "not_attempted"
    assert result.total_awarded == 2.0


# ---------------------------------------------------------------------------
# Alternative methods, unmapped claims, OCR uncertainty
# ---------------------------------------------------------------------------


def test_alternative_valid_method_accepted_when_verifiable() -> None:
    """#45: a different route is accepted when its expressions verify."""
    rm = rubric_math(
        steps=[
            MathStep(step_id="M1", description="kinematics route", marks=2, expression="u*t + a*t^2/2"),
            MathStep(step_id="M2", description="substitute", marks=2, expression="a*t^2/2"),
            MathStep(step_id="M3", description="distance", marks=3, expression="25"),
        ],
        final_answer=None,
    )
    work = StudentMathWork(
        question_id="Q1",
        claims=[
            claim("M1", "s = u*t + (1/2)*a*t**2", alternative_method=True),
            claim("M2", "(1/2)*a*t^2", alternative_method=True),
            claim("M3", "t^2*a/2 + 5", alternative_method=True),  # not equal to expected -> flagged
        ],
    )
    result = evaluate_math_work(rm, work)
    by_id = {o.step_id: o for o in result.outcomes}
    assert by_id["M1"].status.value == "correct"  # equivalent symbolic form accepted
    assert by_id["M3"].status.value in ("incorrect", "uncertain")


def test_unmapped_claim_is_flagged() -> None:
    work = StudentMathWork(
        question_id="Q1",
        claims=[claim(None, "some scribble"), claim("M1", "v=u+a*t")],
    )
    result = evaluate_math_work(rubric_math(), work)
    assert "math_claim_unmapped_step" in result.flags


def test_ocr_uncertain_routes_to_teacher_review() -> None:
    work = StudentMathWork(
        question_id="Q1",
        claims=[claim("M2", "1O+2*5", ocr_uncertain=True)],  # 'O' vs '0' unreadable
    )
    result = evaluate_math_work(rubric_math(), work)
    by_id = {o.step_id: o for o in result.outcomes}
    assert by_id["M2"].status.value == "uncertain"
    assert by_id["M2"].awarded == 0.0
    assert "math_symbol_uncertain" in result.flags


def test_total_clamped_to_possible() -> None:
    rm = rubric_math(steps=[MathStep(step_id="M1", description="only step", marks=2, expression="20")])
    work = StudentMathWork(question_id="Q1", claims=[claim("M1", "20")])
    result = evaluate_math_work(rm, work)
    assert result.total_awarded <= result.total_possible == 2.0



