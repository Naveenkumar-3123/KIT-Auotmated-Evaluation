"""Milestone 6 integration: evaluation start/status/add-paper against LIVE Supabase.

Full flow continues from M5: configured assessment -> status snapshot ->
add missing paper -> begin evaluation (202, async) -> polling status shows
queued submissions; plus the guard rails that must refuse bad sequences.
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import fitz
import httpx
import pytest
from fastapi.testclient import TestClient

from answer_eval.answerkey.parser import FakeAnswerKeyParserAgent
from answer_eval.api.main import create_app
from answer_eval.storage import LocalStorageProvider

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("SUPABASE_URL") or "") and not Path(".env").exists(),
        reason="live credentials required",
    ),
]

SMOKE_EMAIL = os.getenv("SMOKE_USER_EMAIL", "evalai-smoke@test.evalai.local")
SMOKE_PASSWORD = os.getenv("SMOKE_USER_PASSWORD", "EvalAI-Smoke-2026!")


def _make_pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(
        storage=LocalStorageProvider(tmp_path / "storage"),
        answer_key_parser_factory=FakeAnswerKeyParserAgent,
    )
    with TestClient(app) as test_client:
        yield test_client


def _auth_headers() -> dict[str, str]:
    load_env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            load_env[key.strip()] = value.strip().strip('"')
    supabase_url = os.environ.get("SUPABASE_URL") or load_env.get("SUPABASE_URL", "")
    anon_key = os.environ.get("SUPABASE_ANON_KEY") or load_env.get("SUPABASE_ANON_KEY", "")
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            response = httpx.post(
                f"{supabase_url}/auth/v1/token?grant_type=password",
                headers={"apikey": anon_key},
                json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
                timeout=30,
            )
            response.raise_for_status()
            return {"Authorization": f"Bearer {response.json()['access_token']}"}
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"login failed: {last_error}")


POLICIES = {
    "strictness": {
        "mode": "ranges",
        "ranges": [{"from": 1, "to": 2, "level": "lenient"}],
        "questions": [],
    },
    "word_count": {
        "mode": "ranges",
        "ranges": [{"from": 1, "to": 2, "minimum_words": 100, "mode": "once", "trigger_shortfall_words": 20, "marks_deducted": 1}],
        "questions": [],
    },
    "diagrams": {"mode": "individual", "ranges": [], "questions": []},
}


def _configure_assessment(client: TestClient, headers: dict[str, str]) -> str:
    """Drive draft -> zip -> key -> policies -> finalize; return assessment id."""
    assessment_id = client.post("/api/assessments", headers=headers, json={}).json()["assessment"]["id"]
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("24MT001.pdf", _make_pdf("paper one"))
        archive.writestr("24MT002.pdf", _make_pdf("paper two"))
    upload = client.post(
        f"/api/assessments/{assessment_id}/student-zip",
        headers=headers,
        files={"file": ("papers.zip", zip_buffer.getvalue(), "application/zip")},
    )
    assert upload.status_code == 200 and upload.json()["valid"] == 2

    uploaded_key = client.post(
        f"/api/assessments/{assessment_id}/answer-key",
        headers=headers,
        files={"file": ("key.pdf", _make_pdf("answer key"), "application/pdf")},
    ).json()["answer_key"]["id"]
    for _ in range(50):
        meta = client.get(f"/api/answer-keys/{uploaded_key}", headers=headers).json()["answer_key"]
        if meta["status"] != "parsing":
            break
        time.sleep(0.1)
    assert meta["status"] == "parsed"
    confirmed = client.patch(
        f"/api/answer-keys/{uploaded_key}/review", headers=headers, json={"edits": [], "confirm": True}
    )
    assert confirmed.json()["answer_key"]["status"] == "reviewed"

    saved = client.put(f"/api/assessments/{assessment_id}/policies", headers=headers, json=POLICIES)
    assert saved.status_code == 200, saved.text

    details = client.patch(
        f"/api/assessments/{assessment_id}",
        headers=headers,
        json={"class_name": "TY-MT", "subject_name": "Operating Systems"},
    )
    assert details.status_code == 200

    finalized = client.post(f"/api/assessments/{assessment_id}/finalize", headers=headers, json={})
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["assessment"]["status"] == "configured"
    return assessment_id


def test_evaluation_start_status_and_add_paper_live(client) -> None:
    headers = _auth_headers()
    assessment_id = _configure_assessment(client, headers)

    # Status snapshot BEFORE start: everything uploaded and ready.
    before = client.get(f"/api/assessments/{assessment_id}/status", headers=headers)
    assert before.status_code == 200
    body = before.json()
    assert body["status"] == "configured"
    assert body["summary"]["ready"] == 2 and body["summary"]["total"] == 2
    assert len(body["students"]) == 2
    assert all(s["status"] == "uploaded" for s in body["students"])
    assert body["answer_key"] is not None and body["answer_key"]["version"] >= 1

    # Add a missing paper (spec #27) through the real upload endpoint.
    added = client.post(
        f"/api/assessments/{assessment_id}/submissions",
        headers=headers,
        files={"file": ("24MT007.pdf", _make_pdf("late submission"), "application/pdf")},
    )
    assert added.status_code == 201, added.text
    assert added.json()["valid"] == 1
    assert any(s["roll_number"] == "24MT007" for s in added.json()["students"])

    # Corrupt PDF must be refused with a real reason.
    corrupt = client.post(
        f"/api/assessments/{assessment_id}/submissions",
        headers=headers,
        files={"file": ("24MT999.pdf", b"this is not a pdf", "application/pdf")},
    )
    assert corrupt.status_code == 422

    # Begin evaluation: async accept, papers queued, request returns immediately.
    started = client.post(f"/api/assessments/{assessment_id}/start", headers=headers)
    assert started.status_code == 202, started.text
    payload = started.json()
    assert payload["assessment_id"] == assessment_id
    assert payload["status"] == "processing"
    assert payload["submissions_queued"] == 3

    # Double-start is refused.
    again = client.post(f"/api/assessments/{assessment_id}/start", headers=headers)
    assert again.status_code == 409

    # Adding papers after start is refused.
    late = client.post(
        f"/api/assessments/{assessment_id}/submissions",
        headers=headers,
        files={"file": ("24MT008.pdf", _make_pdf("too late"), "application/pdf")},
    )
    assert late.status_code == 409

    # Polling status now reports queued submissions (incremental results source).
    during = client.get(f"/api/assessments/{assessment_id}/status", headers=headers).json()
    assert during["status"] == "processing"
    assert during["summary"]["ready"] == 0
    assert during["summary"]["processing"] == 3
    assert all(s["status"] == "queued" for s in during["students"])

    # Listing carries the full count breakdown for the Evaluation page cards.
    listing = client.get("/api/assessments", headers=headers).json()
    match = next(item for item in listing if item["id"] == assessment_id)
    assert match["student_count"] == 3
    assert match["processing_count"] == 3
    assert match["completed_count"] == 0


def test_start_refused_for_draft(client) -> None:
    headers = _auth_headers()
    assessment_id = client.post("/api/assessments", headers=headers, json={}).json()["assessment"]["id"]
    refused = client.post(f"/api/assessments/{assessment_id}/start", headers=headers)
    assert refused.status_code == 409



