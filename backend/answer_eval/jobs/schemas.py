"""Job system schemas (Module 18)."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class JobStatus(StrEnum):
    queued = "queued"
    claimed = "claimed"
    processing = "processing"
    waiting_for_review = "waiting_for_review"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Stage(StrEnum):
    """Detailed progress stages surfaced through the status API."""

    validating = "validating"
    rendering_pdf = "rendering_pdf"
    preprocessing = "preprocessing"
    segmenting = "segmenting"
    ocr = "ocr"
    diagram_analysis = "diagram_analysis"
    reconstructing = "reconstructing"
    applying_rules = "applying_rules"
    evaluating = "evaluating"
    verifying = "verifying"
    calculating_risk = "calculating_risk"
    waiting_for_review = "waiting_for_review"
    finalizing = "finalizing"
    completed = "completed"


class FailureRecord(BaseModel):
    """Retained failure information — failed jobs are never silently discarded."""

    stage: str
    exception_type: str
    message: str
    attempt: int
    timestamp: str = Field(default_factory=utcnow)
    permanent: bool = False


class JobRecord(BaseModel):
    job_id: str
    submission_id: str
    pdf_path: str
    rubrics: dict[str, Any] = Field(default_factory=dict)
    teacher_rules: dict[str, Any] | None = Field(
        default=None,
        description="Resolved per-question teacher rules: {question_id: TeacherQuestionRules.dump}",
    )

    status: JobStatus = JobStatus.queued
    current_stage: str = Stage.validating.value
    progress_total: int = 12
    progress_completed: int = 0

    attempt: int = 1
    max_attempts: int = 3
    worker_id: str | None = None
    lease_expires_at: str | None = None

    created_at: str = Field(default_factory=utcnow)
    started_at: str | None = None
    heartbeat_at: str | None = None
    completed_at: str | None = None
    next_attempt_at: str | None = Field(
        default=None, description="Earliest time a retrying job may be claimed again (backoff)"
    )

    input_hash: str | None = None
    node_skips: int = Field(
        default=0,
        description=(
            "How many times workers released this job because the PDF was not accessible"
            " on their machine (multi-node job-store sharing). Bounded by the worker's"
            " max_node_skips before the job is dead-lettered."
        ),
    )
    input_hash: str | None = None
    result_summary: dict[str, Any] | None = None
    failures: list[FailureRecord] = Field(default_factory=list)
    error: str | None = None
    review_decisions: dict[str, Any] = Field(
        default_factory=dict,
        description="Teacher review decisions applied on resume: {question_id: {approved, final_marks, reviewer_notes}}",
    )
    review_request: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Teacher-facing review payload captured from the LangGraph interrupt while the "
            "job is waiting_for_review: {awaiting_review: {qid: {proposed_marks, maximum_marks, "
            "feedback, reasons}}, instructions: str}"
        ),
    )

    def progress_percent(self) -> int:
        if self.status == JobStatus.completed:
            return 100
        if self.progress_total <= 0:
            return 0
        return min(100, int(100 * self.progress_completed / self.progress_total))
