"""API app wiring tests: health, auth guards, profile endpoints (DB faked)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from answer_eval.api.config import ApiSettings
from answer_eval.api.deps import TeacherContext, get_current_teacher
from answer_eval.api.main import create_app
from answer_eval.db.pool import Database

SECRET = "unit-test-secret"
NOW = int(time.time())


class FakeDatabase(Database):
    """Stand-in exposing a connected flag; repo calls are overridden in tests."""

    def __init__(self) -> None:
        super().__init__("fake://")

    @property
    def connected(self) -> bool:
        return True

    @property
    def pool(self) -> Any:  # tests patch repository functions; pool never used
        return object()


@pytest.fixture()
def client() -> Iterator[tuple[TestClient, dict[str, Any]]]:
    settings = ApiSettings(supabase_url="https://project.supabase.co", supabase_jwt_secret=SECRET)
    app = create_app(settings, database=FakeDatabase())
    teacher = TeacherContext(
        profile_id="11111111-1111-1111-1111-111111111111",
        user_id="user-1",
        email="teacher@example.edu",
        full_name="Dr. Test",
    )
    captured: dict[str, Any] = {}

    async def override() -> TeacherContext:
        captured["calls"] = captured.get("calls", 0) + 1
        return teacher

    app.dependency_overrides[get_current_teacher] = override
    with TestClient(app) as test_client:
        yield test_client, captured


def test_healthz_reports_database_state(client: tuple[TestClient, dict[str, Any]]) -> None:
    http, _ = client
    response = http.get("/api/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True


def test_profile_requires_token() -> None:
    settings = ApiSettings(supabase_jwt_secret=SECRET)
    app = create_app(settings, database=FakeDatabase())
    with TestClient(app) as http:
        response = http.get("/api/profile")
        assert response.status_code == 401


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_me_returns_profile_shape(
    monkeypatch: pytest.MonkeyPatch,
    client: tuple[TestClient, dict[str, Any]],
) -> None:
    http, _ = client

    async def fake_get_profile(pool: Any, user_id: str) -> dict[str, Any]:  # noqa: ARG001
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "teacher@example.edu",
            "full_name": "Dr. Test",
            "institution_id": None,
            "role": "teacher",
            "department_ids": ["dept-cse"],
            "subjects": ["Machine Learning"],
        }

    from answer_eval.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router.profiles_repo, "get_profile", fake_get_profile)
    token = pyjwt.encode({"sub": "user-1", "exp": NOW + 300}, SECRET, algorithm="HS256")
    response = http.get("/api/auth/me", headers=_auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "user-1"
    assert body["profile"]["email"] == "teacher@example.edu"
    assert body["profile"]["department_ids"] == ["dept-cse"]


def test_sync_profile_updates_fields(
    monkeypatch: pytest.MonkeyPatch,
    client: tuple[TestClient, dict[str, Any]],
) -> None:
    http, _ = client

    async def fake_update_profile(pool: Any, user_id: str, **fields: Any) -> dict[str, Any]:  # noqa: ARG001
        assert fields["full_name"] == "Dr. Renamed"
        assert fields["subjects"] == ["DBMS"]
        return {
            "id": user_id,
            "email": "teacher@example.edu",
            "full_name": fields["full_name"],
            "institution_id": None,
            "role": "teacher",
            "department_ids": [],
            "subjects": fields["subjects"],
        }

    from answer_eval.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router.profiles_repo, "update_profile", fake_update_profile)
    token = pyjwt.encode({"sub": "user-1", "exp": NOW + 300}, SECRET, algorithm="HS256")
    response = http.post(
        "/api/auth/sync-profile",
        headers=_auth_header(token),
        json={"full_name": "Dr. Renamed", "subjects": ["DBMS"]},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Dr. Renamed"


def test_invalid_token_rejected_without_override() -> None:
    settings = ApiSettings(supabase_jwt_secret=SECRET)
    app = create_app(settings, database=FakeDatabase())
    with TestClient(app) as http:
        response = http.get("/api/profile", headers=_auth_header(_hs_bad()))
        assert response.status_code == 401


def _hs_bad() -> str:
    return pyjwt.encode({"sub": "user-2", "exp": NOW + 300}, "wrong-secret", algorithm="HS256")


def test_migration_files_cover_expected_tables() -> None:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "answer_eval" / "db" / "migrations"
    schema = (root / "0001_schema.sql").read_text(encoding="utf-8").lower()
    rls = (root / "0002_rls.sql").read_text(encoding="utf-8").lower()
    expected_tables = [
        "profiles", "institutions", "classes", "subjects", "teacher_classes",
        "teacher_subjects", "assessments", "assessment_students", "answer_keys",
        "questions", "question_answer_keys", "expected_concepts", "keywords",
        "mandatory_terms", "strictness_policies", "word_count_policies",
        "diagram_policies", "diagram_requirements", "answer_key_diagrams",
        "submissions", "submission_files", "submission_pages", "question_spans",
        "question_regions", "ocr_results", "student_diagrams",
        "reconstructed_answers", "evaluation_jobs", "question_jobs", "job_events",
        "evaluation_results", "criterion_scores", "verification_results",
        "verification_comparisons", "risk_results", "teacher_reviews",
        "teacher_overrides", "final_results", "student_totals", "worker_nodes",
        "worker_heartbeats", "audit_events",
    ]
    for table in expected_tables:
        assert f"create table public.{table} (" in schema, f"missing table {table}"
    for table in expected_tables:
        if table in {"worker_nodes", "worker_heartbeats", "audit_events"}:
            continue  # infrastructure tables intentionally have no policies
    assert rls.count("enable row level security") >= len(expected_tables)
    assert "create policy assessments_select_access" in rls
