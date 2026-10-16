"""Submission persistence + student roster."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg

_SUBMISSION_COLUMNS = """
    id, assessment_id, roll_number, status, status_detail,
    pdf_object_key, pdf_sha256, page_count, flags, created_at, updated_at
"""


def _uuid(value: str) -> uuid.UUID:
    return uuid.UUID(str(value))


def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("id", "assessment_id"):
        data[key] = str(data[key])
    data["pdf_sha256"] = str(data["pdf_sha256"]) if data.get("pdf_sha256") else None
    return data


async def upsert_submission(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    roll_number: str,
    pdf_object_key: str,
    pdf_sha256: str,
    page_count: int | None,
    flags: list[str],
    uploaded_by: str,
) -> dict[str, Any]:
    """Insert or idempotently refresh a submission; flags duplicates by hash."""
    async with pool.acquire() as connection:
        existing_hash = await connection.fetchrow(
            """select id, roll_number from submissions
               where assessment_id = $1 and pdf_sha256 = $2 and roll_number != $3""",
            _uuid(assessment_id),
            pdf_sha256,
            roll_number,
        )
        if existing_hash is not None:
            raise ValueError(f"identical file was already uploaded for student roll {existing_hash['roll_number']}")

        existing = await connection.fetchrow(
            """select id, pdf_sha256 from submissions
               where assessment_id = $1 and roll_number = $2""",
            _uuid(assessment_id),
            roll_number,
        )
        if existing is not None:
            same_content = str(existing["pdf_sha256"] or "").lower() == pdf_sha256.lower()
            if same_content:
                row = await connection.fetchrow(
                    f"""update submissions set updated_at = now()
                        where id = $1 returning {_SUBMISSION_COLUMNS}""",
                    existing["id"],
                )
                result = _row_to_dict(row)
                assert result is not None
                result["flags"] = list(result.get("flags") or []) + ["reupload_identical"]
                return result
            row = await connection.fetchrow(
                f"""update submissions
                    set pdf_object_key = $2, pdf_sha256 = $3, page_count = $4,
                        flags = flags || to_jsonb('replaced_file'::text),
                        status_detail = 'file replaced by re-upload', updated_at = now()
                    where id = $1 returning {_SUBMISSION_COLUMNS}""",
                existing["id"],
                pdf_object_key,
                pdf_sha256,
                page_count,
            )
            result = _row_to_dict(row)
            assert result is not None
            await _sync_student_row(connection, assessment_id=assessment_id, roll_number=roll_number)
            return result

        row = await connection.fetchrow(
            f"""insert into submissions
                (assessment_id, roll_number, pdf_object_key, pdf_sha256, page_count, flags, uploaded_by)
                values ($1, $2, $3, $4, $5, $6, $7)
                returning {_SUBMISSION_COLUMNS}""",
            _uuid(assessment_id),
            roll_number,
            pdf_object_key,
            pdf_sha256,
            page_count,
            flags,
            _uuid(uploaded_by),
        )
        result = _row_to_dict(row)
        assert result is not None
        await _sync_student_row(connection, assessment_id=assessment_id, roll_number=roll_number)
        return result


async def get_submission(pool: asyncpg.Pool, submission_id: str) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        f"select {_SUBMISSION_COLUMNS} from submissions where id = $1",
        _uuid(submission_id),
    )
    return _row_to_dict(row)


async def list_for_assessment(pool: asyncpg.Pool, assessment_id: str) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        f"""select {_SUBMISSION_COLUMNS}
            from submissions
            where assessment_id = $1
            order by roll_number""",
        _uuid(assessment_id),
    )
    results = []
    for row in rows:
        item = _row_to_dict(row)
        assert item is not None
        results.append(item)
    return results


async def count_summary(pool: asyncpg.Pool, assessment_id: str) -> dict[str, int]:
    row = await pool.fetchrow(
        """select count(*)::int as total,
                  count(*) filter (where status in ('uploaded', 'pending', 'ready'))::int as ready,
                  count(*) filter (where status in ('queued','processing','evaluating'))::int as processing,
                  count(*) filter (where status = 'completed')::int as completed,
                  count(*) filter (where status = 'waiting_for_review')::int as waiting_for_review,
                  count(*) filter (where status in ('invalid','failed'))::int as failed
           from submissions where assessment_id = $1""",
        _uuid(assessment_id),
    )
    assert row is not None
    return dict(row)


async def queue_uploaded(pool: asyncpg.Pool, assessment_id: str) -> int:
    """Move every freshly-uploaded submission into the evaluation queue."""
    tag = await pool.execute(
        """update submissions
              set status = 'queued', updated_at = now()
            where assessment_id = $1 and status in ('uploaded', 'pending', 'ready')""",
        _uuid(assessment_id),
    )
    # asyncpg returns a command tag such as "UPDATE 12".
    try:
        return int(str(tag).split()[-1])
    except (ValueError, IndexError):
        return 0


async def _sync_student_row(connection: asyncpg.Connection, *, assessment_id: str, roll_number: str) -> None:
    await connection.execute(
        """insert into assessment_students (assessment_id, roll_number)
           values ($1, $2)
           on conflict (assessment_id, roll_number) do update
             set updated_at = now()""",
        _uuid(assessment_id),
        roll_number,
    )


def _json_list(items: list[str]) -> str:
    import json

    return json.dumps(list(items))
