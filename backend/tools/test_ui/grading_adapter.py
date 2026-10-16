"""Bridge between the dev UI and Modules 12-18 (grading, verification, risk, jobs).

Deliberately free of Streamlit imports so the logic stays unit-testable.
Covers:
  - Direct grading (M12-16) via GradingService with a real or mock provider
  - A deterministic MockGradingProvider producing rubric-aware evaluation JSON
  - GradingJobsController: durable store + queue + embedded worker management
"""

import asyncio
import json
import threading
import uuid
from typing import Any

from answer_eval.agents.reconstruction.schemas import AnswerSegment, CanonicalStructuredAnswer
from answer_eval.core.logging import get_logger
from answer_eval.core.provenance import Provenance
from answer_eval.grading.rubric import QuestionRubric
from answer_eval.grading.service import GradingService
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import InferenceRequest, InferenceResponse, InferenceTiming, MemorySnapshot, TokenUsage
from answer_eval.jobs.queue import create_queue
from answer_eval.jobs.schemas import JobRecord, JobStatus
from answer_eval.jobs.service import EvaluationJobService
from answer_eval.jobs.store import SQLiteJobStore
from answer_eval.jobs.worker import EvaluationWorker
from answer_eval.models.profiles import ModelCapabilities

logger = get_logger("tools.test_ui.grading_adapter")

DEFAULT_JOBS_DB = "data/dev_ui_jobs.db"

SAMPLE_ANSWER_TEXT = (
    "TCP is a reliable transport protocol used on the internet. Before any data is "
    "exchanged, the sender and receiver perform a handshake that establishes a session "
    "between them, so communication only happens inside this established session. While "
    "data is being transferred, the receiving host returns a short confirmation message "
    "for every segment it successfully accepts. If the sending side does not receive this "
    "confirmation within a fixed timeout period, it assumes the segment was lost and "
    "transmits that segment again. Sequence numbers allow the receiver to reorder segments "
    "that arrive out of order and detect duplicates. Together these mechanisms guarantee "
    "that applications receive every byte exactly once and in the correct order."
)

SAMPLE_RUBRIC: dict[str, Any] = {
    "question_id": "Q4",
    "question_text": "Explain how TCP provides reliable communication.",
    "answer_type": "explain",
    "maximum_marks": 10,
    "expected_answer": None,
    "expected_concepts": [
        {
            "concept_id": "C1",
            "description": "Connection-oriented communication",
            "maximum_marks": 5,
            "required": True,
        },
        {
            "concept_id": "C2",
            "description": "Acknowledgement mechanism",
            "maximum_marks": 5,
            "required": True,
        },
    ],
    "keywords": ["acknowledgement", "retransmission"],
    "mandatory_terms": ["TCP"],
    "minimum_words": 100,
    "diagram": {"required": False},
    "strictness": 60,
}


class MockGradingProvider(InferenceProvider):
    """Deterministic structured-output mock for the M14/M15 agents.

    Builds a valid EvaluationResult payload from a canned student text so that
    evidence quotes always verify against the canonical corpus. The verifier
    receives an independent-looking payload with identical marks (agreement).
    """

    def __init__(self, answer_text: str = "", rubric: dict[str, Any] | None = None) -> None:
        self.answer_text = answer_text or ""
        self.rubric = rubric or SAMPLE_RUBRIC
        self.call_count = 0

    async def initialize(self, model, config, hardware=None) -> None: ...

    async def health_check(self) -> bool:
        return True

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(vision=True, structured_output=True, thinking=False)

    def get_memory_usage(self) -> MemorySnapshot:
        return MemorySnapshot(vram_used_gb=0.0, vram_free_gb=0.0, ram_used_gb=0.1, ram_available_gb=8.0)

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        raise NotImplementedError("MockGradingProvider only supports structured grading tasks")

    async def shutdown(self) -> None: ...

    def _evidence_for(self, criterion_index: int) -> list[dict[str, Any]]:
        """Sample verbatim quotes out of the canned text so evidence verifies."""
        words = self.answer_text.split()
        if len(words) < 6:
            return []
        span = max(4, len(words) // 3)
        start = min(criterion_index * span, max(0, len(words) - span))
        quote = " ".join(words[start : start + span])
        return [{"quote": quote, "page_number": 1}]

    def _payload(self, task: str) -> dict[str, Any]:
        concepts = self.rubric.get("expected_concepts", [])
        has_text = bool(self.answer_text.strip())
        criteria = []
        for idx, concept in enumerate(concepts):
            max_marks = float(concept.get("maximum_marks", 0))
            criteria.append(
                {
                    "criterion_id": concept["concept_id"],
                    "criterion": concept.get("description", ""),
                    "status": "fully_supported" if has_text else "unsupported",
                    "match_type": "semantic_equivalent" if has_text else "none",
                    "student_evidence": self._evidence_for(idx),
                    "maximum_marks": max_marks,
                    "proposed_marks": max_marks if has_text else 0.0,
                    "reason": (
                        f"[{task}] Concept expressed in equivalent wording by the student."
                        if has_text
                        else "[task] No answer content available."
                    ),
                }
            )
        return {
            "schema_version": "evaluation-v1",
            "question_id": self.rubric.get("question_id", "Q1"),
            "criteria": criteria,
            "missing_concepts": [],
            "contradictions": [],
            "feedback": "Mock grading feedback." if has_text else "Empty answer.",
            "flags": [],
        }

    async def infer_structured(
        self,
        request: InferenceRequest,
        schema: type | dict[str, Any],
        max_retries: int = 2,
    ) -> InferenceResponse:
        self.call_count += 1
        task = (request.metadata or {}).get("task", "evaluation")
        payload = self._payload(task)
        return InferenceResponse(
            request_id=request.request_id,
            provider="mock",
            model_id="mock-grader",
            text=json.dumps(payload),
            structured_data=payload,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=80, total_tokens=180),
            timing=InferenceTiming(total_inference_ms=5.0, tokens_per_second=16000.0),
        )


def build_grading_provider(mock_mode: bool, answer_text: str = "", rubric: dict | None = None) -> InferenceProvider:
    """Real Ollama provider or the deterministic mock — same interface either way."""
    if mock_mode:
        return MockGradingProvider(answer_text=answer_text, rubric=rubric)
    from answer_eval.inference.ollama_provider import OllamaProvider

    return OllamaProvider(timeout_seconds=600.0)


def validate_rubric_dict(rubric_dict: dict[str, Any]) -> QuestionRubric:
    """Parse + pre-LLM validation; raises before anything reaches a model."""
    return QuestionRubric.model_validate(rubric_dict)


def make_canonical_answer(submission_id: str, question_id: str, text: str) -> CanonicalStructuredAnswer:
    provenance = Provenance(
        submission_id=submission_id,
        page_number=1,
        region_id="REG-UI-1",
        question_id=question_id,
        source_image_hash="dev-ui",
        request_id=f"ui-{uuid.uuid4().hex[:8]}",
        model_id="dev-ui",
    )
    return CanonicalStructuredAnswer(
        submission_id=submission_id,
        question_id=question_id,
        source_pages=[1],
        raw_text=text,
        word_count=len(text.split()),
        segments=[AnswerSegment(page_number=1, region_id="REG-UI-1", reading_order=1, raw_text=text)],
        diagrams=[],
        flags=[],
        provenance=provenance,
    )


async def grade_question_async(
    provider: InferenceProvider,
    answer_text: str,
    rubric_dict: dict[str, Any],
    submission_id: str = "SUB-DEV-UI",
) -> Any:
    """Modules 12-16 for one question. Raises RubricValidationError etc. on bad input."""
    rubric = validate_rubric_dict(rubric_dict)
    canonical = make_canonical_answer(submission_id, rubric.question_id, answer_text)
    service = GradingService(inference_provider=provider)
    return await service.grade_question(canonical, rubric)


def run_direct_grading(
    provider: InferenceProvider,
    answer_text: str,
    rubric_dict: dict[str, Any],
    submission_id: str = "SUB-DEV-UI",
):
    """Sync wrapper for direct grading (Streamlit-safe)."""
    return asyncio.run(grade_question_async(provider, answer_text, rubric_dict, submission_id))


class GradingJobsController:
    """Durable job store + queue + API-facing service + ONE embedded worker.

    The controller is a dev-UI convenience around the exact same Module 18
    objects the FastAPI layer and external workers use.
    """

    def __init__(self, db_path: str | None = None) -> None:
        import os

        self.store = SQLiteJobStore(db_path or os.getenv("DEV_UI_JOBS_DB") or DEFAULT_JOBS_DB)
        self.queue = create_queue()
        self.service = EvaluationJobService(self.store, self.queue)
        self._worker: EvaluationWorker | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------ worker
    @property
    def worker_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def worker_id(self) -> str | None:
        return self._worker.worker_id if self._worker else None

    def start_worker(
        self,
        provider_factory,
        checkpoint_db: str | None = None,
        initial_state_hook=None,
    ) -> None:
        """provider_factory() must return a fresh InferenceProvider per graph build.

        checkpoint_db: optional SQLite path -> durable LangGraph checkpoints
        (survives UI restarts); empty -> in-memory development fallback.
        initial_state_hook: optional callable enriching initial workflow state
        (e.g. mock mode injecting pre-computed canonical answers to skip OCR).
        """
        if self.worker_running:
            return

        def graph_factory():
            from answer_eval.workflow.graph import build_evaluation_graph

            checkpointer = None
            if checkpoint_db:
                import sqlite3

                from langgraph.checkpoint.sqlite import SqliteSaver

                conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
                checkpointer = SqliteSaver(conn)
            return build_evaluation_graph(provider_factory(), checkpointer=checkpointer)

        self._worker = EvaluationWorker(
            self.store,
            self.queue,
            graph_factory,
            poll_interval_s=0.5,
            initial_state_hook=initial_state_hook,
        )
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_worker_loop, daemon=True, name="dev-ui-worker")
        self._thread.start()
        logger.info("Dev UI embedded worker started", worker_id=self._worker.worker_id)

    def _run_worker_loop(self) -> None:  # pragma: no cover - thread body
        assert self._worker is not None
        while not self._stop_event.is_set():
            try:
                self._worker.run_once()
            except Exception as e:
                logger.error("Embedded worker cycle failed", error=str(e))
            self._stop_event.wait(0.3)

    def stop_worker(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("Dev UI embedded worker stopped")

    # ------------------------------------------------------------------- jobs
    def submit(self, submission_id: str, pdf_path: str, rubrics: dict[str, Any]) -> tuple[JobRecord, bool]:
        return self.service.submit(submission_id=submission_id, pdf_path=pdf_path, rubrics=rubrics)

    def review(self, job_id: str, decisions: dict[str, Any]) -> JobRecord:
        return self.service.resume_after_review(job_id, decisions)

    def status(self, job_id: str) -> dict[str, Any] | None:
        return self.service.status(job_id)

    def result(self, submission_id: str) -> dict[str, Any] | None:
        return self.store.get_result(submission_id)

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        return self.store.list_jobs(limit=limit)

    def job_summaries(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = []
        for j in reversed(self.list_jobs(limit)):
            rows.append(
                {
                    "job_id": j.job_id,
                    "submission_id": j.submission_id,
                    "status": j.status.value,
                    "stage": j.current_stage,
                    "progress_%": j.progress_percent(),
                    "attempt": f"{j.attempt}/{j.max_attempts}",
                    "worker": j.worker_id or "-",
                    "error": (j.error or "")[:60],
                }
            )
        return rows


def mock_state_hook(sample_answer_text: str):
    """Inject pre-computed canonical answers so mock runs skip perception stages."""

    def hook(inputs: dict[str, Any]) -> dict[str, Any]:
        qid = next(iter(inputs.get("rubrics") or {}), "Q1")
        canonical = make_canonical_answer(inputs["submission_id"], qid, sample_answer_text)
        return {**inputs, "pdf_pages": 1, "regions_count": 3, "canonical_answers": [canonical.model_dump()]}

    return hook


def status_label(job_status: JobStatus | str) -> str:
    value = job_status.value if isinstance(job_status, JobStatus) else str(job_status)
    return value.replace("_", " ").title()


__all__ = [
    "DEFAULT_JOBS_DB",
    "GradingJobsController",
    "MockGradingProvider",
    "SAMPLE_ANSWER_TEXT",
    "SAMPLE_RUBRIC",
    "build_grading_provider",
    "grade_question_async",
    "make_canonical_answer",
    "mock_state_hook",
    "run_direct_grading",
    "status_label",
    "validate_rubric_dict",
]
