"""FastAPI dependencies: bearer-token extraction -> verified teacher context."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from answer_eval.api.auth import AuthError
from answer_eval.db.pool import Database
from answer_eval.db.repositories import profiles as profiles_repo

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TeacherContext:
    """Identity derived from a verified Supabase JWT — never from payloads."""

    profile_id: str
    user_id: str
    email: str
    full_name: str


def require_database(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None or not database.connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )
    return database


async def get_current_teacher(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> TeacherContext:
    if credentials is None or (credentials.scheme or "").lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    verifier = getattr(request.app.state, "verifier", None)
    if verifier is None:
        raise HTTPException(status_code=503, detail="Auth verifier unavailable")

    try:
        claims = verifier.verify(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    database = require_database(request)
    metadata = claims.get("user_metadata") or {}
    raw_departments = metadata.get("department_ids")
    raw_subjects = metadata.get("subjects")
    department_ids = [str(item) for item in raw_departments] if isinstance(raw_departments, list) else []
    subjects = [str(item) for item in raw_subjects] if isinstance(raw_subjects, list) else []
    try:
        row = await profiles_repo.ensure_profile(
            database.pool,
            user_id=str(claims["sub"]),
            email=str(claims.get("email") or ""),
            full_name=str(metadata.get("full_name") or ""),
            department_ids=department_ids,
            subjects=subjects,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return TeacherContext(
        profile_id=str(row["id"]),
        user_id=str(claims["sub"]),
        email=str(row.get("email") or ""),
        full_name=str(row.get("full_name") or ""),
    )


CurrentTeacher = Annotated[TeacherContext, Depends(get_current_teacher)]
