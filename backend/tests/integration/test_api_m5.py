"""Milestone 5 integration: policies + finalize against LIVE Supabase.

Full teacher flow: draft → zip → answer key (fake parser) → review →
policies (ranges + per-question overrides) → resolved snapshot → finalize →
locked versions/totals; plus the guard rails that must refuse bad sequences.
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
        "ranges": [
            {"from": 1, "to": 2, "level": "lenient"},
        ],
        "questions": [],
    },
    "word_count": {
        "mode": "ranges",
        "ranges": [{"from": 1, "to": 2, "minimum_words": 100, "mode": "once", "trigger_shortfall_words": 20, "marks_deducted": 1}],
        "questions": [],
    },
    "diagrams": {
        "mode": "individual",
        "ranges": [],
        "questions": [{"question": 2, "required": True, "minimum_diagrams": 1, "missing_diagram_deductions": [2]}],
    },
}


def test_full_configure_flow_live(client) -> None:
    headers = _auth_headers()

    # Draft with papers
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

    # Policies BEFORE any key must be refused
    early = client.put(f"/api/assessments/{assessment_id}/policies", headers=headers, json=POLICIES)
    assert early.status_code == 409

    # Answer key (fake parser returns Q1..Q2 fixture) + review confirm
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
    confirmed = client.patch(f"/api/answer-keys/{uploaded_key}/review", headers=headers, json={"edits": [], "confirm": True})
    assert confirmed.json()["answer_key"]["status"] == "reviewed"

    # Out-of-range policy rejected with a helpful message
    bad = dict(POLICIES)
    bad["strictness"] = {
        "mode": "questions",
        "ranges": [],
        "questions": [{"question": 9, "level": "strict"}],
    }
    rejected = client.put(f"/api/assessments/{assessment_id}/policies", headers=headers, json=bad)
    assert rejected.status_code == 422 and "outside this assessment" in rejected.json()["error"]["message"]

    # Real policies land
    saved = client.put(f"/api/assessments/{assessment_id}/policies", headers=headers, json=POLICIES)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["policy_version"] >= 1 and body["question_count"] == 2
    by_q = {row["question_number"]: row for row in body["policies"]}
    assert by_q[1]["strictness_level"] == "lenient"
    assert by_q[2]["strictness_level"] == "lenient"  # range covers both; per-Q3 doesn't exist in 2-question key
    assert by_q[2]["diagram_required"] is True
    assert by_q[2]["missing_diagram_deductions"] == [2.0]
    assert by_q[1]["minimum_words"] == 100
    assert float(by_q[1]["rubric_snapshot"]["maximum_marks"]) == 4  # from fake-key fixture C1+... totals

    # Resolved endpoint mirrors it
    resolved = client.get(f"/api/assessments/{assessment_id}/policies/resolved", headers=headers).json()
    assert len(resolved["policies"]) == 2
    assert resolved["total_maximum"] > 0

    # Finalize without class/subject must fail
    no_details = client.post(f"/api/assessments/{assessment_id}/finalize", headers=headers, json={})
    assert no_details.status_code == 422

    details = client.patch(
        f"/api/assessments/{assessment_id}",
        headers=headers,
        json={"class_name": "TY-MT", "subject_name": "Operating Systems", "pass_percentage": 42},
    )
    assert details.status_code == 200

    finalized = client.post(
        f"/api/assessments/{assessment_id}/finalize",
        headers=headers,
        json={"title": "OS Mid-Sem"},
    )
    assert finalized.status_code == 200, finalized.text
    assessment = finalized.json()["assessment"]
    summary = finalized.json()["summary"]
    assert assessment["status"] == "configured"
    assert assessment["title"] == "OS Mid-Sem"
    assert int(assessment["question_count"]) == 2
    assert int(assessment["locked_answer_key_version"]) == 1
    assert int(assessment["locked_policy_version"]) == int(body["policy_version"])
    assert float(assessment["pass_percentage"]) == 42
    assert summary["total"] == 2

    # Locked drafts can't be silently deleted
    delete_blocked = client.delete(f"/api/assessments/{assessment_id}", headers=headers)
    assert delete_blocked.status_code == 409

    # Listing shows the configured assessment
    listing = client.get("/api/assessments", headers=headers).json()
    match = next(item for item in listing if item["id"] == assessment_id)
    assert match["class_name"] == "TY-MT" and match["completed_count"] == 0
