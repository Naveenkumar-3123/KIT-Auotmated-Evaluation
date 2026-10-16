"""Teacher profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from answer_eval.api.deps import CurrentTeacher, require_database
from answer_eval.api.models import ProfileOut, ProfileUpdateIn
from answer_eval.db.repositories import profiles as profiles_repo

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
async def get_my_profile(request: Request, teacher: CurrentTeacher) -> ProfileOut:
    database = require_database(request)
    row = await profiles_repo.get_profile(database.pool, teacher.profile_id)
    return ProfileOut.of(row or {})


@router.patch("", response_model=ProfileOut)
async def update_my_profile(
    body: ProfileUpdateIn,
    request: Request,
    teacher: CurrentTeacher,
) -> ProfileOut:
    database = require_database(request)
    row = await profiles_repo.update_profile(
        database.pool,
        teacher.profile_id,
        full_name=body.full_name,
        department_ids=body.department_ids,
        subjects=body.subjects,
        institution_id=body.institution_id if body.institution_id is not None else profiles_repo._UNSET,
    )
    return ProfileOut.of(row or {})
