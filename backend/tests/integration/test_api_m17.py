"""Milestone 17 integration: incremental results read-model against LIVE Supabase."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import fitz
import httpx
import pytest
from fastapi.testclient import TestClient

from answer_eval.answerkey.parser import FakeAnswerKeyParserAgent
from answer_eval.api.main import create_app
from answer_eval.storage import LocalStorageProvider
from tests.integration.test_workers_m15 import _db_pool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("SUPABASE_URL") or "") and not Path(".env").exists(),
        reason="live credentials required",
    ),
]


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
    response = httpx.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon_key},
        json={
            "email": os.getenv("SMOKE_USER_EMAIL", "evalai-smoke@test.evalai.local"),
            "password": os.getenv("SMOKE_USER_PASSWORD", "EvalAI-Smoke-2026!"),
        },
        timeout=30,
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_incremental_results_live(client) -> None:
    import json as _json
    import uuid as _uuid

    headers = _auth_headers()
    assessment_id = client.post("/api/assessments", headers=headers, json={}).json()["assessment"]["id"]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("24RS001.pdf", _make_pdf("student one"))
        archive.writestr("24RS002.pdf", _make_pdf("student two"))
    upload = client.post(
        f"/api/assessments/{assessment_id}/student-zip",
        headers=headers,
        files={"file": ("papers.zip", buffer.getvalue(), "application/zip")},
    )
    assert upload.json()["valid"] == 2

    roster = client.get(f"/api/assessments/{assessment_id}/students", headers=headers).json()
    by_roll = {r["roll_number"]: r["id"] for r in roster}
    sub1 = by_roll["24RS001"]

    # Incremental state BEFORE grading: both ready, no marks.
    results = client.get(f"/api/assessments/{assessment_id}/results", headers=headers).json()
    assert results["summary"]["ready"] == 2
    for student in results["students"]:
        assert student["total"] == 0.0 and student["rank"] is None

    # Simulate the worker finishing student 1 (completed + final result).
    pool_factory = _db_pool

    async def seed() -> None:
        pool = await pool_factory()
        try:
            er_id = await pool.fetchval(
                """
                insert into evaluation_results
                    (submission_id, assessment_id, question_id, proposed_marks, marks_maximum, criteria)
                values ($1::uuid, $2::uuid, 'Q1', 3.5, 4, $3::jsonb)
                returning id
                """,
                _uuid.UUID(sub1),
                _uuid.UUID(assessment_id),
                _json.dumps(
                    [{"criterion_id": "C1", "status": "fully_supported", "proposed_marks": 3.5, "maximum_marks": 4}]
                ),
            )
            await pool.execute(
                """
                insert into final_results
                    (submission_id, assessment_id, question_id, marks_awarded, marks_maximum,
                     source, result_id)
                values ($1::uuid, $2::uuid, 'Q1', 3.5, 4, 'ai', $3::uuid)
                """,
                _uuid.UUID(sub1),
                _uuid.UUID(assessment_id),
                er_id,
            )
            await pool.execute(
                "update submissions set status = 'completed' where id = $1::uuid",
                _uuid.UUID(sub1),
            )
        finally:
            await pool.close()

    import asyncio

    asyncio.run(seed())

    # Incremental view: completed student has marks + rank; other stays ready.
    results2 = client.get(f"/api/assessments/{assessment_id}/results", headers=headers).json()
    assert results2["summary"]["completed"] == 1
    assert results2["summary"]["ready"] == 1
    students = {s["roll_number"]: s for s in results2["students"]}
    assert students["24RS001"]["total"] == 3.5
    assert students["24RS001"]["rank"] == 1
    assert students["24RS002"]["rank"] is None
    assert students["24RS002"]["total"] == 0.0

    # Question-level detail (#74): AI criteria attached to the final result.
    detail = client.get(
        f"/api/assessments/{assessment_id}/results/{sub1}", headers=headers
    ).json()
    q = detail["questions"][0]
    assert q["final_marks"] == 3.5 and q["source"] == "ai"
    assert q["criteria"][0]["criterion_id"] == "C1"

    # Cross-assessment guard.
    other = client.post("/api/assessments", headers=headers, json={}).json()["assessment"]["id"]
    wrong = client.get(f"/api/assessments/{other}/results/{sub1}", headers=headers)
    assert wrong.status_code == 404
