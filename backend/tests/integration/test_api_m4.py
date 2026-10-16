"""Milestone 4 integration: answer-key upload → background parse (fake agent)
→ poll → review edits, against LIVE Supabase Postgres."""

from __future__ import annotations

import os
import time
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
    data = doc.tobytes()
    doc.close()
    return data


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
    raise RuntimeError(f"Supabase login failed after retries: {last_error}")


def test_answer_key_upload_parse_review_live(client) -> None:
    headers = _auth_headers()

    assessment_id = client.post("/api/assessments", headers=headers, json={}).json()["assessment"]["id"]

    uploaded = client.post(
        f"/api/assessments/{assessment_id}/answer-key",
        headers=headers,
        files={"file": ("key.pdf", _make_pdf("1. Explain flow control"), "application/pdf")},
    )
    assert uploaded.status_code == 202, uploaded.text
    key_id = uploaded.json()["answer_key"]["id"]
    assert uploaded.json()["answer_key"]["status"] == "parsing"

    # Poll until the background parse finishes (fast with the fake agent).
    meta = {}
    for _ in range(50):
        payload = client.get(f"/api/answer-keys/{key_id}", headers=headers).json()
        meta = payload["answer_key"]
        if meta["status"] != "parsing":
            break
        time.sleep(0.1)
    assert meta["status"] == "parsed", meta

    questions = client.get(f"/api/answer-keys/{key_id}", headers=headers).json()["questions"]
    assert len(questions) == 2
    q1, q2 = questions
    assert q1["question_number"] == 1
    assert q1["concepts"][0]["concept_code"] == "C1"
    assert q1["keywords"] == ["acknowledgement", "window"]
    assert q1["mandatory_terms"] == ["acknowledgement"]
    assert float(q1["maximum_marks"]) == 4
    assert q2["diagrams"] == []  # fake fixture has a hint but no crop was extracted from blank page

    # Teacher review corrections persist and lock status to reviewed.
    reviewed = client.patch(
        f"/api/answer-keys/{key_id}/review",
        headers=headers,
        json={
            "edits": [
                {
                    "question_number": 1,
                    "maximum_marks": 5,
                    "keywords": ["acknowledgement", "windowing", "retransmission"],
                    "expected_answer_text": "Corrected reference answer.",
                }
            ],
            "confirm": True,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["answer_key"]["status"] == "reviewed"
    edited_q1 = next(q for q in body["questions"] if q["question_number"] == 1)
    assert float(edited_q1["maximum_marks"]) == 5
    assert "retransmission" in edited_q1["keywords"]
    assert edited_q1["expected_answer_text"] == "Corrected reference answer."

    # Latest-by-assessment endpoint resolves to this key.
    latest = client.get(f"/api/assessments/{assessment_id}/answer-key", headers=headers).json()
    assert latest["answer_key"]["id"] == key_id

    # Unsupported type rejected up front.
    bad = client.post(
        f"/api/assessments/{assessment_id}/answer-key",
        headers=headers,
        files={"file": ("key.xlsx", b"binary", "application/octet-stream")},
    )
    assert bad.status_code == 422

    deleted = client.delete(f"/api/assessments/{assessment_id}", headers=headers)
    assert deleted.status_code == 200
