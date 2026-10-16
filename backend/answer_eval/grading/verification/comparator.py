"""Deterministic evaluator/verifier comparator (Module 15). PURE PYTHON.

Compares criterion by criterion — not just totals. Two graders can agree on
the total while splitting marks very differently across criteria, which is
still important disagreement.
"""

from typing import Any

from answer_eval.core.logging import get_logger
from answer_eval.grading.evaluation.schemas import EvaluationResult
from answer_eval.grading.verification.schemas import (
    CriterionDisagreement,
    EvidenceDisagreement,
    VerificationComparison,
)

logger = get_logger("grading.comparison")

# Comparison policy (heuristic-risk-v1 era defaults; calibrated later).
MARK_AGREEMENT_TOLERANCE = 0.5  # |diff| <= 0.5 marks counts as agreement
MAJOR_MARK_DIFFERENCE = 2.0  # any criterion differing by >= 2 marks is major
MIN_AGREEMENT_RATE = 0.7  # below this rate -> major disagreement
STATUS_SEVERITY = {
    "fully_supported": 3,
    "partially_supported": 2,
    "uncertain": 1,
    "not_applicable": 0,
    "unsupported": 0,
    "contradicted": -2,
}


def _status_str(status: Any) -> str:
    return str(getattr(status, "value", status))


def _status_severity(status: Any) -> int:
    return STATUS_SEVERITY.get(_status_str(status), 0)


def compare(
    evaluation: EvaluationResult,
    verification: EvaluationResult,
    question_id: str,
) -> VerificationComparison:
    """Compare evaluator and verifier results criterion by criterion."""
    eval_by_id = {c.criterion_id: c for c in evaluation.criteria}
    ver_by_id = {c.criterion_id: c for c in verification.criteria}
    all_ids = list(dict.fromkeys([*eval_by_id.keys(), *ver_by_id.keys()]))

    disagreements: list[CriterionDisagreement] = []
    evidence_disagreements: list[EvidenceDisagreement] = []
    contradiction_disagreements: list[str] = []
    agreed = 0

    for cid in all_ids:
        e = eval_by_id.get(cid)
        v = ver_by_id.get(cid)
        e_marks = float(e.proposed_marks) if e else 0.0
        v_marks = float(v.proposed_marks) if v else 0.0
        diff = round(abs(e_marks - v_marks), 2)

        if diff <= MARK_AGREEMENT_TOLERANCE:
            agreed += 1
        else:
            disagreements.append(
                CriterionDisagreement(
                    criterion_id=cid,
                    criterion=(e or v).criterion if e or v else "",
                    evaluator_status=_status_str(e.status) if e else "missing",
                    verifier_status=_status_str(v.status) if v else "missing",
                    evaluator_marks=e_marks,
                    verifier_marks=v_marks,
                    mark_difference=diff,
                )
            )

        # Status-severity mismatch even when marks happen to match closely.
        if e and v:
            e_sev, v_sev = _status_severity(e.status), _status_severity(v.status)
            if abs(e_sev - v_sev) >= 2:
                disagreements.append(
                    CriterionDisagreement(
                        criterion_id=cid,
                        criterion=e.criterion,
                        evaluator_status=_status_str(e.status),
                        verifier_status=_status_str(v.status),
                        evaluator_marks=e_marks,
                        verifier_marks=v_marks,
                        mark_difference=diff,
                    )
                )
            e_ev = {ev.quote for ev in e.student_evidence if ev.verified_in_answer}
            v_ev = {ev.quote for ev in v.student_evidence if ev.verified_in_answer}
            if e_ev and not (e_ev & v_ev):
                evidence_disagreements.append(
                    EvidenceDisagreement(criterion_id=cid, detail="No overlapping verified evidence")
                )

        one_contradicted = (e and _status_str(e.status) == "contradicted") != (
            v and _status_str(v.status) == "contradicted"
        )
        if one_contradicted:
            contradiction_disagreements.append(cid)

    evaluated_total = evaluation.criteria_total()
    verified_total = verification.criteria_total()
    total_difference = round(abs(evaluated_total - verified_total), 2)
    rate = round(agreed / len(all_ids), 4) if all_ids else 1.0

    reasons: list[str] = []
    major = False
    if total_difference >= MAJOR_MARK_DIFFERENCE:
        major = True
        reasons.append(f"Totals differ by {total_difference} marks.")
    if any(d.mark_difference >= MAJOR_MARK_DIFFERENCE for d in disagreements):
        major = True
        worst = max(disagreements, key=lambda d: d.mark_difference)
        reasons.append(f"Criterion '{worst.criterion_id}' differs by {worst.mark_difference} marks.")
    if all_ids and rate < MIN_AGREEMENT_RATE:
        major = True
        reasons.append(f"Criterion agreement rate {rate:.0%} is below {MIN_AGREEMENT_RATE:.0%}.")
    if contradiction_disagreements:
        major = True
        reasons.append(f"Contradiction disagreement on criteria: {contradiction_disagreements}.")

    comparison = VerificationComparison(
        question_id=question_id,
        evaluator_total=evaluated_total,
        verifier_total=verified_total,
        total_difference=total_difference,
        criteria_compared=len(all_ids),
        criteria_agreed=agreed,
        criterion_agreement_rate=rate,
        criterion_disagreements=disagreements,
        evidence_disagreements=evidence_disagreements,
        contradiction_disagreements=contradiction_disagreements,
        major_disagreement=major,
        reasons=reasons,
    )

    logger.info(
        "[COMPARISON]",
        question_id=question_id,
        evaluator_total=evaluated_total,
        verifier_total=verified_total,
        agreement_rate=rate,
        major_disagreement=major,
    )
    return comparison
