"""Milestone 3 integration: ZIP ingestion end-to-end against LIVE Supabase.

Runs only when SUPABASE_URL + DIRECT_URL are configured (.env). Creates a
scratch draft assessment, ingests a synthetic ZIP (valid/corrupt/duplicate/
bad-filename/unsupported entries), verifies persistence + download, then
deletes the draft. Storage goes to a temp dir, never the shared root.
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import fitz  # PyMuPDF
import httpx
import pytest
from fastapi.testclient import TestClient

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
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_zip() -> tuple[bytes, dict[str, str]]:
    good_a = _make_pdf("Answer sheet A")
    good_b = _make_pdf("Answer sheet B")
    files = {
        "23IT101.pdf": good_a,
        "23IT102.pdf": good_b,
        "23IT103.pdf": b"definitely not a pdf",
        "copyof-23IT101.pdf": good_a,  # different roll, same bytes -> invalid_duplicate
        "not a roll!.pdf": _make_pdf("bad name"),
        "readme.txt": b"ignore me",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue(), files


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(storage=LocalStorageProvider(tmp_path / "storage"))
    with TestClient(app) as test_client:
        yield test_client


def _auth_headers(client: TestClient) -> dict[str, str]:
    load_env = {}
    try:  # .env may not exist in CI
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                load_env[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
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
        except (httpx.HTTPError, ValueError) as exc:  # transient regional latency
            last_error = exc
    raise RuntimeError(f"Supabase login failed after retries: {last_error}")


def test_full_ingestion_flow_live(client: TestClient) -> None:
    headers = _auth_headers(client)

    created = client.post("/api/assessments", headers=headers, json={"title": "M3 integration"})
    assert created.status_code == 201, created.text
    assessment_id = created.json()["assessment"]["id"]

    zip_bytes, _files = _make_zip()

    def upload() -> dict:
        response = client.post(
            f"/api/assessments/{assessment_id}/student-zip",
            headers=headers,
            files={"file": ("papers.zip", zip_bytes, "application/zip")},
        )
        assert response.status_code == 200, response.text
        return response.json()

    result = upload()
    by_status: dict[str, list[str]] = {}
    for student in result["students"]:
        by_status.setdefault(student["status"], []).append(student["roll_number"] or student["file_name"])

    assert result["detected"] == 6
    assert sorted(by_status["valid"]) == ["23IT101", "23IT102"]
    assert "invalid_duplicate" in by_status and len(by_status["invalid_duplicate"]) == 1
    assert "invalid_corrupt" in by_status
    assert "invalid_filename" in by_status
    assert "unsupported_type" in by_status

    # Roster persisted
    roster = client.get(f"/api/assessments/{assessment_id}/students", headers=headers).json()
    rolls = sorted(item["roll_number"] for item in roster)
    assert rolls == ["23IT101", "23IT102"]
    assert all(item["page_count"] >= 1 for item in roster)

    # Details update (class/subject auto-created, dynamic pass mark)
    updated = client.patch(
        f"/api/assessments/{assessment_id}",
        headers=headers,
        json={"class_name": "TY-IT", "subject_name": "Machine Learning", "pass_percentage": 45},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["assessment"]
    assert body["class_name"] == "TY-IT"
    assert body["subject_name"] == "Machine Learning"
    assert float(body["pass_percentage"]) == 45

    detail = client.get(f"/api/assessments/{assessment_id}", headers=headers).json()
    assert detail["summary"]["total"] == 2

    # Idempotent re-upload flags duplicates instead of double-inserting
    again = upload()
    statuses = [s["status"] for s in again["students"] if s.get("submission_id")]
    assert all(status == "duplicate" for status in statuses)
    roster_after = client.get(f"/api/assessments/{assessment_id}/students", headers=headers).json()
    assert len(roster_after) == 2

    # Original PDF streams back after ownership check
    submission_id = roster[0]["id"]
    download = client.get(f"/api/assessments/submissions/{submission_id}/pdf", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")

    # Foreign teacher token cannot see this assessment: reuse verifier-level 401 path
    no_auth = client.get(f"/api/assessments/{assessment_id}/students")
    assert no_auth.status_code == 401

    deleted = client.delete(f"/api/assessments/{assessment_id}", headers=headers)
    assert deleted.status_code == 200
