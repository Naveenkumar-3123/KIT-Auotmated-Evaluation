"""Persistence for assessments + submissions (Milestone 3)."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg

_ASSESSMENT_COLUMNS = """
    a.id, a.teacher_id, a.class_id, a.subject_id, a.title, a.status,
    a.pass_percentage, a.total_marks, a.question_count, a.version,
    a.locked_answer_key_version, a.locked_policy_version,
    c.name AS class_name, s.name AS subject_name
"""


def _uuid(value: str) -> uuid.UUID:
    return uuid.UUID(str(value))


def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("id", "teacher_id", "class_id", "subject_id"):
        if data.get(key) is not None:
            data[key] = str(data[key])
    return data


async def create_draft(
    pool: asyncpg.Pool,
    *,
    teacher_id: str,
    title: str = "",
) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        insert into assessments (teacher_id, title)
        values ($1, $2)
        returning id
        """,
        _uuid(teacher_id),
        title or "Untitled assessment",
    )
    assert row is not None
    return {"id": str(row["id"])}


async def get(pool: asyncpg.Pool, assessment_id: str) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        f"""
        select {_ASSESSMENT_COLUMNS}
        from assessments a
        left join classes c on c.id = a.class_id
        left join subjects s on s.id = a.subject_id
        where a.id = $1
        """,
        _uuid(assessment_id),
    )
    return _row_to_dict(row)


async def list_for_teacher(pool: asyncpg.Pool, teacher_id: str) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        f"""
        select {_ASSESSMENT_COLUMNS},
               (select count(*)::int from submissions sub where sub.assessment_id = a.id) as student_count,
               (select count(*)::int from submissions sub
                 where sub.assessment_id = a.id and sub.status in ('uploaded', 'pending', 'ready')) as ready_count,
               (select count(*)::int from submissions sub
                  where sub.assessment_id = a.id
                    and sub.status in ('queued','processing','evaluating')) as processing_count,
               (select count(*)::int from submissions sub
                  where sub.assessment_id = a.id and sub.status = 'completed') as completed_count,
               (select count(*)::int from submissions sub
                  where sub.assessment_id = a.id and sub.status = 'waiting_for_review') as review_count,
               (select count(*)::int from submissions sub
                  where sub.assessment_id = a.id
                    and sub.status in ('invalid','failed')) as failed_count
        from assessments a
        left join classes c on c.id = a.class_id
        left join subjects s on s.id = a.subject_id
        where a.teacher_id = $1
        order by a.created_at desc
        """,
        _uuid(teacher_id),
    )
    results = []
    for row in rows:
        item = _row_to_dict(row)
        assert item is not None
        item["student_count"] = row["student_count"]
        item["ready_count"] = row["ready_count"]
        item["processing_count"] = row["processing_count"]
        item["completed_count"] = row["completed_count"]
        item["review_count"] = row["review_count"]
        item["failed_count"] = row["failed_count"]
        results.append(item)
    return results


async def update_details(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    teacher_id: str,
    title: str | None = None,
    class_name: str | None = None,
    subject_name: str | None = None,
    pass_percentage: float | None = None,
) -> dict[str, Any] | None:
    """Set class/subject/title/pass mark. Class+subject are required together."""
    assignments: list[str] = []
    values: list[Any] = [_uuid(assessment_id), _uuid(teacher_id)]
    n = 3

    if pass_percentage is not None:
        if not 0 <= float(pass_percentage) <= 100:
            raise ValueError("pass_percentage must be between 0 and 100")
        assignments.append(f"pass_percentage = ${n}")
        values.append(float(pass_percentage))
        n += 1
    if title is not None:
        assignments.append(f"title = ${n}")
        values.append(title.strip() or "Untitled assessment")
        n += 1

    async with pool.acquire() as connection, connection.transaction():
        if class_name or subject_name:
            if not (class_name and subject_name):
                raise ValueError("class_name and subject_name must be provided together")
            class_id = await _ensure_class(connection, teacher_id, class_name)
            subject_id = await _ensure_subject(connection, teacher_id, subject_name)
            assignments.append(f"class_id = ${n}")
            values.append(class_id)
            n += 1
            assignments.append(f"subject_id = ${n}")
            values.append(subject_id)
            n += 1

        if not assignments:
            return await get(pool, assessment_id)

        row = await connection.fetchrow(
            f"""update assessments set {', '.join(assignments)}, updated_at = now()
                    where id = $1 and teacher_id = $2
                    returning id""",
            *values,
        )
    if row is None:
        return None
    return await get(pool, assessment_id)


async def delete_draft(pool: asyncpg.Pool, *, assessment_id: str, teacher_id: str) -> bool:
    status = await pool.fetchval(
        "delete from assessments where id = $1 and teacher_id = $2 and status = 'draft' returning id",
        _uuid(assessment_id),
        _uuid(teacher_id),
    )
    return status is not None


async def set_status(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    teacher_id: str,
    new_status: str,
    allowed_from: tuple[str, ...],
) -> dict[str, Any] | None:
    """Guarded status transition; returns the refreshed row or None if not allowed."""
    row = await pool.fetchrow(
        """update assessments set status = $3, updated_at = now()
            where id = $1 and teacher_id = $2 and status = any($4::text[])
            returning id""",
        _uuid(assessment_id),
        _uuid(teacher_id),
        new_status,
        list(allowed_from),
    )
    if row is None:
        return None
    return await get(pool, assessment_id)


async def require_owned(pool: asyncpg.Pool, *, assessment_id: str, teacher_id: str) -> dict[str, Any]:
    row = await get(pool, assessment_id)
    if row is None or row["teacher_id"] != teacher_id:
        raise LookupError("assessment_not_found")
    return row


# -- helpers -----------------------------------------------------------------


async def _ensure_class(connection: asyncpg.Connection, teacher_id: str, name: str) -> uuid.UUID:
    clean = name.strip()
    row = await connection.fetchrow(
        """
        select c.id from classes c
        where c.created_by = $1 and lower(c.name) = lower($2)
        limit 1
        """,
        _uuid(teacher_id),
        clean,
    )
    if row is not None:
        class_id = row["id"]
    else:
        inserted = await connection.fetchrow(
            "insert into classes (created_by, name) values ($1, $2) returning id",
            _uuid(teacher_id),
            clean,
        )
        assert inserted is not None
        class_id = inserted["id"]
    await connection.execute(
        "insert into teacher_classes (teacher_id, class_id) values ($1, $2) on conflict do nothing",
        _uuid(teacher_id),
        class_id,
    )
    return class_id


async def _ensure_subject(connection: asyncpg.Connection, teacher_id: str, name: str) -> uuid.UUID:
    clean = name.strip()
    row = await connection.fetchrow(
        """
        select s.id from subjects s
        where s.created_by = $1 and lower(s.name) = lower($2)
        limit 1
        """,
        _uuid(teacher_id),
        clean,
    )
    if row is not None:
        subject_id = row["id"]
    else:
        inserted = await connection.fetchrow(
            "insert into subjects (created_by, name) values ($1, $2) returning id",
            _uuid(teacher_id),
            clean,
        )
        assert inserted is not None
        subject_id = inserted["id"]
    await connection.execute(
        "insert into teacher_subjects (teacher_id, subject_id) values ($1, $2) on conflict do nothing",
        _uuid(teacher_id),
        subject_id,
    )
    return subject_id
