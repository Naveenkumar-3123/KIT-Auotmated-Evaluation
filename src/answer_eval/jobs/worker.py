"""Evaluation worker (Module 18).

Claim -> lease -> heartbeat -> run LangGraph -> update progress -> save result.
Dead workers lose their lease; expired leases are reclaimed and retried by any
live worker. Failures are classified retryable/permanent; permanent failures and
exhausted retries are retained in the durable store (dead-letter state).
"""

import os
import threading
import uuid
from collections.abc import Callable
from typing import Any

from answer_eval.core.errors import PermanentJobError
from answer_eval.core.logging import get_logger
from answer_eval.jobs.retry import RetryPolicy, is_retryable
from answer_eval.jobs.schemas import FailureRecord, JobRecord, JobStatus, Stage, utcnow

logger = get_logger("jobs.worker")


def _interrupted_for_review(result: dict[str, Any]) -> bool:
    return bool(result.get("__interrupt__"))


def _review_request_from(result: dict[str, Any]) -> dict[str, Any]:
    """Extract the teacher-facing review payload from a LangGraph interrupt.

    ``interrupt()`` receives ``{"awaiting_review": {...}, "instructions": ...}``;
    the invoke result surfaces it via the ``__interrupt__`` entries' ``value``.
    """
    interrupts = result.get("__interrupt__") or []
    for item in interrupts:
        value = getattr(item, "value", item)
        if isinstance(value, dict) and value.get("awaiting_review"):
            return value
    if result.get("status") == "awaiting_review":
        return {"awaiting_review": result.get("awaiting_review") or {}}
    return {}


def _first_error_message(result: dict[str, Any]) -> str:
    errors = result.get("errors") or []
    if errors:
        last = errors[-1]
        return f"[{last.get('node')}] {last.get('message')}"
    return "Workflow reported failure without details"


class EvaluationWorker:
    def __init__(
        self,
        store,
        queue,
        graph_factory: Callable[[], Any],
        worker_id: str | None = None,
        lease_seconds: float = 300.0,
        heartbeat_interval_s: float = 15.0,
        poll_interval_s: float = 0.2,
        retry_policy: RetryPolicy | None = None,
        initial_state_hook: Callable[[dict], dict] | None = None,
        max_node_skips: int = 10,
    ) -> None:
        self.store = store
        self.queue = queue
        self.graph_factory = graph_factory
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_s = heartbeat_interval_s
        self.poll_interval_s = poll_interval_s
        self.retry_policy = retry_policy or RetryPolicy()
        # Multi-node safety: several machines can share one durable job store
        # (same DATABASE_URL). A claimed job whose pdf_path does not exist on
        # THIS machine is likely owned by another node — release it back to the
        # queue instead of running it into a permanent "PDF not found" failure.
        # After max_node_skips releases with no node able to access the file,
        # the job is dead-lettered with a clear error.
        self.max_node_skips = max_node_skips
        # Optional hook to enrich/override the initial workflow state (e.g. tests
        # injecting pre-computed canonical answers, or resuming from artifacts).
        self.initial_state_hook = initial_state_hook
        self._stop = threading.Event()
        # Review decisions captured when a teacher resolves a waiting job.
        self.review_decisions: dict[str, dict] = {}

    def stop(self) -> None:
        self._stop.set()

    def reclaim(self) -> int:
        return self.store.reclaim_expired_leases()

    def run_once(self) -> JobRecord | None:
        """Single claim-execute cycle."""
        job_id = self.queue.dequeue(timeout_s=self.poll_interval_s)
        job: JobRecord | None = None
        if job_id:
            job = self.store.get_job(job_id)
            if job is None or job.status not in (
                JobStatus.claimed.value,
                JobStatus.queued.value,
                JobStatus.retrying.value,
            ):
                return None
        else:
            # Redis/in-memory queue empty. Single-node fallback: claim directly
            # from the durable store (Postgres) so one PC without Redis can run
            # the whole pipeline (API + worker share the same job store).
            self.reclaim()
            claim = getattr(self.store, "claim_next_job", None)
            if callable(claim):
                job = claim(self.worker_id, self.lease_seconds)

        if job is None:
            return None

        # Multi-node guard: if the PDF is not accessible on this machine, the
        # job very likely belongs to another node sharing this job store.
        # Release it (bounded) instead of permanently failing it.
        if job.pdf_path and not os.path.isfile(job.pdf_path):
            return self._release_unrunnable(job)

        job = self.store.update_job(
            job.job_id,
            status=JobStatus.processing,
            current_stage=Stage.validating.value,
            worker_id=self.worker_id,
            started_at=job.started_at or utcnow(),
        )
        assert job is not None

        # Mirror into the submissions table so the UI status endpoint shows this
        # paper as processing (not stuck in 'queued').
        mark = getattr(self.store, "mark_submission", None)
        if callable(mark):
            try:
                mark(job.submission_id, "processing")
            except Exception:  # noqa: BLE001 - UI mirroring is best-effort
                logger.warning("mark_submission failed", submission_id=job.submission_id)

        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(job.job_id, heartbeat_stop), daemon=True)
        heartbeat_thread.start()
        try:
            self._execute(job)
        except Exception as exc:
            logger.warning(
                "Job execution failed",
                job_id=job.job_id,
                attempt=job.attempt,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            self._handle_failure(job, exc)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)

        return self.store.get_job(job.job_id)

    def run_forever(self) -> None:  # pragma: no cover - long-running loop
        logger.info("Worker started", worker_id=self.worker_id)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as e:  # never let the loop die
                logger.error("Worker loop error", worker_id=self.worker_id, error=str(e))
                import time

                time.sleep(1.0)

    def _release_unrunnable(self, job: JobRecord) -> JobRecord | None:
        """Put a claimed job back because its PDF is missing on this machine.

        The release does NOT consume a retry attempt and is bounded by
        ``max_node_skips``: once exceeded, the job is dead-lettered as a
        permanent failure (no node could access the file).
        """
        skips = job.node_skips + 1
        if skips > self.max_node_skips:
            logger.error(
                "Job dead-lettered: PDF never became accessible on any worker node",
                job_id=job.job_id,
                submission_id=job.submission_id,
                pdf_path=job.pdf_path,
                skips=skips,
            )
            self._handle_failure(
                job,
                PermanentJobError(
                    f"[validate_submission] PDF not accessible from any worker node "
                    f"after {skips} attempts: {job.pdf_path}"
                ),
            )
            return self.store.get_job(job.job_id)

        delay = min(self.retry_policy.delay_for_attempt(1), 5.0)
        # NOTE: deliberately NOT re-enqueued on the (process-local) queue — the
        # delay is enforced by next_attempt_at, which the store-level claim
        # fallback respects. Local in-memory queues ignore that delay.
        self.store.update_job(
            job.job_id,
            status=JobStatus.queued,
            worker_id=None,
            lease_expires_at=None,
            next_attempt_at=self.retry_policy.next_attempt_at(1),
            node_skips=skips,
        )
        mark = getattr(self.store, "mark_submission", None)
        if callable(mark):
            try:
                mark(job.submission_id, "queued")
            except Exception:  # noqa: BLE001 - UI mirroring is best-effort
                logger.warning("mark_submission failed", submission_id=job.submission_id)
        logger.warning(
            "Job released: PDF not accessible on this node — another node may own the file",
            job_id=job.job_id,
            submission_id=job.submission_id,
            pdf_path=job.pdf_path,
            worker_id=self.worker_id,
            skip=skips,
            retry_in_s=round(delay, 2),
        )
        return None

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval_s):
            self.store.update_job(job_id, heartbeat_at=utcnow())

    def _execute(self, job: JobRecord) -> None:
        from langgraph.types import Command

        app = self.graph_factory()
        config = {"configurable": {"thread_id": job.job_id}}
        existing = app.get_state(config)

        if existing and existing.next:
            # Interrupted for human review -> resume with teacher decisions.
            result = app.invoke(Command(resume=job.review_decisions or {}), config=config)
        elif existing and existing.values and existing.values.get("status") in ("failed_retryable", "running"):
            state = dict(existing.values)
            state["status"] = "running"  # resume from checkpoint after a retryable failure
            result = app.invoke(state, config=config)
        else:
            from answer_eval.workflow.graph import initial_state

            inputs = initial_state(
                job.job_id,
                job.submission_id,
                job.pdf_path,
                job.rubrics,
                teacher_rules=job.teacher_rules,
            )
            if job.review_decisions:
                # Checkpointer may have been lost across restarts; re-supplying
                # the teacher's decisions lets human_review_gate apply them
                # without a second interrupt.
                inputs["review_decisions"] = dict(job.review_decisions)
            if self.initial_state_hook:
                inputs = self.initial_state_hook(dict(inputs))
            result = app.invoke(inputs, config=config)

        if result.get("status") == "awaiting_review" or _interrupted_for_review(result):
            self.store.update_job(
                job.job_id,
                status=JobStatus.waiting_for_review,
                current_stage=Stage.waiting_for_review.value,
                review_request=_review_request_from(result),
            )
            mark = getattr(self.store, "mark_submission", None)
            if callable(mark):
                try:
                    mark(job.submission_id, "waiting_for_review")
                except Exception:  # noqa: BLE001
                    logger.warning("mark_submission failed", submission_id=job.submission_id)
            logger.info("Job awaiting teacher review", job_id=job.job_id)
            return

        if str(result.get("status", "")).startswith("failed"):
            errors = result.get("errors") or []
            last_retryable = bool(errors and errors[-1].get("retryable", False))
            if last_retryable:
                from answer_eval.core.errors import RetryableJobError

                raise RetryableJobError(_first_error_message(result))
            raise PermanentJobError(_first_error_message(result))

        summary = result.get("result_summary") or {}
        total = result.get("progress_total") or 12
        # A successful workflow MUST have graded at least one question. An empty
        # summary means perception/grading produced nothing (e.g. zero questions
        # mapped from the scanned sheet) — surface it as a clear failure instead
        # of silently marking the paper "completed" with 0 marks / 0 questions.
        if isinstance(summary.get("questions"), dict) and not summary["questions"]:
            raise PermanentJobError(
                "Evaluation completed but 0 questions were graded — check the "
                "answer-key question mapping and scanned-sheet perception output."
            )
        self.store.update_job(
            job.job_id,
            status=JobStatus.completed,
            current_stage=Stage.completed.value,
            progress_completed=total,
            completed_at=utcnow(),
            result_summary=summary,
            error=None,
        )
        self.store.save_result(job.submission_id, summary)
        persist = getattr(self.store, "persist_results", None)
        if callable(persist):
            try:
                persist(job.submission_id, summary)
            except Exception:  # noqa: BLE001 - persistence must never break grading
                logger.warning("persist_results failed", submission_id=job.submission_id, exc_info=True)
        self._persist_perception(job, result)
        mark = getattr(self.store, "mark_submission", None)
        if callable(mark):
            try:
                mark(job.submission_id, "completed")
            except Exception:  # noqa: BLE001
                logger.warning("mark_submission failed", submission_id=job.submission_id)
        logger.info("Job completed", job_id=job.job_id, submission_id=job.submission_id)

    def _persist_perception(self, job: JobRecord, final_state: dict) -> None:
        """Persist pages/spans/regions/OCR for the Processing-Details evidence view.

        Best-effort: runs after grading is durable and never raises.
        """
        if not isinstance(final_state, dict) or not (
            final_state.get("page_records") or final_state.get("region_records")
        ):
            return
        pool = getattr(self.store, "pool", None)
        run_coro = getattr(self.store, "run_coro", None)
        if pool is None or run_coro is None:
            logger.warning(
                "No DB loop/pool on job store; skipping perception persistence",
                submission_id=job.submission_id,
            )
            return
        try:
            import os

            from answer_eval.jobs.perception_persist import persist_perception
            from answer_eval.storage import LocalStorageProvider

            storage_root = os.getenv("STORAGE_LOCAL_ROOT", "data/storage")
            storage = LocalStorageProvider(storage_root)
            persist_perception(
                job.submission_id, final_state, storage, run_coro=run_coro, pool=pool
            )
        except Exception:  # noqa: BLE001 - evidence must never break grading
            logger.warning(
                "persist_perception setup failed",
                submission_id=job.submission_id,
                exc_info=True,
            )

    def _handle_failure(self, job: JobRecord, exc: Exception) -> None:
        retryable = is_retryable(exc) and not isinstance(exc, PermanentJobError)
        failure = FailureRecord(
            stage=job.current_stage,
            exception_type=type(exc).__name__,
            message=str(exc)[:500],
            attempt=job.attempt,
            permanent=not retryable,
        )
        record = self.store.get_job(job.job_id)
        attempts_so_far = max(record.attempt if record else 1, job.attempt)

        if retryable and not self.retry_policy.attempts_exhausted(attempts_so_far):
            delay = self.retry_policy.delay_for_attempt(attempts_so_far)
            self.store.update_job(
                job.job_id,
                status=JobStatus.retrying,
                attempt=attempts_so_far + 1,
                next_attempt_at=self.retry_policy.next_attempt_at(attempts_so_far),
                failures=[*(record.failures if record else []), failure],
                error=f"{type(exc).__name__}: {exc}"[:500],
            )

            self.queue.requeue(job.job_id, delay_s=min(delay, 5.0))
            logger.info(
                "Job scheduled for retry",
                job_id=job.job_id,
                next_attempt=attempts_so_far + 1,
                backoff_s=round(delay, 2),
            )
        else:
            # Dead-letter: retained durably with full failure context.
            self.store.update_job(
                job.job_id,
                status=JobStatus.failed,
                completed_at=utcnow(),
                failures=[*(record.failures if record else []), failure],
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            logger.error(
                "Job moved to dead-letter (failed) state — retained for inspection",
                job_id=job.job_id,
                attempts=attempts_so_far,
                permanent=not retryable,
            )
            mark = getattr(self.store, "mark_submission", None)
            if callable(mark):
                try:
                    mark(job.submission_id, "failed", detail=str(exc)[:300])
                except Exception:  # noqa: BLE001
                    logger.warning("mark_submission failed", submission_id=job.submission_id)
