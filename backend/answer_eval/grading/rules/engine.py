"""Deterministic rule engine (Module 12). PURE PYTHON — no LLM involvement.

Calculates objective facts and enforces hard constraints: word counts, literal
keyword occurrences, mandatory terms, rubric arithmetic, diagram presence,
empty/too-short answers, and bounded strictness-derived penalties.

This module must NEVER perform semantic interpretation (e.g. "the student
understood reliable communication") — that belongs to the evaluation agent.
"""

import re

from answer_eval.agents.ocr.agent import count_words_deterministic
from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.core.logging import get_logger
from answer_eval.grading.rubric import QuestionRubric
from answer_eval.grading.rules.schemas import (
    DeterministicPenalty,
    DiagramFacts,
    KeywordFacts,
    MandatoryTermFacts,
    RubricValidationFacts,
    RuleEvaluationResult,
    TeacherQuestionRules,
    WordCountFacts,
)
from answer_eval.grading.strictness.engine import StrictnessEngine
from answer_eval.grading.strictness.schemas import StrictnessPolicy

logger = get_logger("grading.rules")


def normalize_for_matching(text: str) -> str:
    """Lowercase and collapse whitespace for literal term matching."""
    return re.sub(r"\s+", " ", text.casefold())


def match_literal_terms(text: str, terms: list[str]) -> tuple[list[str], list[str]]:
    """Case-insensitive whole-word literal matching. Returns (matched, missing).

    Deliberately literal: this module reports facts only, never whether a
    concept is "present in spirit".
    """
    if not text or not terms:
        return [], list(terms or [])
    haystack = normalize_for_matching(text)
    matched: list[str] = []
    missing: list[str] = []
    for term in terms:
        needle = normalize_for_matching(term).strip()
        if not needle:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            matched.append(term)
        else:
            missing.append(term)
    return matched, missing


def evaluate_answer(
    answer: CanonicalStructuredAnswer,
    rubric: QuestionRubric,
    policy: StrictnessPolicy,
    teacher_rules: TeacherQuestionRules | None = None,
) -> RuleEvaluationResult:
    """Compute the deterministic RuleEvaluationResult for one canonical answer.

    When ``teacher_rules`` is supplied (resolved per-question policies from the
    Configure flow), ALL penalty amounts come from it — strictness never
    invents deductions (specs #18-#20, #54). Without it the legacy
    strictness-derived fallback applies.
    """
    rubric.validate_rubric()

    raw_text = answer.raw_text or ""
    actual_words = count_words_deterministic(raw_text)
    answer_empty = actual_words == 0

    wc_rule = teacher_rules.word_count if teacher_rules else None

    # Word-count facts. Explicit rubric grace_words overrides policy grace.
    if wc_rule is not None:
        minimum = wc_rule.minimum_words
        effective_minimum = wc_rule.effective_minimum
        grace_words = max(0, minimum - effective_minimum)
    elif rubric.grace_words is not None:
        minimum = rubric.minimum_words
        grace_words = min(rubric.grace_words, minimum)
        effective_minimum = minimum - grace_words
    else:
        grace_words, effective_minimum = StrictnessEngine.effective_minimum_words(policy, rubric.minimum_words)
    within_requirement = actual_words >= effective_minimum
    deficit = max(0, effective_minimum - actual_words)

    keyword_matched, keyword_missing = match_literal_terms(raw_text, rubric.keywords)
    mandatory_matched, mandatory_missing = match_literal_terms(raw_text, rubric.mandatory_terms)

    # Diagram presence comes from Module 10 observations (never graded here).
    diagram_present = any(d.diagram_present for d in answer.diagrams)

    criteria_total = round(sum(c.maximum_marks for c in rubric.expected_concepts), 6)
    rubric_valid = criteria_total <= rubric.maximum_marks + 1e-9 and rubric.maximum_marks > 0

    penalties: list[DeterministicPenalty] = []
    flags: list[str] = []

    # ---- word-count penalty -------------------------------------------------
    if wc_rule is not None:
        marks, shortfall_below_trigger = wc_rule.penalty_for(actual_words)
        if marks > 0 and not answer_empty:
            penalties.append(
                DeterministicPenalty(
                    penalty_type="word_count_teacher",
                    marks=marks,
                    reason=(
                        f"Teacher rule v{teacher_rules.version}: {actual_words} words is below the trigger "
                        f"threshold {effective_minimum} (minimum {minimum}, shortfall grace "
                        f"{wc_rule.trigger_shortfall_words}); mode={wc_rule.mode}; -{marks} marks."
                    ),
                )
            )
            flags.append("word_count_teacher_penalty")
    elif deficit > 0 and not answer_empty and rubric.minimum_words > 0:
        # Legacy fallback: bounded strictness-derived penalty.
        proportional = rubric.maximum_marks * (deficit / max(rubric.minimum_words, 1))
        capped = min(proportional, policy.max_word_count_penalty(rubric.maximum_marks))
        penalty = round(capped, 2)
        if penalty > 0:
            penalties.append(
                DeterministicPenalty(
                    penalty_type="word_count_deficit",
                    marks=penalty,
                    reason=(
                        f"Answer is {deficit} words below the effective minimum "
                        f"({actual_words}/{effective_minimum}); grace {grace_words} words; "
                        f"penalty capped at {policy.max_word_count_penalty(rubric.maximum_marks)} marks."
                    ),
                )
            )

    # ---- missing-diagram penalty (teacher-configured, spec #22/#38) --------
    diagram_rule = teacher_rules.diagram if teacher_rules else None
    if diagram_rule is not None:
        present_diagrams = sum(1 for d in answer.diagrams if d.diagram_present)
        missing_marks = diagram_rule.missing_penalty(present_diagrams)
        if missing_marks > 0:
            required_count = max(diagram_rule.minimum_diagrams, 1 if diagram_rule.required else 0)
            penalties.append(
                DeterministicPenalty(
                    penalty_type="missing_diagram",
                    marks=missing_marks,
                    reason=(
                        f"{present_diagrams}/{required_count} required diagram(s) present; "
                        f"fixed missing-ordinal deduction -{missing_marks} marks "
                        "(applied once — no additional semantic absence penalty)."
                    ),
                )
            )

    # ---- terminology / mandatory terms -------------------------------------
    if mandatory_missing:
        term_rule = teacher_rules.terminology if teacher_rules else None
        enforce = term_rule.enforce_mandatory_terms if term_rule else policy.terminology.enforce_mandatory_terms
        if enforce:
            if term_rule is not None and term_rule.marks_deducted is not None:
                capped = round(min(term_rule.marks_deducted, rubric.maximum_marks), 2)
                basis = "teacher-configured"
            else:
                capped = policy.max_mandatory_term_penalty(rubric.maximum_marks)
                basis = "strictness-capped"
            if capped > 0:
                penalties.append(
                    DeterministicPenalty(
                        penalty_type="mandatory_terms_missing",
                        marks=capped,
                        reason=f"Missing mandatory term(s): {', '.join(mandatory_missing)} ({basis} deduction).",
                    )
                )

    if answer_empty:
        flags.append("answer_empty")
    if deficit > 0 and not answer_empty and rubric.minimum_words > 0:
        flags.append("answer_too_short")
    if rubric.diagram.required and not diagram_present:
        flags.append("diagram_required_missing")
    if not rubric_valid:
        flags.append("invalid_rubric_arithmetic")

    result = RuleEvaluationResult(
        question_id=rubric.question_id,
        answer_empty=answer_empty,
        answer_too_short="answer_too_short" in flags,
        word_count=WordCountFacts(
            actual=actual_words,
            minimum=rubric.minimum_words,
            grace_words=grace_words,
            effective_minimum=effective_minimum,
            within_requirement=within_requirement,
            deficit=deficit,
        ),
        keywords=KeywordFacts(matched=keyword_matched, missing_optional=keyword_missing),
        mandatory_terms=MandatoryTermFacts(matched=mandatory_matched, missing=mandatory_missing),
        diagram=DiagramFacts(required=rubric.diagram.required, present=diagram_present),
        rubric_validation=RubricValidationFacts(
            criteria_total=criteria_total,
            question_maximum=rubric.maximum_marks,
            valid=rubric_valid,
        ),
        deterministic_penalties=penalties,
        flags=flags,
    )

    logger.info(
        "[RULES]",
        question_id=rubric.question_id,
        words=actual_words,
        effective_minimum=effective_minimum,
        keyword_hits=len(keyword_matched),
        mandatory_missing=len(mandatory_missing),
        penalties=result.total_deterministic_penalty,
        flags=flags,
    )
    return result
