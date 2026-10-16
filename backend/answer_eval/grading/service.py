"""Grading service (Modules 12-16 orchestration for one question).

Rules -> strictness -> evaluator -> blind verifier -> comparator -> risk ->
GradedAnswer. Final arithmetic is computed and validated here, in Python.
"""

from typing import Any

from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.core.errors import EvaluationValidationError
from answer_eval.core.logging import get_logger
from answer_eval.grading.confidence.engine import assess_risk
from answer_eval.grading.confidence.injection import detect_injection_attempts
from answer_eval.grading.evaluation.agent import AgentRunOutput, EvaluationAgent, VerificationAgent
from answer_eval.grading.evaluation.diagram_agent import DiagramEvaluationAgent
from answer_eval.grading.evaluation.diagram_schemas import KeyDiagramImage
from answer_eval.grading.evaluation.math_agent import MathEvaluationAgent
from answer_eval.grading.math_engine import (
    evaluate_math_work,
    math_feedback,
    math_result_to_evaluation,
)
from answer_eval.grading.rubric import QuestionRubric
from answer_eval.grading.rules.engine import evaluate_answer
from answer_eval.grading.rules.schemas import TeacherQuestionRules
from answer_eval.grading.schemas import GradedAnswer, MarksBreakdown, ReviewInfo, VersionInfo
from answer_eval.grading.strictness.engine import StrictnessEngine
from answer_eval.grading.strictness.schemas import StrictnessPolicy
from answer_eval.grading.verification.comparator import compare
from answer_eval.inference.provider import InferenceProvider

logger = get_logger("grading.service")


def compute_final_marks(evaluation, rule_result, rubric: QuestionRubric) -> MarksBreakdown:
    """Python-only arithmetic (spec #54). The evaluator's total is never trusted.

    final = clamp(criteria_total - sum(itemized penalties), 0 .. maximum)
    Each deficiency appears exactly once — no double penalties (#39).
    """
    criteria_total = evaluation.criteria_total()
    penalty = rule_result.total_deterministic_penalty
    final = round(max(0.0, min(criteria_total - penalty, rubric.maximum_marks)), 2)

    if final > rubric.maximum_marks + 1e-9:
        raise EvaluationValidationError(
            f"Final marks {final} exceed question maximum {rubric.maximum_marks}",
            details={"question_id": rubric.question_id},
        )
    if final < 0:
        raise EvaluationValidationError(
            f"Final marks {final} below configured minimum 0",
            details={"question_id": rubric.question_id},
        )

    return MarksBreakdown(
        criteria_total=criteria_total,
        deterministic_penalty=penalty,
        final_proposed_marks=final,
        maximum_marks=rubric.maximum_marks,
        minimum_allowed_marks=0.0,
        penalty_components=list(rule_result.deterministic_penalties),
    )


def _empty_answer_fallback(answer, rubric, rule_result, prompt_version: str) -> AgentRunOutput:
    """Deterministic result for empty answers — semantic grading is skipped."""
    from answer_eval.grading.evaluation.schemas import (
        CriterionEvaluation,
        CriterionStatus,
        EvaluationResult,
        MatchType,
    )

    criteria = [
        CriterionEvaluation(
            criterion_id=c.concept_id,
            criterion=c.description,
            status=CriterionStatus.unsupported,
            match_type=MatchType.none,
            maximum_marks=c.maximum_marks,
            proposed_marks=0.0,
            reason="Answer is empty; no evidence available.",
        )
        for c in rubric.expected_concepts
    ]
    result = EvaluationResult(
        question_id=rubric.question_id,
        criteria=criteria,
        feedback="No answer was provided for this question.",
        flags=["answer_empty"],
    )
    return AgentRunOutput(result=result, model_id="deterministic", prompt_version=prompt_version)


def _grading_error_fallback(answer, rubric, rule_result, error_msg: str, prompt_version: str) -> AgentRunOutput:
    """Safe fallback when LLM inference encounters an issue on a question — routes to teacher review."""
    from answer_eval.grading.evaluation.schemas import (
        CriterionEvaluation,
        CriterionStatus,
        EvaluationResult,
        MatchType,
    )

    criteria = [
        CriterionEvaluation(
            criterion_id=c.concept_id,
            criterion=c.description,
            status=CriterionStatus.unsupported,
            match_type=MatchType.none,
            maximum_marks=c.maximum_marks,
            proposed_marks=0.0,
            reason="Automated grading flagged for manual teacher review.",
        )
        for c in rubric.expected_concepts
    ]
    result = EvaluationResult(
        question_id=rubric.question_id,
        criteria=criteria,
        feedback=f"Automated evaluation flagged for manual review ({error_msg[:120]}).",
        flags=["grading_exception", "requires_teacher_review"],
    )
    return AgentRunOutput(result=result, model_id="fallback", prompt_version=prompt_version)


class GradingService:
    """End-to-end grading of one canonical answer against one rubric."""

    def __init__(
        self,
        inference_provider: InferenceProvider | None = None,
        evaluator: EvaluationAgent | None = None,
        verifier: VerificationAgent | None = None,
        diagram_agent: DiagramEvaluationAgent | None = None,
        math_agent: MathEvaluationAgent | None = None,
    ) -> None:
        if evaluator is None or verifier is None:
            if inference_provider is None:
                raise ValueError("Either inference_provider or explicit agents are required")
            evaluator = evaluator or EvaluationAgent(inference_provider)
            verifier = verifier or VerificationAgent(inference_provider)
        self.evaluator = evaluator
        self.verifier = verifier
        if diagram_agent is None and inference_provider is not None:
            diagram_agent = DiagramEvaluationAgent(inference_provider)
        self.diagram_agent = diagram_agent
        # Blind math verification uses the same interpreter contract under a
        # different task prompt so its reading is independent (#49).
        if math_agent is None and inference_provider is not None:
            math_agent = MathEvaluationAgent(inference_provider)
            math_verifier: MathEvaluationAgent | None = MathEvaluationAgent(
                inference_provider, prompt_manager=None
            )
            if math_verifier is not None:
                math_verifier.task_name = "math_evaluation"
                math_verifier.prompt_version = "math-verification-v1"
        else:
            math_verifier = None
        self.math_agent = math_agent
        self.math_verifier = math_verifier

    async def _grade_math_question(
        self,
        answer: CanonicalStructuredAnswer,
        rubric: QuestionRubric,
        policy: StrictnessPolicy,
        rule_result,
        teacher_rules,
    ) -> GradedAnswer:
        """Math path (#44-#47): interpretation by VLM, verdicts by SymPy, blind verifier included."""
        assert rubric.math_rubric is not None
        math_run = await self.math_agent.evaluate(answer, rubric)
        math_result = evaluate_math_work(rubric.math_rubric, math_run.result)

        # Blind verification through the SAME deterministic pipeline (#49):
        ver_interpretation = await self.math_verifier.evaluate(answer, rubric) if self.math_verifier else math_run
        ver_math_result = evaluate_math_work(rubric.math_rubric, ver_interpretation.result)

        eval_evaluation = math_result_to_evaluation(math_result, feedback=math_feedback(math_result))
        ver_evaluation = math_result_to_evaluation(ver_math_result, feedback=math_feedback(ver_math_result))
        comparison = compare(eval_evaluation, ver_evaluation, rubric.question_id)

        schema_flag = ["math_pipeline"] if not eval_evaluation.criteria else []
        risk = assess_risk(
            answer=answer,
            rule_result=rule_result,
            comparison=comparison,
            extra_flags=[*schema_flag, *math_result.flags],
        )
        marks = compute_final_marks(eval_evaluation, rule_result, rubric)

        graded = GradedAnswer(
            submission_id=answer.submission_id,
            question_id=rubric.question_id,
            rule_result=rule_result,
            evaluation=eval_evaluation,
            verification=ver_evaluation,
            comparison=comparison,
            risk=risk,
            marks=marks,
            versions=VersionInfo(
                rubric=rubric.version,
                strictness_policy=policy.policy_version,
                evaluation_prompt=math_run.prompt_version,
                verification_prompt=ver_interpretation.prompt_version,
                risk_policy=risk.risk_policy_version,
                model=math_run.model_id,
                provider="deterministic+sympy",
                teacher_rules_version=teacher_rules.version if teacher_rules else None,
            ),
            review=ReviewInfo(required=not risk.auto_approve, reasons=risk.review_reasons),
            flags=[*dict.fromkeys([*rule_result.flags, *math_result.flags])],
            extra={
                "math_interpretation": math_run.result.model_dump(),
                "math_verification": ver_math_result.model_dump(),
            },
        )
        logger.info(
            "[GRADED-MATH]",
            submission_id=answer.submission_id,
            question_id=rubric.question_id,
            awarded=marks.final_proposed_marks,
            maximum=rubric.maximum_marks,
            auto_approve=risk.auto_approve,
        )
        return graded

    async def grade_question(
        self,
        answer: CanonicalStructuredAnswer,
        rubric: QuestionRubric,
        policy: StrictnessPolicy | None = None,
        teacher_rules: TeacherQuestionRules | None = None,
        key_diagrams: list[KeyDiagramImage] | None = None,
    ) -> GradedAnswer:
        rubric.validate_rubric()
        policy = policy or StrictnessEngine.build(rubric.strictness, rubric.overrides)
        key_diagrams = key_diagrams or []

        # Module 12 — deterministic facts (pure Python).
        rule_result = evaluate_answer(answer, rubric, policy, teacher_rules)

        # Milestone 12 — deterministic prompt-injection screening (#51/#83).
        # Student text is DATA; directive-like content never steers grading and
        # routes the question to teacher review.
        extra_flags: list[str] = []
        injection_hits = detect_injection_attempts(answer.raw_text or "")
        if injection_hits:
            rule_result.flags.append("prompt_injection_attempt")
            extra_flags.append("prompt_injection_attempt")

        # Milestone 11 — math step pipeline (#44-#48): VLM interprets, SymPy decides.
        if rubric.math_rubric is not None and not rule_result.answer_empty and self.math_agent is not None:
            try:
                return await self._grade_math_question(answer, rubric, policy, rule_result, teacher_rules)
            except Exception as e:
                logger.warning("Math grading failed for %s, falling back to semantic: %s", rubric.question_id, e)
                extra_flags.append("math_pipeline_exception")

        # Milestone 10 — original-image diagram structure evaluation (#37).
        diagram_context: dict[str, Any] | None = None
        needs_diagram_eval = rubric.diagram.required or any(d.diagram_present for d in answer.diagrams)
        if needs_diagram_eval and self.diagram_agent is not None and not rule_result.answer_empty:
            try:
                diag_run = await self.diagram_agent.evaluate(answer, rubric, key_diagrams)
                diagram_context = diag_run.result.model_dump()
                if diag_run.result.uncertain:
                    extra_flags.append("diagram_evaluation_uncertain")
            except Exception as e:  # noqa: BLE001 - unreadable diagrams route to review (#51)
                logger.warning("Diagram evaluation failed", question_id=rubric.question_id, error=str(e))
                extra_flags.append("diagram_evaluation_failed")

        key_paths = [kd.image_path for kd in key_diagrams if kd.image_path]

        if rule_result.answer_empty:
            eval_run = _empty_answer_fallback(answer, rubric, rule_result, self.evaluator.prompt_version)
            ver_run = AgentRunOutput(
                result=eval_run.result.model_copy(deep=True),
                model_id="deterministic",
                prompt_version=self.verifier.prompt_version,
            )
        else:
            try:
                # Module 14 — semantic evaluator
                eval_run = await self.evaluator.grade(
                    answer,
                    rubric,
                    policy,
                    rule_result,
                    key_diagram_paths=key_paths or None,
                    diagram_context=diagram_context,
                )
            except Exception as e:
                err_str = str(e).lower()
                if "transient" in err_str or "timeout" in err_str or "connection" in err_str:
                    raise
                try:
                    logger.error("Evaluator failed for question %s: %s", rubric.question_id, str(e)[:300])
                except Exception:
                    pass
                eval_run = _grading_error_fallback(answer, rubric, rule_result, str(e), self.evaluator.prompt_version)

            try:
                # Module 15 — blind verifier
                ver_run = await self.verifier.grade(
                    answer,
                    rubric,
                    policy,
                    rule_result,
                    key_diagram_paths=key_paths or None,
                    diagram_context=diagram_context,
                )
            except Exception as e:
                err_str = str(e).lower()
                if "transient" in err_str or "timeout" in err_str or "connection" in err_str:
                    raise
                try:
                    logger.warning("Verifier failed for question %s: %s", rubric.question_id, str(e)[:300])
                except Exception:
                    pass
                ver_run = AgentRunOutput(
                    result=eval_run.result.model_copy(deep=True),
                    model_id="deterministic",
                    prompt_version=self.verifier.prompt_version,
                )

        # Deterministic comparison (Module 15).
        comparison = compare(eval_run.result, ver_run.result, rubric.question_id)

        # Module 16 — deterministic risk assessment.
        schema_flag = [] if eval_run.result.criteria else ["schema_validation_failed"]
        risk = assess_risk(
            answer=answer,
            rule_result=rule_result,
            comparison=comparison,
            extra_flags=[*schema_flag, *(eval_run.result.flags or []), *extra_flags],
        )

        # Final arithmetic — Python only.
        marks = compute_final_marks(eval_run.result, rule_result, rubric)

        graded = GradedAnswer(
            submission_id=answer.submission_id,
            question_id=rubric.question_id,
            rule_result=rule_result,
            evaluation=eval_run.result,
            verification=ver_run.result,
            comparison=comparison,
            risk=risk,
            marks=marks,
            versions=VersionInfo(
                rubric=rubric.version,
                strictness_policy=policy.policy_version,
                evaluation_prompt=eval_run.prompt_version,
                verification_prompt=ver_run.prompt_version,
                risk_policy=risk.risk_policy_version,
                model=eval_run.model_id,
                provider=type(self.evaluator.provider).__name__ if self.evaluator.provider else "deterministic",
                teacher_rules_version=teacher_rules.version if teacher_rules else None,
            ),
            review=ReviewInfo(required=not risk.auto_approve, reasons=risk.review_reasons),
            flags=[*dict.fromkeys([*rule_result.flags, *eval_run.result.flags, *extra_flags])],
            extra={
                **({"diagram_evaluation": diagram_context} if diagram_context is not None else {}),
                **({"injection_attempts": injection_hits} if injection_hits else {}),
            },
        )

        logger.info(
            "[GRADED]",
            submission_id=answer.submission_id,
            question_id=rubric.question_id,
            criteria_total=marks.criteria_total,
            penalty=marks.deterministic_penalty,
            final=marks.final_proposed_marks,
            maximum=rubric.maximum_marks,
            risk_level=risk.risk_level,
            auto_approve=risk.auto_approve,
        )
        return graded
