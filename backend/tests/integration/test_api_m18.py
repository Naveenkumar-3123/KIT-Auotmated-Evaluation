"""Milestone 18 integration: class/student analytics against LIVE Supabase."""

from __future__ import annotations

import io
import json
import os
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


async def test_class_and_student_analytics_live(client) -> None:
    headers = _auth_headers()
    assessment_id = client.post("/api/assessments", headers=headers, json={}).json()["assessment"]["id"]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("24AN001.pdf", _make_pdf("student one"))
        archive.writestr("24AN002.pdf", _make_pdf("student two"))
    client.post(
        f"/api/assessments/{assessment_id}/student-zip",
        headers=headers,
        files={"file": ("papers.zip", buffer.getvalue(), "application/zip")},
    )
    roster = client.get(f"/api/assessments/{assessment_id}/students", headers=headers).json()
    by_roll = {r["roll_number"]: r["id"] for r in roster}

    # Simulate the worker: both students completed with AI criteria snapshots.
    pool = await _db_pool()
    try:
        criteria_high = json.dumps([
            {"criterion_id": "C1", "criterion": "retransmission", "status": "fully_supported",
             "proposed_marks": 4, "maximum_marks": 4},
            {"criterion_id": "C2", "criterion": "timer usage", "status": "fully_supported",
             "proposed_marks": 4, "maximum_marks": 4},
        ])
        criteria_low = json.dumps([
            {"criterion_id": "C1", "criterion": "retransmission", "status": "unsupported",
             "proposed_marks": 0, "maximum_marks": 4},
            {"criterion_id": "C2", "criterion": "timer usage", "status": "fully_supported",
             "proposed_marks": 1, "maximum_marks": 4},
        ])
        for sub_id, marks, crit in [
            (by_roll["24AN001"], 8.0, criteria_high),
            (by_roll["24AN002"], 1.0, criteria_low),
        ]:
            await pool.execute(
                """insert into evaluation_results
                     (submission_id, assessment_id, question_id, proposed_marks, marks_maximum, criteria)
                   values ($1::uuid, $2::uuid, 'Q1', $3, 8, $4::jsonb)""",
                uuid.UUID(sub_id), uuid.UUID(assessment_id), marks, crit,
            )
            await pool.execute(
                """insert into final_results
                     (submission_id, assessment_id, question_id, marks_awarded, marks_maximum, source)
                   values ($1::uuid, $2::uuid, 'Q1', $3, 8, 'ai')""",
                uuid.UUID(sub_id), uuid.UUID(assessment_id), marks,
            )
            await pool.execute(
                "update submissions set status = 'completed' where id = $1::uuid", uuid.UUID(sub_id),
            )
    finally:
        await pool.close()

    class_stats = client.get(f"/api/analytics/classes/{assessment_id}", headers=headers).json()
    assert class_stats["based_on_completed"] == 2 and class_stats["partial_note"] is None
    assert class_stats["class_average"] == 4.5
    assert class_stats["highest"] == 8.0 and class_stats["lowest"] == 1.0
    assert class_stats["pass_percentage_actual"] == 50.0  # default pass mark 40%
    q = class_stats["per_question"][0]
    assert q["question_id"] == "Q1" and float(q["average_awarded"]) == 4.5
    concepts = {c["criterion_id"]: c for c in class_stats["concept_difficulty"]}
    assert concepts["C1"]["attainment_pct"] == 50.0  # (100 + 0) / 2
    assert concepts["C2"]["attainment_pct"] == 62.5  # (100 + 25) / 2

    student = client.get(f"/api/analytics/students/{by_roll['24AN001']}", headers=headers).json()
    assert student["rank"] == 1 and student["passed"] is True
    assert student["percentage"] == 100.0
    assert any(s["criterion_id"] == "C1" for s in student["strengths"])

    weak = client.get(f"/api/analytics/students/{by_roll['24AN002']}", headers=headers).json()
    assert weak["rank"] == 2 and weak["passed"] is False
    assert any(m["criterion_id"] == "C1" for m in weak["missing_concepts"])
