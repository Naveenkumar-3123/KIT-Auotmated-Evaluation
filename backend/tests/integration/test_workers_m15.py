"""Milestone 15 integration: worker registration/heartbeat/fleet against LIVE Supabase.

Covers #58 register (token issued once), #59 heartbeat, #64 token auth
(rejects bad tokens), and the Computers-page fleet view (#60).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from answer_eval.answerkey.parser import FakeAnswerKeyParserAgent
from answer_eval.api.main import create_app
from answer_eval.storage import LocalStorageProvider


async def _db_pool():
    """Fresh asyncpg pool on the TEST's loop (pgbouncer-safe)."""
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
    return await asyncpg.create_pool(dsn, statement_cache_size=0)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("SUPABASE_URL") or "") and not Path(".env").exists(),
        reason="live credentials required",
    ),
]


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(
        storage=LocalStorageProvider(tmp_path / "storage"),
        answer_key_parser_factory=FakeAnswerKeyParserAgent,
    )
    with TestClient(app) as test_client:
        yield test_client


def _teacher_headers() -> dict[str, str]:
    import httpx as _httpx

    load_env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            load_env[key.strip()] = value.strip().strip('"')
    supabase_url = os.environ.get("SUPABASE_URL") or load_env.get("SUPABASE_URL", "")
    anon_key = os.environ.get("SUPABASE_ANON_KEY") or load_env.get("SUPABASE_ANON_KEY", "")
    response = _httpx.post(
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


async def test_worker_register_heartbeat_fleet_live(client) -> None:
    teacher = _teacher_headers()
    worker_id = f"worker-t{uuid.uuid4().hex[:8]}"

    # 1) Register: token issued exactly once (#58/#64).
    registered = client.post(
        "/api/workers/register",
        json={
            "worker_id": worker_id,
            "hostname": "eval-pc-01",
            "hardware": {"cpu": "8 cores", "ram_gb": 32.0, "gpu": "RTX 4060", "vram_gb": 8.0},
            "model_profile": "qwen_vl_4b_q8",
            "capabilities": ["vision", "ocr", "evaluation"],
        },
    )
    assert registered.status_code == 200, registered.text
    body = registered.json()
    assert body["worker"]["worker_id"] == worker_id
    token = body["token"]
    assert token

    auth = {"Authorization": f"Bearer {worker_id}:{token}"}

    # 2) Heartbeat with valid credentials is accepted (#59).
    beat = client.post(
        "/api/workers/heartbeat",
        headers=auth,
        json={"stage": "ocr", "progress": 42.0, "ram_used_gb": 12.5, "vram_used_gb": 6.1},
    )
    assert beat.status_code == 200, beat.text
    assert beat.json()["ok"] is True

    # 3) Bad token is rejected (#64).
    bad = client.post(
        "/api/workers/heartbeat",
        headers={"Authorization": f"Bearer {worker_id}:wrong-token"},
        json={"stage": "idle"},
    )
    assert bad.status_code == 403

    # 4) Fleet view shows the online worker with its latest heartbeat (#60).
    fleet = client.get("/api/workers", headers=teacher).json()
    mine = next(w for w in fleet["workers"] if w["worker_id"] == worker_id)
    assert mine["online"] is True
    assert mine["hardware"]["gpu"] == "RTX 4060"
    assert mine["model_profile"] == "qwen_vl_4b_q8"
    assert mine["stage"] == "ocr"
    assert float(mine["progress"]) == 42.0
    assert fleet["online_count"] >= 1


async def test_fleet_resolves_current_student_roll_number(client) -> None:
    """A busy worker's heartbeat resolves to the student it is grading (#60/#61)."""

    teacher = _teacher_headers()
    worker_id = f"worker-t{uuid.uuid4().hex[:8]}"
    registered = client.post("/api/workers/register", json={"worker_id": worker_id, "hostname": "busy-pc"})
    assert registered.status_code == 200
    token = registered.json()["token"]
    auth = {"Authorization": f"Bearer {worker_id}:{token}"}

    pool = await _db_pool()
    try:
        profile_id = await pool.fetchval("select id from profiles order by created_at limit 1")
        assessment_id = await pool.fetchval(
            """insert into assessments (teacher_id, title) values ($1::uuid, 'fleet check')
               returning id""",
            profile_id,
        )
        submission_id = await pool.fetchval(
            """insert into submissions
                 (assessment_id, roll_number, status, pdf_object_key)
               values ($1::uuid, '24FLT001', 'processing', 'original-pdfs/fleet-check.pdf')
               returning id""",
            assessment_id,
        )
        job_id = await pool.fetchval(
            """insert into evaluation_jobs (assessment_id, submission_id, status)
               values ($1::uuid, $2::uuid, 'claimed') returning id""",
            assessment_id,
            submission_id,
        )

        beat = client.post(
            "/api/workers/heartbeat",
            headers=auth,
            json={"stage": "evaluating", "current_job_id": str(job_id), "progress": 55.0},
        )
        assert beat.status_code == 200, beat.text

        fleet = client.get("/api/workers", headers=teacher).json()
        mine = next(w for w in fleet["workers"] if w["worker_id"] == worker_id)
        assert mine["roll_number"] == "24FLT001"
        assert mine["current_job_id"] == str(job_id)

        await pool.execute("delete from assessments where id = $1", assessment_id)
    finally:
        await pool.execute("delete from worker_nodes where worker_id = $1", worker_id)
        await pool.close()
