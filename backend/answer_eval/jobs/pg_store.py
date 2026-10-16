"""PostgreSQL-backed durable JobStore (Milestone 14, spec #69/#70).

Production implementation of the JobStore protocol. The worker/queue/API call
it synchronously, so an internal event-loop thread owns the asyncpg pool and
every protocol method bridges onto it — callers stay unchanged.

Durability rules:
  * job existence/state/results live in Postgres (job_records / job_results);
  * Redis carries only ephemeral coordination (queue.py);
  * losing Redis loses nothing — jobs are reconstructible from these tables;
  * claims use FOR UPDATE SKIP LOCKED so N workers never grab one job.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from answer_eval.core.logging import get_logger
from answer_eval.jobs.schemas import JobRecord, JobStatus, utcnow

logger = get_logger("jobs.pg_store")

_ACTIVE_STATUSES = ("queued", "claimed", "processing", "waiting_for_review", "retrying")


def _jsonb_default(value: Any) -> str:
    return json.dumps(value, default=str)


class PostgresJobStore:
    """Sync-facing JobStore backed by asyncpg on a private loop thread."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5) -> None:
        self._dsn = dsn
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="jobs-pg-store", daemon=True)
        self._thread.start()
        self._pool: asyncpg.Pool | None = None
        self._run(self._connect(min_size=min_size, max_size=max_size))
        logger.info("PostgresJobStore ready")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=30)

    async def _connect(self, *, min_size: int, max_size: int) -> None:
        async def _init(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb",
                encoder=_jsonb_default,
                decoder=json.loads,
                schema="pg_catalog",
            )

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=min_size,
            max_size=max_size,
            statement_cache_size=0,  # pgbouncer/Supavisor compatibility
            init=_init,
        )

    def close(self) -> None:
        if self._pool is not None:
            self._run(self._pool.close())
            self._pool = None
        self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def pool(self) -> asyncpg.Pool | None:
        """Expose the pool so components (e.g. evidence persistence) can reuse it."""
        return self._pool

    def run_coro(self, coro):
        """Run an awaitable to completion on the store's event loop (thread-safe).

        Reused by evidence persistence so asyncpg operations stay on the same
        loop the pool was created on (``asyncio.run`` on the caller's thread
        would bind the pool's connections to a different loop and fail).
        """
        return self._run(coro)

    @staticmethod
    def _record_from(row: asyncpg.Record | None) -> JobRecord | None:
        if row is None:
            return None
        return JobRecord.model_validate(dict(row["payload"]))

    @staticmethod
    def _as_ts(value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    # -- protocol -------------------------------------------------------------

    def create_job(self, record: JobRecord) -> tuple[JobRecord, bool]:
        existing = self.find_active_by_submission(record.submission_id)
        if existing is not None:
            return existing, False

        def _insert(pool: asyncpg.Pool):
            return pool.fetchrow(
                """
                insert into job_records
                    (job_id, submission_id, status, attempt, payload)
                values ($1, $2, $3, $4, $5::jsonb)
                on conflict (job_id) do nothing
                returning payload
                """,
                record.job_id,
                record.submission_id,
                record.status.value,
                record.attempt,
                record.model_dump(),
            )

        row = self._run(_insert(self._pool))
        if row is None:
            existing = self.find_active_by_submission(record.submission_id)
            if existing is not None:
                return existing, False

        def _event(pool: asyncpg.Pool):
            return pool.execute(
                "insert into job_record_events (job_id, event) values ($1, 'created')",
                record.job_id,
            )

        self._run(_event(self._pool))
        return record, True

    def get_job(self, job_id: str) -> JobRecord | None:
        def _get(pool: asyncpg.Pool):
            return pool.fetchrow("select payload from job_records where job_id = $1", job_id)

        return self._record_from(self._run(_get(self._pool)))

    def find_active_by_submission(self, submission_id: str) -> JobRecord | None:
        def _find(pool: asyncpg.Pool):
            return pool.fetchrow(
                """
                select payload from job_records
                 where submission_id = $1 and status = any($2::text[])
                 order by created_at desc limit 1
                """,
                submission_id,
                list(_ACTIVE_STATUSES),
            )

        return self._record_from(self._run(_find(self._pool)))

    def update_job(self, job_id: str, **fields: Any) -> JobRecord | None:
        async def _update(pool: asyncpg.Pool):
            async with pool.acquire() as conn, conn.transaction():
                row = await conn.fetchrow(
                    "select payload from job_records where job_id = $1 for update",
                    job_id,
                )
                if row is None:
                    return None
                data = dict(row["payload"])
                old_status = data.get("status")
                data.update(fields)
                updated = JobRecord.model_validate(data)
                await conn.execute(
                    """
                        update job_records set
                            status = $2, attempt = $3, worker_id = $4,
                            lease_expires_at = $5::timestamptz, next_attempt_at = $6::timestamptz,
                            payload = $7::jsonb, updated_at = now()
                        where job_id = $1
                        """,
                    job_id,
                    updated.status.value,
                    updated.attempt,
                    updated.worker_id,
                    self._as_ts(updated.lease_expires_at),
                    self._as_ts(updated.next_attempt_at),
                    updated.model_dump(),
                )
                new_status = updated.status.value
                if new_status != old_status:
                    await conn.execute(
                        "insert into job_record_events (job_id, event, metadata) "
                        "values ($1, $2, $3::jsonb)",
                        job_id,
                        f"status:{new_status}",
                        json.dumps({"from": old_status}),
                    )
                return updated

        return self._run(_update(self._pool))

    def claim_next_job(self, worker_id: str, lease_seconds: float) -> JobRecord | None:
        async def _claim(pool: asyncpg.Pool):
            async with pool.acquire() as conn, conn.transaction():
                row = await conn.fetchrow(
                    """
                        select job_id, payload from job_records
                         where status in ('queued', 'retrying')
                           and (next_attempt_at is null or next_attempt_at <= now())
                         order by created_at
                         limit 1
                         for update skip locked
                        """,
                )
                if row is None:
                    return None
                data = dict(row["payload"])
                expires = (
                    datetime.now(UTC) + timedelta(seconds=lease_seconds)
                ).isoformat()
                data.update(
                    {
                        "status": JobStatus.claimed.value,
                        "worker_id": worker_id,
                        "lease_expires_at": expires,
                        "heartbeat_at": utcnow(),
                    }
                )
                updated = JobRecord.model_validate(data)
                await conn.execute(
                    """
                        update job_records set
                            status = 'claimed', worker_id = $2,
                            lease_expires_at = $3::timestamptz,
                            payload = $4::jsonb, updated_at = now()
                        where job_id = $1
                        """,
                    row["job_id"],
                    worker_id,
                    self._as_ts(updated.lease_expires_at),
                    updated.model_dump(),
                )
                await conn.execute(
                    "insert into job_record_events (job_id, event, metadata) values ($1, 'claimed', $2::jsonb)",
                    row["job_id"],
                    json.dumps({"worker_id": worker_id}),
                )
                return updated

        return self._run(_claim(self._pool))

    def reclaim_expired_leases(self) -> int:
        def _reclaim(pool: asyncpg.Pool):
            return pool.fetch(
                """
                update job_records set
                    status = 'queued', worker_id = null,
                    lease_expires_at = null,
                    payload = jsonb_set(
                        jsonb_set(
                            jsonb_set(payload, '{status}', '"queued"'::jsonb),
                            '{worker_id}', 'null'::jsonb
                        ),
                        '{lease_expires_at}', 'null'::jsonb
                    ),
                    updated_at = now()
                where status in ('claimed', 'processing') and lease_expires_at < now()
                returning job_id
                """
            )

        rows = self._run(_reclaim(self._pool))
        reclaimed = len(rows)
        if reclaimed:

            def _events(pool: asyncpg.Pool):
                return pool.executemany(
                    "insert into job_record_events (job_id, event) values ($1, 'lease_reclaimed')",
                    [(r["job_id"],) for r in rows],
                )

            self._run(_events(self._pool))
            logger.info("Reclaimed expired leases", count=reclaimed)
        return reclaimed

    def list_jobs(self, limit: int = 200) -> list[JobRecord]:
        def _list(pool: asyncpg.Pool):
            return pool.fetch(
                "select payload from job_records order by created_at desc limit $1", limit
            )

        rows = self._run(_list(self._pool))
        records = [self._record_from(r) for r in rows]
        return [r for r in records if r is not None]

    def save_result(self, submission_id: str, result: dict[str, Any]) -> None:
        def _save(pool: asyncpg.Pool):
            return pool.execute(
                """
                insert into job_results (submission_id, payload, updated_at)
                values ($1, $2::jsonb, now())
                on conflict (submission_id) do update
                    set payload = excluded.payload, updated_at = now()
                """,
                submission_id,
                result,
            )

        self._run(_save(self._pool))

    def get_result(self, submission_id: str) -> dict[str, Any] | None:
        def _get(pool: asyncpg.Pool):
            return pool.fetchrow(
                "select payload from job_results where submission_id = $1", submission_id
            )

        row = self._run(_get(self._pool))
        return dict(row["payload"]) if row else None

    def persist_results(self, submission_id: str, summary: dict[str, Any]) -> None:
        """Persist a completed evaluation into the Results read-model.

        The workflow's ``result_summary`` holds the graded per-question marks, but
        the Results/Analytics pages read only ``evaluation_results`` and
        ``final_results`` — nothing bridged the two until now (single-PC fix).

        * ``evaluation_results`` — one row per graded question (AI proposal).
        * ``final_results``     — questions the risk engine auto-approved
          (``source='ai'``) AND questions the teacher approved during the
          in-workflow review gate (``source='review'``). Both carry final
          marks so the Results/Analytics read-models see the real totals.
        """
        questions = summary.get("questions")
        if not isinstance(questions, dict) or not questions:
            return  # nothing graded — caller decides how to surface that
        auto_approved = set(summary.get("auto_approved") or [])
        human_reviewed = set(summary.get("human_reviewed") or [])

        def _persist(pool: asyncpg.Pool):
            async def _write() -> None:
                async with pool.acquire() as conn:
                    assessment_id = await conn.fetchval(
                        "select assessment_id from submissions where id = $1::uuid",
                        submission_id,
                    )
                    if not assessment_id:
                        logger.warning(
                            "persist_results: submission not found",
                            submission_id=submission_id,
                        )
                        return
                    for qid, q in sorted(questions.items()):
                        final_marks = round(float(q.get("final_marks") or 0), 2)
                        maximum = round(float(q.get("maximum_marks") or 0), 2)
                        criteria_data = q.get("criteria") or []
                        breakdown = {
                            "criteria_total": q.get("criteria_total"),
                            "deterministic_penalty": q.get("deterministic_penalty"),
                            "risk_level": q.get("risk_level"),
                            "feedback": q.get("feedback", ""),
                            "reason": q.get("reason", ""),
                            "reasons": q.get("reasons", []),
                        }
                        # evaluation_results has no per-question unique key, so
                        # replace the proposal on re-runs to stay idempotent.
                        await conn.execute(
                            "delete from evaluation_results "
                            "where submission_id = $1::uuid and question_id = $2",
                            submission_id,
                            qid,
                        )
                        er_id = await conn.fetchval(
                            """
                            insert into evaluation_results
                                (assessment_id, submission_id, question_id, proposed_marks,
                                 marks_maximum, criteria, breakdown, schema_version)
                            values ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7::jsonb,
                                    'evaluation-result-v1')
                            returning id
                            """,
                            assessment_id,
                            submission_id,
                            qid,
                            final_marks,
                            maximum,
                            criteria_data,
                            breakdown,
                        )
                        if qid in auto_approved:
                            await conn.execute(
                                """
                                insert into final_results
                                    (assessment_id, submission_id, question_id, marks_awarded,
                                     marks_maximum, deductions, breakdown, source, result_id, version)
                                values ($1::uuid, $2::uuid, $3, $4, $5, '[]'::jsonb, $6::jsonb,
                                        'ai', $7, 1)
                                on conflict (submission_id, question_id) do update
                                    set marks_awarded = excluded.marks_awarded,
                                        marks_maximum = excluded.marks_maximum,
                                        deductions = excluded.deductions,
                                        breakdown = excluded.breakdown,
                                        source = 'ai',
                                        result_id = excluded.result_id,
                                        version = final_results.version + 1,
                                        updated_at = now()
                                """,
                                assessment_id,
                                submission_id,
                                qid,
                                final_marks,
                                maximum,
                                breakdown,
                                er_id,
                            )
                        elif qid in human_reviewed:
                            # Teacher-approved in the workflow's review gate: the
                            # marks are final and must reach the read-model.
                            await conn.execute(
                                """
                                insert into final_results
                                    (assessment_id, submission_id, question_id, marks_awarded,
                                     marks_maximum, deductions, breakdown, source, result_id, version)
                                values ($1::uuid, $2::uuid, $3, $4, $5, '[]'::jsonb, $6::jsonb,
                                        'review', $7, 1)
                                on conflict (submission_id, question_id) do update
                                    set marks_awarded = excluded.marks_awarded,
                                        marks_maximum = excluded.marks_maximum,
                                        deductions = excluded.deductions,
                                        breakdown = excluded.breakdown,
                                        source = 'review',
                                        result_id = excluded.result_id,
                                        version = final_results.version + 1,
                                        updated_at = now()
                                """,
                                assessment_id,
                                submission_id,
                                qid,
                                final_marks,
                                maximum,
                                breakdown,
                                er_id,
                            )

            return _write()

        try:
            self._run(_persist(self._pool))
            logger.info(
                "Persisted evaluation results",
                submission_id=submission_id,
                questions=len(questions),
                auto_approved=sorted(auto_approved),
            )
        except Exception as exc:  # noqa: BLE001 - persistence must never break grading
            logger.warning(
                "Could not persist evaluation results",
                submission_id=submission_id,
                error=str(exc),
            )

    def mark_submission(self, submission_id: str, status: str, detail: str | None = None) -> None:
        """Mirror a job's lifecycle into the submissions table so the UI status
        endpoint (/assessments/{id}/status) reflects real progress: this is the
        single-PC fix that makes the Evaluation page advance instead of showing
        every paper stuck in 'queued' forever."""

        def _mark(pool: asyncpg.Pool):
            return pool.execute(
                """update submissions set status = $2, status_detail = $3, updated_at = now()
                   where id = $1::uuid and status <> 'completed'""",
                submission_id,
                status,
                detail,
            )

        try:
            self._run(_mark(self._pool))
        except Exception as exc:  # noqa: BLE001 - UI mirroring must never break grading
            logger.warning(
                "Could not mirror submission status",
                submission_id=submission_id,
                status=status,
                error=str(exc),
            )


__all__ = ["PostgresJobStore"]
