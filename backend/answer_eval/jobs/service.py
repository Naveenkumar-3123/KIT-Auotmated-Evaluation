"""Job service (Module 18): the boundary used by the API and worker processes.

submit()  -> durable job record + enqueue, returns immediately
status()  -> job progress for polling
result()  -> final grading summary (no raw model reasoning is ever exposed)
resume()  -> apply teacher review decisions; job re-enters the queue
"""

import uuid
from typing import Any

from answer_eval.core.errors import JobError
from answer_eval.core.logging import get_logger
from answer_eval.jobs.retry import DEFAULT_RETRY_POLICY
from answer_eval.jobs.schemas import JobRecord, JobStatus, Stage

logger = get_logger("jobs.service")


class EvaluationJobService:
    def __init__(self, store, queue) -> None:
        self.store = store
        self.queue = queue

    def submit(
        self,
        submission_id: str,
        pdf_path: str,
        rubrics: dict[str, Any],
        max_attempts: int | None = None,
        teacher_rules: dict[str, Any] | None = None,
    ) -> tuple[JobRecord, bool]:
        """Create a durable job record and enqueue it. Idempotent per active submission."""
        job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
        record = JobRecord(
            job_id=job_id,
            submission_id=submission_id,
            pdf_path=pdf_path,
            rubrics=rubrics,
            teacher_rules=teacher_rules,
            max_attempts=max_attempts or DEFAULT_RETRY_POLICY.max_attempts,
            input_hash=None,
        )
        created, ok = self.store.create_job(record)
        if ok:
            self.queue.enqueue(created.job_id)
            logger.info("Job enqueued", job_id=created.job_id, submission_id=submission_id)
        else:
            logger.info(
                "Duplicate submit ignored — active job already exists",
                job_id=created.job_id,
                submission_id=submission_id,
                status=created.status.value,
            )
        return created, ok

    def status(self, job_id: str) -> dict[str, Any] | None:
        job = self.store.get_job(job_id)
        if job is None:
            return None
        return {
            "job_id": job.job_id,
            "submission_id": job.submission_id,
            "status": job.status.value if isinstance(job.status, JobStatus) else str(job.status),
            "stage": job.current_stage,
            "progress": {"completed": job.progress_completed, "total": job.progress_total},
            "progress_percent": job.progress_percent(),
            "attempt": job.attempt,
            "worker_id": job.worker_id,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "heartbeat_at": job.heartbeat_at,
            "error": job.error,
        }

    def result(self, submission_id: str) -> dict[str, Any] | None:
        return self.store.get_result(submission_id)

    def resume_after_review(self, job_id: str, decisions: dict[str, Any]) -> JobRecord:
        """Apply teacher decisions to a waiting job and put it back in the queue."""
        job = self.store.get_job(job_id)
        if job is None:
            raise JobError(f"Unknown job '{job_id}'")
        if job.status != JobStatus.waiting_for_review:
            raise JobError(f"Job '{job_id}' is not waiting for review (status={job.status})")
        updated = self.store.update_job(job_id, review_decisions=decisions, status=JobStatus.queued)
        assert updated is not None
        self.queue.enqueue(job_id)
        logger.info("Job resumed after human review", job_id=job_id, questions=list(decisions))
        return updated

    def cancel(self, job_id: str) -> JobRecord | None:
        job = self.store.get_job(job_id)
        if job is None or job.status not in _CANCELLABLE:
            return job
        return self.store.update_job(job_id, status=JobStatus.cancelled, completed_at=Stage.completed.value)


_CANCELLABLE = {JobStatus.queued, JobStatus.retrying, JobStatus.waiting_for_review}
