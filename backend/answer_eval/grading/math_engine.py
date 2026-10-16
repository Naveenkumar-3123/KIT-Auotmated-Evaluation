"""Deterministic math engine (Milestone 11, specs #45-#48). PURE PYTHON + SymPy.

Policy implemented here:
  #45  Steps are awarded independently. A wrong final calculation does not
       zero correctly-completed earlier steps. A correct final answer with no
       working earns only the final-answer step's marks. Alternative valid
       methods are accepted whenever their expressions can be verified.
  #46  Arithmetic/equivalence/tolerance/summation: deterministic (SymPy).
       The model only interprets handwriting and maps steps.
  #47  Follow-through: after a genuine student error, later steps that are
       internally consistent with the student's own carried value earn their
       method marks instead of being zeroed.
  #48  Unreliable OCR of operators/signs/digits -> status "uncertain"; the
       question routes to teacher verification. Nothing is guessed.
"""

from __future__ import annotations

import re

from sympy import simplify
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from answer_eval.core.logging import get_logger
from answer_eval.grading.math_schemas import (
    MathEvaluationResult,
    MathRubric,
    MathStepOutcome,
    StepStatus,
    StudentMathWork,
    StudentStepClaim,
)

logger = get_logger("grading.math_engine")

_TRANSFORMATIONS = standard_transformations + (convert_xor, implicit_multiplication_application)


def _clean(expr_text: str) -> str:
    """Normalize handwriting transcription into a parseable expression."""
    text = expr_text.strip().rstrip(".").replace("×", "*").replace("÷", "/").replace("−", "-")
    if "=" in text:
        # Equation marker: compare the computed side (last non-empty).
        sides = [side.strip() for side in text.split("=") if side.strip()]
        if sides:
            text = sides[-1]
    return text


def _leading_number(text: str) -> str | None:
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return match.group(0) if match else None


def parse_expression(expr_text: str | None):
    """Parse an expression to SymPy. Returns None when unparseable."""
    if not expr_text or not expr_text.strip():
        return None
    try:
        return parse_expr(
            _clean(expr_text),
            transformations=_TRANSFORMATIONS,
            evaluate=True,
        )
    except Exception:  # noqa: BLE001 - any parse failure means "cannot verify"
        return None


def expressions_equivalent(a_text: str, b_text: str, tolerance: float = 1e-6) -> bool | None:
    """Symbolic equivalence first, numeric tolerance fallback.

    Returns True/False, or None when either side cannot be parsed reliably.
    """
    a = parse_expression(a_text)
    b = parse_expression(b_text)
    if a is None or b is None:
        return None
    try:
        difference = simplify(a - b)
        if difference == 0:
            return True
        if not difference.free_symbols:
            magnitude = max(1.0, abs(float(b.evalf())))
            return abs(float(difference.evalf())) <= tolerance * magnitude
        # Unit-suffixed key like "20 m/s" parses with free symbols; compare the
        # student's pure number against the key's leading numeric value.
        if not a.free_symbols and b.free_symbols:
            key_number = _leading_number(b_text)
            if key_number is not None:
                magnitude = max(1.0, abs(float(key_number)))
                return abs(float(a.evalf()) - float(key_number)) <= tolerance * magnitude * 1000
        return False
    except Exception:  # noqa: BLE001 - equivalence genuinely undecidable
        return None


def _outcome(step, status: StepStatus, awarded: float, detail: str) -> MathStepOutcome:
    return MathStepOutcome(
        step_id=step.step_id,
        description=step.description,
        max_marks=step.marks,
        awarded=round(max(0.0, min(awarded, step.marks)), 2),
        status=status,
        detail=detail,
    )


_STATUS_TO_CRITERION = {
    StepStatus.correct: "fully_supported",
    StepStatus.follow_through: "fully_supported",
    StepStatus.incorrect: "unsupported",
    StepStatus.not_attempted: "unsupported",
    StepStatus.uncertain: "uncertain",
}


def _status_str(s: Any) -> str:
    return getattr(s, "value", str(s))


def math_result_to_evaluation(result: MathEvaluationResult, feedback: str = ""):
    """Adapt deterministic math outcomes into an EvaluationResult so the rest of
    the pipeline (comparison, risk, marks, review) works unchanged."""
    from answer_eval.grading.evaluation.schemas import (
        CriterionEvaluation,
        CriterionStatus,
        EvaluationResult,
        MatchType,
    )

    status_map = {
        getattr(CriterionStatus, name): value
        for value, names in {
            "fully_supported": (StepStatus.correct, StepStatus.follow_through),
            "unsupported": (StepStatus.incorrect, StepStatus.not_attempted),
            "uncertain": (StepStatus.uncertain,),
        }.items()
        for name in [_status_str(s) for s in names]
        if hasattr(CriterionStatus, name)
    }
    criteria = []
    for outcome in result.outcomes:
        criterion_status = CriterionStatus.unsupported
        out_val = _status_str(outcome.status)
        for candidate, source_values in status_map.items():
            if out_val in {_status_str(s) for s in source_values}:
                criterion_status = candidate
                break
        criteria.append(
            CriterionEvaluation(
                criterion_id=outcome.step_id,
                criterion=outcome.description,
                status=criterion_status,
                match_type=MatchType.exact,
                maximum_marks=outcome.max_marks,
                proposed_marks=outcome.awarded,
                reason=outcome.detail or f"status={out_val}",
            )
        )
    return EvaluationResult(
        question_id=result.question_id,
        criteria=criteria,
        flags=list(result.flags),
        feedback=feedback,
    )


def math_feedback(result: MathEvaluationResult) -> str:
    parts = [f"{o.step_id}: {_status_str(o.status)}" for o in result.outcomes]
    earned = f"awarded {result.total_awarded}/{result.total_possible}"
    return f"Step-by-step marking ({earned}). " + "; ".join(parts)


def evaluate_math_work(rubric_math: MathRubric, work: StudentMathWork) -> MathEvaluationResult:
    """Deterministic step-by-step awarding. See module docstring for the policy."""
    steps_by_id = {s.step_id: s for s in rubric_math.steps}
    flags: list[str] = []
    outcomes: list[MathStepOutcome] = []
    error_active = False
    final_matches_key: bool | None = None

    claimed_ids: set[str] = set()
    for claim in work.claims:
        step = steps_by_id.get(claim.rubric_step_id or "")
        if step is None:
            if claim.student_expression:
                flags.append("math_claim_unmapped_step")
            continue
        claimed_ids.add(step.step_id)

        # --- #48: unreliable OCR never guesses ------------------------------
        if claim.ocr_uncertain or work.overall_uncertain:
            outcomes.append(_outcome(step, StepStatus.uncertain, 0.0, "OCR uncertainty — routed to teacher verification"))
            flags.append("math_symbol_uncertain")
            continue

        # --- final-answer step ----------------------------------------------
        if claim.is_final_answer and rubric_math.final_answer:
            equivalent = expressions_equivalent(
                claim.student_expression or "", rubric_math.final_answer, rubric_math.numeric_tolerance
            )
            if equivalent is True:
                final_matches_key = True
                outcomes.append(_outcome(step, StepStatus.correct, step.marks, "Final answer matches the key."))
                error_active = False
                continue
            if equivalent is False:
                final_matches_key = False
                outcomes.append(_outcome(step, StepStatus.incorrect, 0.0, "Final answer does not match the key."))
                continue
            flags.append("math_final_unverifiable")
            outcomes.append(_outcome(step, StepStatus.uncertain, 0.0, "Final answer could not be verified."))
            continue

        outcomes.append(_regular_step(steps_by_id, claim, error_active, rubric_math, flags))
        last = outcomes[-1]
        if last.status == StepStatus.incorrect:
            error_active = True

    for step in rubric_math.steps:
        if step.step_id not in claimed_ids:
            outcomes.append(_outcome(step, StepStatus.not_attempted, 0.0, "No working mapped to this step."))

    order = {s.step_id: i for i, s in enumerate(rubric_math.steps)}
    outcomes.sort(key=lambda o: order.get(o.step_id, 999))
    total_possible = round(sum(s.marks for s in rubric_math.steps), 2)
    total_awarded = round(sum(o.awarded for o in outcomes), 2)
    total_awarded = max(0.0, min(total_awarded, total_possible))

    logger.info("[MATH]", question_id=work.question_id, awarded=total_awarded, possible=total_possible)
    return MathEvaluationResult(
        question_id=work.question_id,
        outcomes=outcomes,
        total_awarded=total_awarded,
        total_possible=total_possible,
        final_matches_key=final_matches_key,
        flags=list(dict.fromkeys(flags)),
    )


def _regular_step(
    steps_by_id: dict,
    claim: StudentStepClaim,
    error_active: bool,
    rubric_math: MathRubric,
    flags: list[str],
) -> MathStepOutcome:
    step = steps_by_id[claim.rubric_step_id or ""]
    expected_expr = step.expression
    student_expr = claim.student_expression
    if expected_expr and student_expr:
        equivalent = expressions_equivalent(student_expr, expected_expr, rubric_math.numeric_tolerance)
        if equivalent is True:
            status, detail = StepStatus.correct, "Expression matches the key symbolically/numerically."
        elif equivalent is False:
            if error_active and claim.internally_consistent:
                status, detail = StepStatus.follow_through, "Consistent with the student's carried value (#47)."
            else:
                status = StepStatus.incorrect
                detail = f"'{student_expr}' does not match the expected '{expected_expr}'."
        else:
            if error_active and claim.internally_consistent:
                status, detail = StepStatus.follow_through, "Unparseable but consistent with the carried value."
            else:
                flags.append("math_step_unverified")
                status, detail = StepStatus.uncertain, "Expression could not be parsed for verification."
        awarded = step.marks if status in (StepStatus.correct, StepStatus.follow_through) else 0.0
        return _outcome(step, status, awarded, detail)

    if error_active and claim.internally_consistent:
        return _outcome(step, StepStatus.follow_through, step.marks, "Follow-through method marks.")
    if claim.internally_consistent and not claim.alternative_method:
        flags.append("math_step_unverified")
        return _outcome(step, StepStatus.correct, step.marks, "Mapped by interpretation; no expression to verify.")
    flags.append("math_step_unverified")
    return _outcome(step, StepStatus.uncertain, 0.0, "Alternative/unverified route — teacher review.")
