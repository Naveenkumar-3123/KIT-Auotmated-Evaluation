"""Heuristic confidence / risk engine (Module 16). DETERMINISTIC PYTHON.

Confidence is computed from observable signals (OCR uncertainty, segmentation
quality, grader agreement, evidence validity, schema/arithmetic validity) —
never from a model's self-reported confidence number.

Policy version: heuristic-risk-v1 (initial, UNCALIBRATED weights).
"""

from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.core.logging import get_logger
from answer_eval.grading.confidence.policies import (
    AUTO_APPROVE_MAX_LEVEL,
    LOW_RISK_THRESHOLD,
    MANDATORY_REVIEW_TRIGGERS,
    MEDIUM_RISK_THRESHOLD,
    RISK_POLICY_VERSION,
    SIGNAL_WEIGHTS,
    TRIGGER_REASONS,
)
from answer_eval.grading.confidence.schemas import RiskAssessment, RiskSignals
from answer_eval.grading.rules.schemas import RuleEvaluationResult
from answer_eval.grading.verification.schemas import VerificationComparison

logger = get_logger("grading.risk")

_OCR_QUALITY_FLAGS = {"very_faint", "poor_quality", "low_contrast", "skewed"}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _ocr_uncertainty(answer: CanonicalStructuredAnswer) -> float:
    span_risk = _clamp01(len(answer.uncertainties) / 10.0)
    flag_risk = 1.0 if any(f in _OCR_QUALITY_FLAGS for f in answer.flags) else 0.0
    return _clamp01(0.6 * span_risk + 0.4 * flag_risk)


def _segmentation_uncertainty(answer: CanonicalStructuredAnswer) -> float:
    seg_flags = [f for f in answer.flags if "unknown_region" in f or "boundary" in f]
    risk = _clamp01(len(seg_flags) / 3.0)
    multi_page = len({s.page_number for s in answer.segments}) > 1
    if multi_page and any("continuation" in f for f in answer.flags):
        risk = _clamp01(risk + 0.4)
    return risk


def _diagram_uncertainty(answer: CanonicalStructuredAnswer, diagram_required: bool) -> float:
    if not diagram_required:
        return 0.0
    diagrams = answer.diagrams
    if not diagrams or not any(d.diagram_present for d in diagrams):
        return 1.0  # required diagram completely missing
    worst = 0.0
    quality_scale = {"good": 0.1, "medium": 0.5, "poor": 0.9}
    for d in diagrams:
        if not d.diagram_present:
            continue
        score = max(
            quality_scale.get(d.visual_quality.legibility, 0.5),
            quality_scale.get(d.visual_quality.label_clarity, 0.5),
        )
        score += 0.1 * min(len(d.uncertain_elements), 5) / 5
        worst = max(worst, score)
    return _clamp01(worst)


def _grader_disagreement(comparison: VerificationComparison | None) -> float:
    if comparison is None:
        return 0.0
    total_based = _clamp01(comparison.total_difference / 5.0)
    rate_based = 1.0 - comparison.criterion_agreement_rate
    major_bonus = 0.25 if comparison.major_disagreement else 0.0
    return _clamp01(0.5 * total_based + 0.4 * rate_based + major_bonus)


_TRIGGER_REASONS = TRIGGER_REASONS


def assess_risk(
    answer: CanonicalStructuredAnswer,
    rule_result: RuleEvaluationResult,
    comparison: VerificationComparison | None = None,
    extra_flags: list[str] | None = None,
) -> RiskAssessment:
    """Compute the deterministic risk assessment for one graded question."""
    diagram_uncertainty = _diagram_uncertainty(answer, rule_result.diagram.required)
    all_flags = [*answer.flags, *rule_result.flags, *(extra_flags or [])]

    unverified_evidence = sum(1 for f in all_flags if f.startswith("unverified_evidence"))
    validation_failures = [f for f in all_flags if f in ("schema_validation_failed", "arithmetic_validation_failed")]

    signals = RiskSignals(
        ocr_uncertainty=_ocr_uncertainty(answer),
        segmentation_uncertainty=_segmentation_uncertainty(answer),
        diagram_uncertainty=diagram_uncertainty,
        grader_disagreement=_grader_disagreement(comparison),
        evidence_risk=_clamp01(unverified_evidence / 3.0),
        validation_risk=1.0 if validation_failures else 0.0,
    )

    risk_score = _clamp01(sum(getattr(signals, name) * weight for name, weight in SIGNAL_WEIGHTS.items()))
    if risk_score < LOW_RISK_THRESHOLD:
        risk_level = "low"
    elif risk_score < MEDIUM_RISK_THRESHOLD:
        risk_level = "medium"
    else:
        risk_level = "high"

    # Mandatory review triggers ALWAYS override the numeric threshold.
    review_reasons: list[str] = []
    flag_set = set(all_flags)
    triggered = {
        t for t in MANDATORY_REVIEW_TRIGGERS if t in flag_set or any(f == t or f.startswith(t + ":") for f in all_flags)
    }
    if comparison is not None and comparison.major_disagreement:
        triggered.add("major_grader_disagreement")
    for trigger in sorted(triggered):
        reason = _TRIGGER_REASONS.get(trigger, f"Mandatory review trigger: {trigger}.")
        if reason not in review_reasons:
            review_reasons.append(reason)

    hard_validations_passed = not validation_failures and rule_result.rubric_validation.valid
    auto_approve = risk_level == AUTO_APPROVE_MAX_LEVEL and not review_reasons and hard_validations_passed

    assessment = RiskAssessment(
        risk_policy_version=RISK_POLICY_VERSION,
        question_id=rule_result.question_id,
        risk_score=round(risk_score, 4),
        risk_level=risk_level,
        auto_approve=auto_approve,
        signals=signals,
        review_reasons=review_reasons,
        hard_validations_passed=hard_validations_passed,
    )

    logger.info(
        "[RISK]",
        question_id=rule_result.question_id,
        policy=RISK_POLICY_VERSION,
        risk_score=assessment.risk_score,
        risk_level=risk_level,
        auto_approve=auto_approve,
        review_reasons=len(review_reasons),
    )
    return assessment
