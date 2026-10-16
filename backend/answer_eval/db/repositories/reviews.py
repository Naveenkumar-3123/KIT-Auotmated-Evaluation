"""Teacher review persistence + resolution (Milestone 13).

Every teacher decision is audited (#53): the original AI result is never
overwritten — corrections live in teacher_overrides, decisions in
teacher_reviews, and both are mirrored into audit_events. Final results point
at the approved version. WAITING_FOR_REVIEW is a valid state that resolves
back to completed (#85).
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg

ALLOWED_OVERRIDE_TARGETS = ("criterion", "final_marks", "ocr_text", "mapping", "diagram_status")


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def upsert_pending(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    submission_id: str,
    question_id: str,
    reasons: list[str],
    result_id: str | None = None,
) -> dict[str, Any]:
    """Create (or fetch the existing pending) review for one student/question."""
    row = await pool.fetchrow(
        """
        insert into teacher_reviews
            (result_id, assessment_id, submission_id, question_id, status, reasons)
        values ($1::uuid, $2::uuid, $3::uuid, $4, 'pending', $5::jsonb)
        returning id, assessment_id, submission_id, question_id, status, reasons, created_at
        """,
        _uuid(result_id) if result_id else None,
        _uuid(assessment_id),
        _uuid(submission_id),
        question_id,
        reasons,
    )
    return dict(row)


async def open_review_for_question(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    submission_id: str,
    question_id: str,
    reasons: list[str],
    result_id: str | None = None,
) -> dict[str, Any]:
    """Bridge the grading pipeline into teacher review (#85).

    Called by the worker/coordinator when a question's risk routing flags it:
    creates the pending review row and flips the submission to the valid
    WAITING_FOR_REVIEW state (never FAILED).
    """
    review = await upsert_pending(
        pool,
        assessment_id=assessment_id,
        submission_id=submission_id,
        question_id=question_id,
        reasons=reasons,
        result_id=result_id,
    )
    await pool.execute(
        """
        update submissions set status = 'waiting_for_review', status_detail = $3, updated_at = now()
         where id = $1::uuid and status not in ('waiting_for_review', 'completed')
        """,
        _uuid(submission_id),
        _uuid(assessment_id),
        f"pending teacher review: {question_id}",
    )
    return review


async def get_review(pool: asyncpg.Pool, review_id: str) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        select r.id, r.result_id, r.assessment_id, r.submission_id, r.question_id,
               r.status, r.reasons, r.reviewer_id, r.note, r.decided_at, r.created_at,
               s.roll_number
        from teacher_reviews r
        join submissions s on s.id = r.submission_id
        where r.id = $1::uuid
        """,
        _uuid(review_id),
    )
    return dict(row) if row else None


async def list_for_assessment(
    pool: asyncpg.Pool,
    assessment_id: str,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    query = """
        select r.id, r.result_id, r.submission_id, r.question_id, r.status, r.reasons,
               r.note, r.decided_at, r.created_at, s.roll_number
        from teacher_reviews r
        join submissions s on s.id = r.submission_id
        where r.assessment_id = $1::uuid
    """
    args: list[Any] = [_uuid(assessment_id)]
    if status:
        query += " and r.status = $2"
        args.append(status)
    query += " order by r.created_at desc"
    rows = await pool.fetch(query, *args)
    results = []
    for row in rows:
        item = dict(row)
        item["id"] = str(item["id"])
        item["submission_id"] = str(item["submission_id"])
        results.append(item)
    return results


async def _audit(
    connection: asyncpg.Connection,
    *,
    actor_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: str,
    before: Any,
    after: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    await connection.execute(
        """
        insert into audit_events (actor_id, action, entity_type, entity_id, before, after, metadata)
        values ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb)
        """,
        actor_id,
        action,
        entity_type,
        entity_id,
        before,
        after,
        metadata or {},
    )


async def _record_overrides(
    connection: asyncpg.Connection,
    *,
    review_id: str,
    reviewer_id: uuid.UUID,
    overrides: list[dict[str, Any]],
) -> None:
    for item in overrides:
        target = item.get("target")
        if target not in ALLOWED_OVERRIDE_TARGETS:
            raise ValueError(f"Unsupported override target '{target}'")
        await connection.execute(
            """
            insert into teacher_overrides
                (review_id, target, target_key, old_value, new_value, reason, reviewer_id)
            values ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
            """,
            _uuid(review_id),
            target,
            item.get("target_key"),
            item.get("old_value"),
            item.get("new_value"),
            item.get("reason"),
            reviewer_id,
        )


async def _final_marks_max(pool: asyncpg.Pool, assessment_id: str, question_number: int) -> float | None:
    row = await pool.fetchrow(
        """
        select rubric_snapshot->>'maximum_marks' as max_marks
        from question_policies
        where assessment_id = $1::uuid and question_number = $2
        order by version desc limit 1
        """,
        _uuid(assessment_id),
        question_number,
    )
    if row and row["max_marks"] is not None:
        return float(row["max_marks"])
    return None


def _question_number(question_id: str) -> int | None:
    digits = "".join(ch for ch in question_id if ch.isdigit())
    return int(digits) if digits else None


async def resolve_review(
    pool: asyncpg.Pool,
    *,
    review_id: str,
    reviewer_id: str,
    decision: str,  # approved | overridden
    note: str | None = None,
    final_marks: float | None = None,
    overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply a teacher decision transactionally with full audit trail (#53)."""
    review = await get_review(pool, review_id)
    if not review:
        raise LookupError("review_not_found")
    if review["status"] != "pending":
        raise ValueError(f"Review already resolved as '{review['status']}'")

    overrides = overrides or []
    async with pool.acquire() as connection, connection.transaction():
        before = {"status": review["status"], "note": review["note"]}
        await connection.execute(
            """
                update teacher_reviews
                   set status = $2, reviewer_id = $3::uuid, note = $4, decided_at = now(), updated_at = now()
                 where id = $1::uuid
                """,
            _uuid(review_id),
            decision,
            _uuid(reviewer_id),
            note,
        )
        await _audit(
            connection,
            actor_id=_uuid(reviewer_id),
            action=f"review_{decision}",
            entity_type="teacher_review",
            entity_id=review_id,
            before=before,
            after={"status": decision, "note": note},
        )

        if overrides:
            await _record_overrides(
                connection,
                review_id=review_id,
                reviewer_id=_uuid(reviewer_id),
                overrides=overrides,
            )
            for item in overrides:
                await _audit(
                    connection,
                    actor_id=_uuid(reviewer_id),
                    action=f"override_{item['target']}",
                    entity_type="teacher_review",
                    entity_id=review_id,
                    before=item.get("old_value"),
                    after=item.get("new_value"),
                    metadata={"target_key": item.get("target_key"), "reason": item.get("reason")},
                )

        # Final result: an explicit final_marks override wins; otherwise the
        # AI's proposed marks snapshotted from evaluation_results.
        proposed: float | None = None
        marks_maximum: float | None = None
        result_id = review.get("result_id")
        if result_id:
            er = await connection.fetchrow(
                "select proposed_marks, marks_maximum from evaluation_results where id = $1::uuid",
                _uuid(result_id),
            )
            if er:
                proposed = float(er["proposed_marks"])
                marks_maximum = float(er["marks_maximum"])

        qnum = _question_number(review["question_id"])
        policy_max = await _final_marks_max(pool, review["assessment_id"], qnum) if qnum is not None else None
        if marks_maximum is None:
            marks_maximum = policy_max if policy_max is not None else 0.0

        explicit_final = {"new_value": final_marks} if final_marks is not None else next(
            (o for o in overrides if o.get("target") == "final_marks"), None
        )
        awarded = proposed if proposed is not None else 0.0
        if explicit_final is not None and explicit_final.get("new_value") is not None:
            candidate = float(explicit_final["new_value"])
            ceiling = marks_maximum if marks_maximum > 0 else candidate
            awarded = round(max(0.0, min(candidate, ceiling)), 2)

        await connection.execute(
            """
                insert into final_results
                    (submission_id, assessment_id, question_id, marks_awarded, marks_maximum,
                     source, approved_by, result_id, review_id)
                values ($1::uuid, $2::uuid, $3, $4, $5, 'review', $6::uuid, $7::uuid, $8::uuid)
                on conflict (submission_id, question_id) do update
                    set marks_awarded = excluded.marks_awarded,
                        marks_maximum = excluded.marks_maximum,
                        source = 'review',
                        approved_by = excluded.approved_by,
                        review_id = excluded.review_id,
                        version = final_results.version + 1,
                        updated_at = now()
                """,
            _uuid(review["submission_id"]),
            _uuid(review["assessment_id"]),
            review["question_id"],
            awarded,
            marks_maximum,
            _uuid(reviewer_id),
            _uuid(result_id) if result_id else None,
            _uuid(review_id),
        )

        # WAITING_FOR_REVIEW resolves back to completed (#85).
        await connection.execute(
            """
                update submissions set status = 'completed', updated_at = now()
                 where id = $1::uuid and status = 'waiting_for_review'
                """,
            _uuid(review["submission_id"]),
        )

    return await get_review(pool, review_id)


async def refresh_assessment_status(pool: asyncpg.Pool, assessment_id: str) -> str | None:
    """When nothing is queued/processing/waiting, close out the assessment (#70/#71)."""
    row = await pool.fetchrow(
        """
        select
            count(*) filter (where status in ('uploaded','pending','ready','queued','processing','evaluating')) as outstanding,
            count(*) filter (where status = 'waiting_for_review') as waiting,
            count(*) filter (where status = 'completed') as completed,
            count(*) as total
        from submissions where assessment_id = $1::uuid
        """,
        _uuid(assessment_id),
    )
    if row is None or row["total"] == 0 or row["outstanding"] > 0 or row["waiting"] > 0:
        return None
    if row["completed"] > 0:
        await pool.execute(
            """
            update assessments set status = 'completed', updated_at = now()
             where id = $1::uuid and status = 'processing'
            """,
            _uuid(assessment_id),
        )
        return "completed"
    return None

