"""Integration tests for Module 18: durable store, queue, leases, retries, worker.

Runs REAL workers against the REAL compiled LangGraph graph with a scripted
fake inference provider (orchestration integration-tested; model calls faked).
"""

import json

import pytest

from answer_eval.core.errors import InferenceTimeoutError
from answer_eval.jobs.queue import InMemoryQueue
from answer_eval.jobs.retry import RetryPolicy
from answer_eval.jobs.schemas import JobStatus
from answer_eval.jobs.service import EvaluationJobService
from answer_eval.jobs.store import InMemoryJobStore
from answer_eval.jobs.worker import EvaluationWorker
from tests.unit.test_workflow_graph import GOOD_EVAL, make_graph


def failing_once_provider():
    """Provider whose FIRST infer_structured call times out (transient failure)."""
    from tests.unit.test_workflow_graph import FakeStructuredProvider

    class FlakyProvider(FakeStructuredProvider):
        def __init__(self, responses):
            super().__init__(responses)
            self.calls = 0

        async def infer_structured(self, request, schema, max_retries=2):
            self.calls += 1
            if self.calls == 1:
                raise InferenceTimeoutError("simulated transient inference timeout")
            return await super().infer_structured(request, schema, max_retries)

    return FlakyProvider([json.loads(json.dumps(GOOD_EVAL))] * 2)


RUBRIC = {
    "question_id": "Q4",
    "maximum_marks": 10,
    "expected_concepts": [
        {"concept_id": "C1", "description": "Connection-oriented communication", "maximum_marks": 5},
        {"concept_id": "C2", "description": "Acknowledgement mechanism", "maximum_marks": 5},
    ],
    "minimum_words": 0,
    "strictness": 60,
}


@pytest.fixture()
def job_env(tmp_path):
    store = InMemoryJobStore()
    queue = InMemoryQueue()
    service = EvaluationJobService(store, queue)
    return store, queue, service, RUBRIC, tmp_path


def _submit(service, submission_id, tmp_path, rubrics):
    dummy_pdf = tmp_path / "dummy.pdf"
    if not dummy_pdf.exists():
        dummy_pdf.write_bytes(b"%PDF-1.4 fake")
    return service.submit(submission_id, str(dummy_pdf), rubrics)


def test_submit_is_idempotent_per_active_submission(job_env) -> None:
    _, _, service, rubric, tmp_path = job_env
    job1, created1 = _submit(service, "SUB-1", tmp_path, {"Q4": rubric})
    job2, created2 = _submit(service, "SUB-1", tmp_path, {"Q4": rubric})
    assert created1 is True and created2 is False
    assert job1.job_id == job2.job_id  # duplicate protected


def _inject_ready_state(state: dict) -> dict:
    """Skip perception stages by injecting pre-computed canonical answers."""
    from tests.unit.test_grading_rules import make_answer
    from tests.unit.test_workflow_graph import ANSWER_TEXT

    state.update(
        {
            "pdf_pages": 2,
            "regions_count": 3,
            "canonical_answers": [make_answer(ANSWER_TEXT).model_dump()],
        }
    )
    return state


def test_worker_completes_job_end_to_end(job_env) -> None:
    from answer_eval.workflow.graph import build_evaluation_graph
    from tests.unit.test_workflow_graph import FakeStructuredProvider

    store, queue, service, rubric, tmp_path = job_env
    provider = FakeStructuredProvider([json.loads(json.dumps(GOOD_EVAL))] * 2)
    app = build_evaluation_graph(provider)

    job, _ = _submit(service, "SUB-E2E", tmp_path, {"Q4": rubric})
    worker = EvaluationWorker(store, queue, lambda: app, worker_id="w1", initial_state_hook=_inject_ready_state)

    done = worker.run_once()
    assert done.status == JobStatus.completed
    assert done.progress_percent() == 100
    result = service.result("SUB-E2E")
    assert result["questions"]["Q4"]["final_marks"] == 10.0
    assert result["auto_approved"] == ["Q4"]


def test_retryable_failure_is_retried_then_completes(job_env) -> None:
    store, queue, service, rubric, tmp_path = job_env
    provider = failing_once_provider()

    def graph_factory():
        from answer_eval.workflow.graph import build_evaluation_graph

        return build_evaluation_graph(provider)

    job, _ = _submit(service, "SUB-R", tmp_path, {"Q4": rubric})
    worker = EvaluationWorker(
        store,
        queue,
        graph_factory,
        worker_id="w-retry",
        retry_policy=RetryPolicy(max_attempts=3),
        initial_state_hook=_inject_ready_state,
    )

    first = worker.run_once()
    assert first.status == JobStatus.retrying
    assert first.attempt == 2
    # Node normalizes the raw timeout into a retryable workflow failure.
    assert first.failures[0].exception_type == "RetryableJobError"
    assert "transient inference timeout" in first.failures[0].message

    store.update_job(first.job_id, next_attempt_at=None)  # simulate backoff elapsing
    second = worker.run_once()
    assert second.status == JobStatus.completed
    assert second.result_summary["questions"]["Q4"]["final_marks"] == 10.0


def test_permanent_failure_goes_to_dead_letter_without_retry(job_env) -> None:
    store, queue, service, _, tmp_path = job_env
    app = make_graph([])  # invalid rubric fails permanently before any LLM call

    job, _ = _submit(service, "SUB-DLQ", tmp_path, {"Q4": {"question_id": "Q4", "maximum_marks": -5}})
    done = EvaluationWorker(store, queue, lambda: app, worker_id="w-dlq").run_once()

    assert done.status == JobStatus.failed  # retained in durable dead-letter state


def test_empty_workflow_summary_is_failure_not_false_success(job_env) -> None:
    """A workflow that 'completes' with zero graded questions must surface as a
    failed job with a clear message — never a 0-mark 'completed' paper."""

    class EmptySummaryGraph:
        """Scripted graph whose result_summary has an empty questions dict,
        exactly what the real pipeline produced for an unmapped scanned paper."""

        def get_state(self, config):
            return None  # fresh job, no checkpoint

        def invoke(self, inputs, config=None):
            return {
                "status": "completed",
                "progress_total": 12,
                "result_summary": {
                    "submission_id": inputs.get("submission_id", "SUB-EMPTY"),
                    "questions": {},
                    "auto_approved": [],
                    "human_reviewed": [],
                    "total_proposed_marks": 0.0,
                },
            }

    store, queue, service, rubric, tmp_path = job_env
    job, _ = _submit(service, "SUB-EMPTY", tmp_path, {"Q4": rubric})
    done = EvaluationWorker(store, queue, lambda: EmptySummaryGraph(), worker_id="w-empty").run_once()

    assert done.status == JobStatus.failed
    assert done.error and "0 questions were graded" in done.error
    assert done.attempt == 1  # permanent errors are NOT retried
    assert done.failures[0].permanent is True


def test_lease_expiry_lets_second_worker_recover_crashed_job(job_env) -> None:
    store, queue, service, rubric, tmp_path = job_env
    job, _ = _submit(service, "SUB-CRASH", tmp_path, {"Q4": rubric})

    claimed = store.claim_next_job(worker_id="worker-a", lease_seconds=3600)
    assert claimed is not None and claimed.status == JobStatus.claimed

    store.update_job(claimed.job_id, lease_expires_at="2000-01-01T00:00:00+00:00")  # crash simulation
    assert store.reclaim_expired_leases() == 1
    requeued = store.get_job(claimed.job_id)
    assert requeued.status == JobStatus.queued

    app = make_graph([json.loads(json.dumps(GOOD_EVAL))] * 2)
    worker_b = EvaluationWorker(store, queue, lambda: app, worker_id="worker-b", initial_state_hook=_inject_ready_state)
    queue.enqueue(requeued.job_id)
    assert worker_b.run_once().status == JobStatus.completed


def test_progress_updates_flow_through_status_api(job_env) -> None:
    store, queue, service, rubric, tmp_path = job_env
    app = make_graph([json.loads(json.dumps(GOOD_EVAL))] * 2)

    job, _ = _submit(service, "SUB-PROG", tmp_path, {"Q4": rubric})
    status = service.status(job.job_id)
    assert status["status"] == "queued" and status["progress_percent"] == 0

    EvaluationWorker(store, queue, lambda: app, worker_id="w-prog", initial_state_hook=_inject_ready_state).run_once()
    status = service.status(job.job_id)
    assert status["status"] == "completed"
    assert status["progress_percent"] == 100 and status["stage"] == "completed"


def test_waiting_for_review_then_teacher_resume_completes(job_env) -> None:
    """Empty answer -> WAITING_FOR_REVIEW (never FAILED) -> teacher decision -> completed."""

    store, queue, service, rubric, tmp_path = job_env
    app = make_graph([])  # empty answer short-circuits; no LLM needed

    class ReviewAwareWorker(EvaluationWorker):
        """Injects perception results directly so the test exercises grading + HITL."""

        mode = {}

        def _execute(self, job):
            from langgraph.types import Command

            from answer_eval.workflow.graph import initial_state
            from tests.unit.test_grading_rules import make_answer as ma

            graph_app = self.graph_factory()
            config = {"configurable": {"thread_id": job.job_id}}
            if self.mode.get("resume"):
                existing = graph_app.get_state(config)
                assert existing and existing.next, "expected persisted interrupt"
                final = graph_app.invoke(Command(resume=job.review_decisions or {}), config=config)
            else:
                state = initial_state(job.job_id, job.submission_id, job.pdf_path, job.rubrics)
                state.update(
                    {
                        "pdf_pages": 2,
                        "regions_count": 3,
                        "canonical_answers": [ma("" if self.mode.get("empty") else "x" * 200).model_dump()],
                    }
                )
                final = graph_app.invoke(state, config=config)

            if final.get("__interrupt__"):
                self.store.update_job(job.job_id, status=JobStatus.waiting_for_review)
                return
            if str(final.get("status", "")).startswith("failed"):
                raise AssertionError(f"unexpected workflow failure: {final.get('errors')}")
            summary = final.get("result_summary") or {}
            self.store.update_job(
                job.job_id,
                status=JobStatus.completed,
                progress_completed=final.get("progress_total") or 12,
                result_summary=summary,
            )
            self.store.save_result(job.submission_id, summary)

    job, _ = _submit(service, "SUB-HITL", tmp_path, {"Q4": rubric})
    worker = ReviewAwareWorker(store, queue, lambda: app, worker_id="w-hitl")

    worker.mode = {"empty": True}
    after_first = worker.run_once()
    assert after_first.status == JobStatus.waiting_for_review  # review is NOT failure

    service.resume_after_review(job.job_id, {"Q4": {"approved": True, "final_marks": 0}})
    worker.mode = {"resume": True}
    final = worker.run_once()
    assert final.status == JobStatus.completed
    assert final.result_summary["human_reviewed"] == ["Q4"]


def test_worker_releases_job_when_pdf_not_on_this_node(job_env) -> None:
    """Multi-node safety: a claimed job whose PDF is missing on THIS machine is
    released back to the queue (another node sharing the store may own the
    file) instead of being permanently failed."""
    store, queue, service, rubric, tmp_path = job_env

    def _boom():
        raise AssertionError("_execute must never run for a released job")

    job, _ = service.submit("SUB-Foreign", str(tmp_path / "ghost.pdf"), {"Q4": rubric})
    assert not (tmp_path / "ghost.pdf").exists()

    no_backoff = RetryPolicy(max_attempts=3, initial_delay_s=0.0, backoff_factor=1.0)
    worker = EvaluationWorker(store, queue, _boom, worker_id="w-node-a", retry_policy=no_backoff)
    assert worker.run_once() is None  # released, not executed

    released = store.get_job(job.job_id)
    assert released is not None and released.status == JobStatus.queued
    assert released.node_skips == 1
    assert released.next_attempt_at is not None

    # The file shows up (e.g. the owning node's enqueue) -> job runs to completion.
    (tmp_path / "ghost.pdf").write_bytes(b"%PDF-1.4 now-available")
    store.update_job(job.job_id, next_attempt_at=None)
    queue.enqueue(job.job_id)
    from tests.unit.test_workflow_graph import make_graph

    app = make_graph([json.loads(json.dumps(GOOD_EVAL))] * 2)
    owner = EvaluationWorker(
        store, queue, lambda: app, worker_id="w-owner", initial_state_hook=_inject_ready_state
    )
    done = owner.run_once()
    assert done is not None and done.status == JobStatus.completed


def test_worker_dead_letters_job_when_no_node_can_read_pdf(job_env) -> None:
    """Once the node-skip budget is exhausted the job is dead-lettered with a
    clear permanent error instead of looping forever."""
    store, queue, service, rubric, tmp_path = job_env

    def _boom():
        raise AssertionError("_execute must never run for a released job")

    job, _ = service.submit("SUB-Lost", str(tmp_path / "never.pdf"), {"Q4": rubric})
    worker = EvaluationWorker(
        store,
        queue,
        _boom,
        worker_id="w-node-a",
        max_node_skips=2,
        retry_policy=RetryPolicy(max_attempts=3, initial_delay_s=0.0, backoff_factor=1.0),
    )

    for expected_skip in (1, 2):
        assert worker.run_once() is None
        current = store.get_job(job.job_id)
        assert current is not None and current.status == JobStatus.queued
        assert current.node_skips == expected_skip

    done = worker.run_once()
    assert done is not None and done.status == JobStatus.failed
    assert done.failures[-1].permanent is True
    assert done.error and "not accessible from any worker node" in done.error
