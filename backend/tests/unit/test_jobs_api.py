"""Smoke test for the optional FastAPI surface (Module 18)."""

import pytest
from fastapi.testclient import TestClient

from answer_eval.jobs.api import create_app
from answer_eval.jobs.store import InMemoryJobStore


@pytest.fixture()
def client():
    store = InMemoryJobStore()
    app = create_app(store)  # queue falls back to in-memory when Redis is absent
    return TestClient(app), store


def test_api_submit_status_result_roundtrip(client):
    api, _store = client
    body = {
        "submission_id": "SUB-API",
        "pdf_path": "whatever.pdf",
        "rubrics": {"Q1": {"question_id": "Q1", "maximum_marks": 5}},
    }
    resp = api.post("/submissions", json=body)
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["submission_id"] == "SUB-API" and payload["job_id"]

    dup = api.post("/submissions", json=body).json()
    assert dup["duplicate"] is True

    status = api.get(f"/jobs/{payload['job_id']}").json()
    assert status["status"] in ("queued",)

    result = api.get("/submissions/SUB-API/result")
    assert result.status_code == 404  # nothing processed yet

    unknown = api.get("/jobs/JOB-UNKNOWN")
    assert unknown.status_code == 404


def test_api_review_endpoint_validation(client):
    api, _ = client
    body = {"submission_id": "SUB-RV", "pdf_path": "x.pdf", "rubrics": {}}
    job_id = api.post("/submissions", json=body).json()["job_id"]
    resp = api.post(f"/jobs/{job_id}/review", json={"decisions": {"Q1": {"approved": True}}})
    assert resp.status_code == 409  # job not waiting_for_review -> conflict
