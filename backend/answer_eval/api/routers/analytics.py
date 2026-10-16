"""Analytics endpoints (Milestone 18, specs #75-#79)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from answer_eval.api.deps import CurrentTeacher, require_database
from answer_eval.db.repositories import analytics as analytics_repo
from answer_eval.db.repositories import assessments as assessments_repo

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/classes/{assessment_id}")
async def class_analytics(assessment_id: str, request: Request, teacher: CurrentTeacher) -> dict:
    database = require_database(request)
    try:
        await assessments_repo.require_owned(
            database.pool, assessment_id=assessment_id, teacher_id=teacher.profile_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Assessment not found") from exc
    return await analytics_repo.class_analytics(database.pool, assessment_id)


@router.get("/students/{submission_id}")
async def student_analytics(submission_id: str, request: Request, teacher: CurrentTeacher) -> dict:
    database = require_database(request)
    result = await analytics_repo.student_analytics(database.pool, submission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Submission not found")
    try:
        await assessments_repo.require_owned(
            database.pool,
            assessment_id=str(result["assessment_id"]),
            teacher_id=teacher.profile_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Submission not found") from exc
    return result
