"""Milestone 13 integration: teacher review workflow against LIVE Supabase.

Configures an assessment, opens a pending review for a question, then a
teacher approves and later overrides one — asserting the full audit trail,
final-result record, and WAITING_FOR_REVIEW -> completed transition (#53/#85).
"""

from __future__ import annotations

import io
import json
import os
import time
import uuid
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


def _configure_assessment(client, headers: dict[str, str]) -> str:
    from tests.integration.test_api_m5 import POLICIES

    assessment_id = client.post("/api/assessments", headers=headers, json={}).json()["assessment"]["id"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("24MT010.pdf", _make_pdf("student paper"))
    upload = client.post(
        f"/api/assessments/{assessment_id}/student-zip",
        headers=headers,
        files={"file": ("papers.zip", buffer.getvalue(), "application/zip")},
    )
    assert upload.json()["valid"] == 1
    key_id = client.post(
        f"/api/assessments/{assessment_id}/answer-key",
        headers=headers,
        files={"file": ("key.pdf", _make_pdf("answer key"), "application/pdf")},
    ).json()["answer_key"]["id"]
    for _ in range(50):
        meta = client.get(f"/api/answer-keys/{key_id}", headers=headers).json()["answer_key"]
        if meta["status"] != "parsing":
            break
        time.sleep(0.1)
    assert meta["status"] == "parsed"
    client.patch(f"/api/answer-keys/{key_id}/review", headers=headers, json={"edits": [], "confirm": True})
    client.put(f"/api/assessments/{assessment_id}/policies", headers=headers, json=POLICIES)
    details = client.patch(
        f"/api/assessments/{assessment_id}",
        headers=headers,
        json={"class_name": "TY-REV", "subject_name": "Networks"},
    )
    assert details.status_code == 200
    finalized = client.post(f"/api/assessments/{assessment_id}/finalize", headers=headers, json={})
    assert finalized.status_code == 200, finalized.text
    return assessment_id


async def _db_pool():
    """Fresh asyncpg pool on the TEST's loop (the app pool lives on TestClient's loop)."""
    import asyncpg

    load_env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            load_env[key.strip()] = value.strip().strip('"')
    dsn = (
        os.environ.get("DATABASE_URL")
        or load_env.get("DATABASE_URL")
        or load_env.get("DATABASE_URL_POOLER")
    )
    # pgbouncer transaction poolers do not support prepared statements (#97).
    return await asyncpg.create_pool(dsn, statement_cache_size=0)


async def test_review_approve_and_override_live(client) -> None:
    headers = _auth_headers()
    assessment_id = _configure_assessment(client, headers)

    # Open the queue so submissions settle into processing-aware states.
    started = client.post(f"/api/assessments/{assessment_id}/start", headers=headers)
    assert started.status_code == 202

    # Simulate the worker: seed an AI evaluation result + open a pending review
    # for the single student on Q1 through the review bridge (#85).
    roster = client.get(f"/api/assessments/{assessment_id}/students", headers=headers).json()
    submission_id = roster[0]["id"]

    pool = await _db_pool()
    try:
        result_id = await pool.fetchval(
            """
            insert into evaluation_results
                (submission_id, assessment_id, question_id, proposed_marks, marks_maximum, model_id, schema_version)
            values ($1::uuid, $2::uuid, 'Q1', 3.5, 4, 'mock', 'evaluation-result-v1')
            returning id
            """,
            uuid.UUID(submission_id),
            uuid.UUID(assessment_id),
        )

        # Bridge: open pending review + submission -> waiting_for_review.
        await pool.execute(
            """
            insert into teacher_reviews
                (result_id, assessment_id, submission_id, question_id, status, reasons)
            values ($1::uuid, $2::uuid, $3::uuid, 'Q1', 'pending', $4::jsonb)
            """,
            result_id,
            uuid.UUID(assessment_id),
            uuid.UUID(submission_id),
            json.dumps(["major_grader_disagreement"]),
        )
        await pool.execute(
            """update submissions set status = 'waiting_for_review' where id = $1::uuid""",
            uuid.UUID(submission_id),
        )

        # 1) Pending review appears in the assessment list.
        pending = client.get(
            f"/api/assessments/{assessment_id}/reviews", headers=headers, params={"status": "pending"}
        ).json()
        assert len(pending) == 1 and pending[0]["question_id"] == "Q1"
        review_id = pending[0]["id"]

        # 2) Detail endpoint returns overrides (empty initially).
        detail = client.get(f"/api/reviews/{review_id}", headers=headers).json()["review"]
        assert detail["roll_number"] == "24MT010" and detail["overrides"] == []

        # 3) Teacher approves -> final result uses the AI's proposed marks (source=review).
        approved = client.post(f"/api/reviews/{review_id}/approve", headers=headers, json={"note": "looks correct"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["review"]["status"] == "approved"
        proven = await pool.fetchrow(
            """select marks_awarded, source, review_id, version from final_results
               where submission_id = $1::uuid and question_id = 'Q1'""",
            uuid.UUID(submission_id),
        )
        assert float(proven["marks_awarded"]) == 3.5 and proven["source"] == "review"
        assert str(proven["review_id"]) == review_id

        # 4) Re-approve must be refused (already resolved).
        again = client.post(f"/api/reviews/{review_id}/approve", headers=headers, json={})
        assert again.status_code == 409

        # 5) Open a second review to exercise the override path with final_marks.
        await pool.execute(
            """
            insert into teacher_reviews
                (result_id, assessment_id, submission_id, question_id, status, reasons)
            values ($1::uuid, $2::uuid, $3::uuid, 'Q2', 'pending', $4::jsonb)
            """,
            result_id,
            uuid.UUID(assessment_id),
            uuid.UUID(submission_id),
            json.dumps(["mapping_uncertain"]),
        )
        await pool.execute(
            """update submissions set status = 'waiting_for_review' where id = $1::uuid""",
            uuid.UUID(submission_id),
        )
        pending2 = client.get(
            f"/api/assessments/{assessment_id}/reviews", headers=headers, params={"status": "pending"}
        ).json()
        review2_id = next(r["id"] for r in pending2 if r["question_id"] == "Q2")

        overridden = client.post(
            f"/api/reviews/{review2_id}/override",
            headers=headers,
            json={"final_marks": 4.0, "note": "student corrected the diagram", "overrides": []},
        )
        assert overridden.status_code == 200, overridden.text
        assert overridden.json()["review"]["status"] == "overridden"

        # 6) Audit trail recorded both the review decision and the marks override.
        audit = await pool.fetch(
            """select action from audit_events
               where entity_type = 'teacher_review' and entity_id = any(($1::uuid[])::text[])
               order by created_at""",
            [uuid.UUID(review_id), uuid.UUID(review2_id)],
        )
        actions = [a["action"] for a in audit]
        assert "review_approved" in actions
        assert "review_overridden" in actions

        # 7) Submission resolved back to completed (#85).
        status_body = client.get(f"/api/assessments/{assessment_id}/status", headers=headers).json()
        assert status_body["summary"]["completed"] == 1
        assert status_body["summary"]["waiting_for_review"] == 0
    finally:
        await pool.close()
