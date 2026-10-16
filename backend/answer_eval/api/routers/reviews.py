"""Teacher review endpoints (Milestone 13, specs #52/#53/#85).

Review records are created by the grading pipeline when risk routing flags a
question; teachers resolve them here. Every decision is ownership-checked,
transactional, and fully audited.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from answer_eval.api.deps import CurrentTeacher, require_database
from answer_eval.db.repositories import assessments as assessments_repo
from answer_eval.db.repositories import reviews as reviews_repo

router = APIRouter(tags=["reviews"])


class OverrideIn(BaseModel):
    target: str = Field(description="criterion | final_marks | ocr_text | mapping | diagram_status")
    target_key: str | None = None
    old_value: float | str | None = None
    new_value: float | str | None = None
    reason: str | None = None


class ApproveIn(BaseModel):
    note: str | None = None


class OverrideRequestIn(BaseModel):
    final_marks: float | None = Field(default=None, ge=0)
    overrides: list[OverrideIn] = Field(default_factory=list)
    note: str | None = None


@router.get("/assessments/{assessment_id}/reviews")
async def list_reviews(
    assessment_id: str,
    request: Request,
    teacher: CurrentTeacher,
    status: str | None = None,
) -> list[dict]:
    database = require_database(request)
    try:
        await assessments_repo.require_owned(
            database.pool, assessment_id=assessment_id, teacher_id=teacher.profile_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Assessment not found") from exc
    if status is not None and status not in ("pending", "approved", "overridden", "requeued"):
        raise HTTPException(status_code=422, detail="Invalid status filter")
    return await reviews_repo.list_for_assessment(database.pool, assessment_id, status=status)


async def _load_owned_review(database, review_id: str, teacher_profile_id: str) -> dict:
    review = await reviews_repo.get_review(database.pool, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    try:
        await assessments_repo.require_owned(
            database.pool, assessment_id=review["assessment_id"], teacher_id=teacher_profile_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Review not found") from exc
    return review


@router.get("/reviews/{review_id}")
async def get_review(review_id: str, request: Request, teacher: CurrentTeacher) -> dict:
    database = require_database(request)
    review = await _load_owned_review(database, review_id, teacher.profile_id)
    overrides = await database.pool.fetch(
        """
        select id, target, target_key, old_value, new_value, reason, created_at
        from teacher_overrides where review_id = $1::uuid order by created_at
        """,
        __import__("uuid").UUID(review_id),
    )
    review["overrides"] = [
        {
            "id": str(o["id"]),
            "target": o["target"],
            "target_key": o["target_key"],
            "old_value": o["old_value"],
            "new_value": o["new_value"],
            "reason": o["reason"],
        }
        for o in overrides
    ]
    return {"review": review}


@router.post("/reviews/{review_id}/approve")
async def approve_review(review_id: str, body: ApproveIn, request: Request, teacher: CurrentTeacher) -> dict:
    database = require_database(request)
    review = await _load_owned_review(database, review_id, teacher.profile_id)
    if review["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Review already resolved as '{review['status']}'")
    resolved = await reviews_repo.resolve_review(
        database.pool,
        review_id=review_id,
        reviewer_id=teacher.profile_id,
        decision="approved",
        note=body.note,
    )
    await reviews_repo.refresh_assessment_status(database.pool, review["assessment_id"])
    return {"review": resolved}


@router.post("/reviews/{review_id}/override")
async def override_review(review_id: str, body: OverrideRequestIn, request: Request, teacher: CurrentTeacher) -> dict:
    database = require_database(request)
    review = await _load_owned_review(database, review_id, teacher.profile_id)
    if review["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Review already resolved as '{review['status']}'")
    if body.final_marks is None and not body.overrides:
        raise HTTPException(status_code=422, detail="Provide final_marks or at least one override")
    for item in body.overrides:
        if item.target not in reviews_repo.ALLOWED_OVERRIDE_TARGETS:
            raise HTTPException(status_code=422, detail=f"Unsupported override target '{item.target}'")
    try:
        resolved = await reviews_repo.resolve_review(
            database.pool,
            review_id=review_id,
            reviewer_id=teacher.profile_id,
            decision="overridden",
            note=body.note,
            final_marks=body.final_marks,
            overrides=[o.model_dump() for o in body.overrides],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await reviews_repo.refresh_assessment_status(database.pool, review["assessment_id"])
    return {"review": resolved}
