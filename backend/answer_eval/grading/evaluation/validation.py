"""Deterministic validation helpers for evaluation/verification results.

Python — never the LLM — decides whether proposed marks are structurally
valid, clamps out-of-range values, and verifies that cited evidence actually
exists in the student's canonical answer.
"""

import re

from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.core.errors import EvaluationValidationError
from answer_eval.core.logging import get_logger
from answer_eval.grading.evaluation.schemas import CriterionEvaluation, EvaluationResult
from answer_eval.grading.rubric import QuestionRubric

logger = get_logger("grading.evaluation")

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_evidence_text(text: str) -> str:
    """Casefold, strip punctuation, collapse whitespace — for evidence matching."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub("", text.casefold())).strip()


def build_answer_corpus(answer: CanonicalStructuredAnswer) -> list[str]:
    """Normalized text corpus of the canonical answer (full text + per segment)."""
    corpus = [normalize_evidence_text(answer.raw_text or "")]
    for seg in answer.segments:
        if seg.raw_text:
            corpus.append(normalize_evidence_text(seg.raw_text))
    for diag in answer.diagrams:
        if diag.fallback_ocr_text:
            corpus.append(normalize_evidence_text(diag.fallback_ocr_text))
        for label in diag.labels:
            if label.text:
                corpus.append(normalize_evidence_text(label.text))
    return corpus


def evidence_exists_in_answer(quote: str, corpus: list[str]) -> bool:
    """True when a normalized quote appears in the canonical answer corpus.

    Substring matching over the full answer OR any single segment. This is a
    deliberately conservative containment check, not semantic matching.
    """
    needle = normalize_evidence_text(quote)
    if len(needle) < 3:
        return False
    return any(needle in hay for hay in corpus if hay)


def validate_and_sanitize(
    result: EvaluationResult,
    rubric: QuestionRubric,
    answer: CanonicalStructuredAnswer,
    clamp_marks: bool = True,
) -> EvaluationResult:
    """Validate criterion structure/marks against the rubric and verify evidence.

    - Marks are clamped into [0, criterion maximum] (flagged when clamped).
    - Criteria unknown to the rubric are flagged (never silently dropped).
    - Evidence quotes are checked against the canonical answer; unverifiable
      evidence is flagged `unverified_evidence`, never trusted silently.
    - Missing/invalid rubric structure raises EvaluationValidationError.
    """
    if result.question_id != rubric.question_id:
        raise EvaluationValidationError(
            f"Evaluation question_id '{result.question_id}' does not match rubric '{rubric.question_id}'"
        )

    concept_map = {c.concept_id: c for c in rubric.expected_concepts}
    corpus = build_answer_corpus(answer)
    flags: list[str] = list(result.flags)

    seen_criterion_ids: set[str] = set()
    sanitized: list[CriterionEvaluation] = []
    for crit in result.criteria:
        concept = concept_map.get(crit.criterion_id)
        if concept is None:
            flags.append(f"unknown_criterion:{crit.criterion_id}")
            logger.warning("Evaluation returned unknown criterion id", criterion_id=crit.criterion_id)
            continue

        if crit.criterion_id in seen_criterion_ids:
            # Duplicate credit for the same idea is never awarded: the first
            # decision for a criterion wins, later repeats are flagged and dropped.
            flags.append(f"duplicate_criterion_ignored:{crit.criterion_id}")
            logger.warning(
                "Evaluation repeated a criterion id — duplicate dropped",
                criterion_id=crit.criterion_id,
                dropped_marks=crit.proposed_marks,
            )
            continue
        seen_criterion_ids.add(crit.criterion_id)

        marks = crit.proposed_marks
        max_marks = float(concept.maximum_marks)
        if marks < 0:
            flags.append(f"negative_marks_clamped:{crit.criterion_id}")
            marks = 0.0
        elif marks > max_marks:
            flags.append(f"marks_clamped_to_maximum:{crit.criterion_id}")
            logger.warning(
                "Criterion marks exceeded maximum — clamped",
                criterion_id=crit.criterion_id,
                proposed=marks,
                maximum=max_marks,
            )
            marks = max_marks
        if not clamp_marks and crit.proposed_marks > max_marks:
            raise EvaluationValidationError(
                f"Criterion '{crit.criterion_id}' proposed {crit.proposed_marks} > maximum {max_marks}"
            )

        evidence = []
        for ev in crit.student_evidence:
            verified = evidence_exists_in_answer(ev.quote, corpus)
            if not verified:
                flags.append(f"unverified_evidence:{crit.criterion_id}")
                logger.warning(
                    "Evidence quote not found in canonical answer",
                    criterion_id=crit.criterion_id,
                    quote=ev.quote[:80],
                )
            evidence.append(ev.model_copy(update={"verified_in_answer": verified}))

        sanitized.append(
            crit.model_copy(
                update={
                    "criterion": crit.criterion or concept.description,
                    "maximum_marks": max_marks,
                    "proposed_marks": round(marks, 2),
                    "student_evidence": evidence,
                }
            )
        )

    # Required rubric criteria absent from the evaluation are flagged.
    returned_ids = {c.criterion_id for c in sanitized}
    for cid, concept in concept_map.items():
        if cid not in returned_ids and concept.required:
            flags.append(f"missing_criterion:{cid}")

    # Model-recommended review is surfaced as an observable flag (the deterministic
    # risk engine remains the sole authority for routing decisions).
    if (result.review or {}).get("recommended"):
        flags.append("model_review_recommended")

    # Hard invariant (defense in depth): unique criteria with clamped marks can
    # never exceed the question maximum while rubric arithmetic is valid.
    total = round(sum(c.proposed_marks for c in sanitized), 2)
    if total > rubric.maximum_marks + 1e-9:
        raise EvaluationValidationError(
            f"Sanitized criteria total {total} exceeds question maximum {rubric.maximum_marks}",
            details={"question_id": rubric.question_id},
        )

    return result.model_copy(update={"criteria": sanitized, "flags": flags})
