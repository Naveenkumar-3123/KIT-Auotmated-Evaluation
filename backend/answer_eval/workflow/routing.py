"""Conditional edge routing for the evaluation workflow (Module 17)."""

from answer_eval.workflow.state import EvaluationWorkflowState


def route_after_validation(state: EvaluationWorkflowState) -> str:
    if state.get("status") == "failed_permanent":
        return "end_failed"
    return "process_pdf"


def route_after_perception(state: EvaluationWorkflowState) -> str:
    """Retryable failures stop the run; the job system re-enqueues with backoff.

    The checkpointer preserves all completed stage outputs, so the retried run
    resumes from the failed stage instead of redoing expensive work.
    """
    if state.get("status") == "failed_permanent":
        return "end_failed"
    if state.get("status") == "failed_retryable":
        return "end_retry"
    return "continue"


def route_after_grading(state: EvaluationWorkflowState) -> str:
    if state.get("status") in ("failed_permanent", "failed_retryable"):
        return "end_retry" if state.get("status") == "failed_retryable" else "end_failed"
    pending = [qid for qid, g in (state.get("graded_answers") or {}).items() if g.get("review", {}).get("required")]
    return "human_review" if pending else "finalize"


def route_after_review(state: EvaluationWorkflowState) -> str:
    return "finalize"
