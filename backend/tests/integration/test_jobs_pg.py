"""Milestone 14 integration: PostgresJobStore against LIVE Supabase (spec #69/#70).

Durability: create -> idempotent duplicate -> atomic claim (SKIP LOCKED) ->
lease expiry reclaim -> complete -> results round-trip. Rows are cleaned up.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from answer_eval.jobs.pg_store import PostgresJobStore
from answer_eval.jobs.schemas import JobRecord, JobStatus

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("SUPABASE_URL") or "") and not Path(".env").exists(),
        reason="live credentials required",
    ),
]


def _dsn() -> str:
    load_env: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            load_env[key.strip()] = value.strip().strip('"')
    return (
        os.environ.get("DATABASE_URL")
        or load_env.get("DATABASE_URL")
        or load_env.get("DATABASE_URL_POOLER")
        or ""
    )


def _record(submission_id: str) -> JobRecord:
    return JobRecord(
        job_id=f"JOB-T{uuid.uuid4().hex[:10].upper()}",
        submission_id=submission_id,
        pdf_path="/tmp/does-not-matter.pdf",
        rubrics={"Q1": {"question_id": "Q1"}},
    )


@pytest.fixture()
def store():
    store = PostgresJobStore(_dsn())
    yield store
    # Cleanup test rows.
    ids = [j.job_id for j in store.list_jobs(limit=500) if j.job_id.startswith("JOB-T")]
    if ids:
        pool = store._pool

        def _cleanup(pool):
            return pool.executemany("delete from job_records where job_id = $1", [(i,) for i in ids])

        store._run(_cleanup(pool))
    store.close()


def test_postgres_store_full_lifecycle(store) -> None:
    submission = f"SUB-JT-{uuid.uuid4().hex[:10]}"
    record = _record(submission)

    created, ok = store.create_job(record)
    assert ok and created.job_id == record.job_id

    # Durable: readable from a fresh lookup.
    fetched = store.get_job(record.job_id)
    assert fetched is not None and fetched.submission_id == submission

    # Idempotent duplicate submit returns the SAME active job.
    duplicate, ok2 = store.create_job(_record(submission))
    assert not ok2 and duplicate.job_id == record.job_id

    # Atomic claim: first worker gets it, second worker gets nothing else for
    # this submission (single queued row).
    claimed = store.claim_next_job("worker-A", lease_seconds=120)
    assert claimed is not None and claimed.job_id == record.job_id
    assert claimed.worker_id == "worker-A"
    assert claimed.status == JobStatus.claimed

    # Heartbeat/progress update persists.
    updated = store.update_job(
        record.job_id,
        status=JobStatus.processing,
        current_stage="ocr",
        progress_completed=4,
        heartbeat_at=datetime.now(UTC).isoformat(),
    )
    assert updated is not None and updated.status == JobStatus.processing

    # Lease expiry -> reclaimed to queued by any live worker (#66).
    past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    store.update_job(record.job_id, status=JobStatus.claimed, lease_expires_at=past)
    reclaimed_count = store.reclaim_expired_leases()
    assert reclaimed_count >= 1
    back = store.get_job(record.job_id)
    assert back is not None and back.status == JobStatus.queued

    # Re-claim, then complete with a durable result.
    re_claimed = store.claim_next_job("worker-B", lease_seconds=120)
    assert re_claimed is not None and re_claimed.worker_id == "worker-B"
    done = store.update_job(
        record.job_id,
        status=JobStatus.completed,
        result_summary={"total": 7.5, "maximum": 10},
        completed_at=datetime.now(UTC).isoformat(),
    )
    assert done.status == JobStatus.completed

    store.save_result(submission, {"total_marks": 7.5, "maximum": 10})
    loaded = store.get_result(submission)
    assert loaded == {"total_marks": 7.5, "maximum": 10}

    listed_ids = {j.job_id for j in store.list_jobs(limit=500)}
    assert record.job_id in listed_ids


def test_persist_results_writes_read_model_rows(store) -> None:
    """A completed workflow's summary is durable into evaluation_results +
    final_results so the Results/Analytics read-models see real marks.

    Uses a throwaway question id against a real submission row so nothing the
    teacher actually produced is touched, and cleans up afterwards.
    """

    def _pick(pool):
        return pool.fetchval("select id::text from submissions order by created_at desc limit 1")

    submission_id = store._run(_pick(store._pool))
    if not submission_id:
        pytest.skip("no submissions present in live database")

    qid = "Q-JT-PERSIST"
    summary = {
        "submission_id": submission_id,
        "questions": {
            qid: {
                "final_marks": 4.0,
                "maximum_marks": 5.0,
                "criteria_total": 4.0,
                "deterministic_penalty": 0.0,
                "risk_level": "low",
                "feedback": "auto-approved test run",
            },
        },
        "auto_approved": [qid],
        "human_reviewed": [],
    }
    store.persist_results(submission_id, summary)

    def _check(pool):
        return pool.fetchrow(
            "select f.marks_awarded as awarded, f.marks_maximum as maximum, f.source as src, "
            "       e.proposed_marks as proposed, e.question_id as qid "
            "from final_results f "
            "join evaluation_results e on e.id = f.result_id "
            "where f.submission_id = $1::uuid and f.question_id = $2",
            submission_id,
            qid,
        )

    row = store._run(_check(store._pool))
    assert row is not None, "final_results row must exist for an auto-approved question"
    assert float(row["awarded"]) == 4.0
    assert float(row["maximum"]) == 5.0
    assert row["src"] == "ai"
    assert float(row["proposed"]) == 4.0

    # Idempotent: re-persisting replaces the proposal instead of duplicating it.
    store.persist_results(submission_id, summary)

    def _count(pool):
        return pool.fetchval(
            "select count(*) from evaluation_results "
            "where submission_id = $1::uuid and question_id = $2",
            submission_id,
            qid,
        )

    assert store._run(_count(store._pool)) == 1

    def _cleanup(pool):
        async def _tx_():
            async with pool.acquire() as conn:
                await conn.execute(
                    "delete from final_results where submission_id = $1::uuid and question_id = $2",
                    submission_id,
                    qid,
                )
                await conn.execute(
                    "delete from evaluation_results where submission_id = $1::uuid and question_id = $2",
                    submission_id,
                    qid,
                )

        return _tx_()

    store._run(_cleanup(store._pool))
