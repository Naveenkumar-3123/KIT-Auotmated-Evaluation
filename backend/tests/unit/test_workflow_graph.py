"""Integration tests for Module 17 (LangGraph workflow).

Runs the REAL compiled graph with a scripted fake inference provider
(integration-tested orchestration; model calls are faked).
"""

import json
import uuid

import pytest  # noqa: F401
from langgraph.types import Command

from answer_eval.inference.types import InferenceResponse
from answer_eval.workflow.graph import build_evaluation_graph, initial_state
from tests.unit.test_grading_rules import make_rubric


class FakeStructuredProvider:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)

    async def infer_structured(self, request, schema, max_retries: int = 2):
        data = self.responses.pop(0) if self.responses else {"question_id": "Q1", "criteria": []}
        return InferenceResponse(
            request_id=request.request_id,
            provider="fake",
            model_id="fake-4b",
            text="structured",
            structured_data=data,
        )

    async def initialize(self, *a, **k): ...
    async def health_check(self):
        return True

    async def infer(self, request):
        raise NotImplementedError

    def get_capabilities(self):
        raise NotImplementedError

    def get_memory_usage(self):
        raise NotImplementedError

    async def shutdown(self): ...


GOOD_EVAL = {
    "schema_version": "evaluation-v1",
    "question_id": "Q4",
    "criteria": [
        {
            "criterion_id": "C1",
            "status": "fully_supported",
            "match_type": "semantic_equivalent",
            "student_evidence": [{"quote": "tcp is connection oriented", "page_number": 1}],
            "maximum_marks": 5,
            "proposed_marks": 5,
            "reason": "Stated directly.",
        },
        {
            "criterion_id": "C2",
            "status": "fully_supported",
            "match_type": "semantic_equivalent",
            "student_evidence": [{"quote": "receiver confirms", "page_number": 1}],
            "maximum_marks": 5,
            "proposed_marks": 5,
            "reason": "Stated directly.",
        },
    ],
    "feedback": "Good.",
    "flags": [],
}

ANSWER_TEXT = "TCP is connection oriented. The receiver confirms packets arrived. " + "word " * 81


def base_inputs(tmp_path: str) -> dict:
    """State pre-populated past perception so tests exercise grading stages only."""
    from tests.unit.test_grading_rules import make_answer

    dummy_pdf = f"{tmp_path}/dummy.pdf"
    with open(dummy_pdf, "wb") as f:
        f.write(b"%PDF-1.4 fake")

    answer = make_answer(ANSWER_TEXT)
    inputs = initial_state("JOB-X", "SUB-X", dummy_pdf, {"Q4": make_rubric().model_dump()})
    inputs.update({"pdf_pages": 2, "regions_count": 3, "canonical_answers": [answer.model_dump()]})
    return inputs


def make_graph(provider_responses: list[dict]):
    provider = FakeStructuredProvider(provider_responses)
    return build_evaluation_graph(provider)


def test_auto_approval_flow_completes(tmp_path) -> None:
    app = make_graph([json.loads(json.dumps(GOOD_EVAL))] * 2)
    inputs = {**base_inputs(str(tmp_path)), "job_id": "JOB-A1", "submission_id": "SUB-A1"}

    final = app.invoke(inputs, config={"configurable": {"thread_id": "JOB-A1"}})

    assert final["status"] == "completed"
    summary = final["result_summary"]
    assert summary["questions"]["Q4"]["final_marks"] == 10.0
    assert summary["auto_approved"] == ["Q4"]
    assert summary["human_reviewed"] == []
    # Versions/provenance recorded for reproducibility
    versions = final["graded_answers"]["Q4"]["versions"]
    assert versions["strictness_policy"] == "strictness-v1"
    assert versions["risk_policy"] == "heuristic-risk-v2"


def test_human_review_interrupts_then_resumes(tmp_path) -> None:
    """An EMPTY answer triggers mandatory review -> interrupt -> teacher decision -> resume."""
    from tests.unit.test_grading_rules import make_answer

    app = make_graph([])
    inputs = {**base_inputs(str(tmp_path)), "job_id": "JOB-R1", "submission_id": "SUB-R1"}
    inputs["canonical_answers"] = [make_answer("").model_dump()]  # empty -> mandatory review
    # Unique thread per run: the checkpointer may be durable (PostgreSQL), and a
    # reused thread_id would replay a stale checkpoint instead of interrupting.
    thread = f"JOB-R1-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread}}

    interrupted = app.invoke(inputs, config=config)
    assert interrupted.get("__interrupt__"), "expected human-review interrupt"

    resumed = app.invoke(
        Command(resume={"Q4": {"approved": True, "final_marks": 0, "reviewer_notes": "blank page"}}),
        config=config,
    )
    assert resumed["status"] == "completed"
    assert resumed["result_summary"]["human_reviewed"] == ["Q4"]
    assert resumed["graded_answers"]["Q4"]["review"]["status"] == "reviewed"
    assert resumed["review_decisions"]["Q4"]["approved"] is True


def test_duplicate_execution_is_idempotent(tmp_path) -> None:
    app = make_graph([json.loads(json.dumps(GOOD_EVAL))] * 2)
    inputs = {**base_inputs(str(tmp_path)), "job_id": "JOB-I1", "submission_id": "SUB-I1"}
    config = {"configurable": {"thread_id": "JOB-I1"}}

    first = app.invoke(dict(inputs), config=config)
    second = app.invoke(dict(inputs), config=config)

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert second["graded_answers"] == first["graded_answers"]


def test_restart_from_sqlite_checkpoint_resumes_review(tmp_path) -> None:
    """SqliteSaver durability: interrupt, simulate a process restart (new graph +
    new saver over the SAME checkpoint DB), then resume the paused workflow."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    from tests.unit.test_grading_rules import make_answer

    db_path = str(tmp_path / "checkpoints.sqlite")
    inputs = {**base_inputs(str(tmp_path)), "job_id": "JOB-S1", "submission_id": "SUB-S1"}
    inputs["canonical_answers"] = [make_answer("").model_dump()]  # empty -> mandatory review
    config = {"configurable": {"thread_id": "JOB-S1"}}

    # First "process": run until the human-review interrupt, checkpointed to disk.
    conn1 = sqlite3.connect(db_path, check_same_thread=False)
    app1 = build_evaluation_graph(FakeStructuredProvider([]), checkpointer=SqliteSaver(conn1))
    interrupted = app1.invoke(dict(inputs), config=config)
    assert interrupted.get("__interrupt__"), "expected human-review interrupt"
    conn1.close()

    # Restart: brand-new graph + saver reading the SAME SQLite checkpoint DB.
    conn2 = sqlite3.connect(db_path, check_same_thread=False)
    app2 = build_evaluation_graph(FakeStructuredProvider([]), checkpointer=SqliteSaver(conn2))
    resumed = app2.invoke(
        Command(resume={"Q4": {"approved": True, "final_marks": 0, "reviewer_notes": "blank page"}}),
        config=config,
    )
    conn2.close()

    assert resumed["status"] == "completed"
    assert resumed["result_summary"]["human_reviewed"] == ["Q4"]
    assert resumed["graded_answers"]["Q4"]["review"]["status"] == "reviewed"
    assert resumed["review_decisions"]["Q4"]["approved"] is True


def test_invalid_rubric_fails_permanent_before_llm(tmp_path) -> None:
    app = make_graph([])
    inputs = {**base_inputs(str(tmp_path)), "job_id": "JOB-F1", "submission_id": "SUB-F1"}
    inputs["rubrics"] = {"Q4": {"question_id": "Q4", "maximum_marks": -5}}  # invalid

    final = app.invoke(inputs, config={"configurable": {"thread_id": "JOB-F1"}})
    assert final["status"] == "failed_permanent"
