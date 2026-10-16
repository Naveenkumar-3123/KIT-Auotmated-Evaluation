"""Tests for the dev-UI grading bridge (tools/test_ui/grading_adapter.py).

Covers the Streamlit-free logic: sample rubric validation, mock-provider direct
grading through the real GradingService, empty-answer review routing, and
GradingJobsController lifecycle against a temp SQLite store.
"""

import pytest

from answer_eval.core.errors import JobError
from tools.test_ui.grading_adapter import (
    SAMPLE_ANSWER_TEXT,
    SAMPLE_RUBRIC,
    GradingJobsController,
    MockGradingProvider,
    make_canonical_answer,
    mock_state_hook,
    run_direct_grading,
    validate_rubric_dict,
)


def test_sample_rubric_is_valid() -> None:
    rubric = validate_rubric_dict(SAMPLE_RUBRIC)
    assert rubric.question_id == "Q4"
    assert rubric.strictness == 60
    rubric.validate_rubric()  # explicit pre-LLM validation passes


def _flags(g) -> set[str]:
    return set(g.flags)


def test_mock_direct_grading_full_credit_auto_approves() -> None:
    provider = MockGradingProvider(answer_text=SAMPLE_ANSWER_TEXT)
    graded = run_direct_grading(provider, SAMPLE_ANSWER_TEXT, dict(SAMPLE_RUBRIC))

    assert graded.marks.final_proposed_marks == 10.0
    assert graded.marks.deterministic_penalty == 0.0
    # Evaluator and blind verifier agree criterion-by-criterion
    assert graded.comparison.total_difference == 0
    assert graded.comparison.criterion_agreement_rate == 1.0
    assert not graded.comparison.major_disagreement
    # Low risk -> auto approved without human review
    assert graded.risk.auto_approve is True
    assert graded.review.required is False
    # Evidence verified against canonical corpus, no unverified flags
    for crit in graded.evaluation.criteria:
        assert crit.student_evidence
        assert all(ev.verified_in_answer for ev in crit.student_evidence)
    assert not any("unverified_evidence" in f for f in _flags(graded))
    # Versioned provenance recorded
    assert graded.versions.strictness_policy == "strictness-v1"
    assert graded.versions.risk_policy == "heuristic-risk-v2"


def test_mock_empty_answer_routes_to_review_without_model_calls() -> None:
    provider = MockGradingProvider(answer_text="")
    graded = run_direct_grading(provider, "", dict(SAMPLE_RUBRIC))
    assert provider.call_count == 0  # deterministic shortcut skipped both agents
    assert graded.marks.final_proposed_marks == 0.0
    assert graded.review.required is True
    assert "answer_empty" in _flags(graded)


def test_mock_provider_marks_clamped_to_maxima() -> None:
    """Even if the mock proposed over-maximum marks, validation clamps them."""
    provider = MockGradingProvider(answer_text=SAMPLE_ANSWER_TEXT)
    rubric = dict(SAMPLE_RUBRIC)
    provider.rubric = {
        **rubric,
        "expected_concepts": [
            {"concept_id": "C1", "description": "x", "maximum_marks": 3},
            {"concept_id": "C2", "description": "y", "maximum_marks": 7},
        ],
    }
    graded = run_direct_grading(provider, SAMPLE_ANSWER_TEXT, rubric)
    totals = sum(c.proposed_marks for c in graded.evaluation.criteria)
    assert totals <= 10.0
    assert graded.marks.final_proposed_marks <= 10.0


def test_controller_lifecycle_with_temp_sqlite(tmp_path) -> None:
    db = tmp_path / "jobs.db"
    pdf = tmp_path / "sheet.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    controller = GradingJobsController(db_path=str(db))
    job, created = controller.submit("SUB-T1", str(pdf), {"Q4": SAMPLE_RUBRIC})
    assert created is True
    assert controller.status(job.job_id)["status"] == "queued"

    duplicate, created_again = controller.submit("SUB-T1", str(pdf), {"Q4": SAMPLE_RUBRIC})
    assert created_again is False and duplicate.job_id == job.job_id

    summaries = controller.job_summaries()
    assert any(row["job_id"] == job.job_id for row in summaries)

    with pytest.raises(JobError):
        controller.review(job.job_id, {"Q4": {"approved": True}})  # not waiting_for_review

    controller.stop_worker()  # never started — must be a safe no-op
    assert controller.worker_running is False

    # Durable store reloads from disk
    reloaded = GradingJobsController(db_path=str(db))
    assert reloaded.status(job.job_id)["status"] == "queued"


def test_mock_state_hook_injects_canonical_answer() -> None:
    hook = mock_state_hook(SAMPLE_ANSWER_TEXT)
    inputs = {
        "submission_id": "SUB-H",
        "pdf_path": "x.pdf",
        "rubrics": {"Q4": SAMPLE_RUBRIC},
        "status": "running",
    }
    enriched = hook(inputs)
    answers = enriched["canonical_answers"]
    assert len(answers) == 1
    restored = make_canonical_answer("SUB-H", "Q4", "")
    assert type(answers[0]) is dict
    assert answers[0]["question_id"] == "Q4"
    assert restored.question_id == "Q4"
