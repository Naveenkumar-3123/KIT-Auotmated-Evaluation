"""Durable job store (Module 18).

DURABILITY RULE: job existence/state/results live in the durable store, never
only in Redis. Redis is used for queueing/leases/coordination only.

Production target is PostgreSQL; until the project database exists, the
durable local fallback is SQLiteJobStore (WAL mode). InMemoryJobStore is for
unit tests only. All stores implement the JobStore protocol — swapping in a
Postgres implementation later requires no changes to worker/queue/API code.
"""

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from answer_eval.core.logging import get_logger
from answer_eval.jobs.schemas import JobRecord, JobStatus, utcnow

logger = get_logger("jobs.store")


class JobStore(Protocol):
    """Durable-job protocol — Postgres/SQLite/memory all implement this."""

    def create_job(self, record: JobRecord) -> tuple[JobRecord, bool]: ...
    def get_job(self, job_id: str) -> JobRecord | None: ...
    def find_active_by_submission(self, submission_id: str) -> JobRecord | None: ...
    def update_job(self, job_id: str, **fields: Any) -> JobRecord | None: ...
    def claim_next_job(self, worker_id: str, lease_seconds: float) -> JobRecord | None: ...
    def reclaim_expired_leases(self) -> int: ...
    def list_jobs(self, limit: int = 200) -> list[JobRecord]: ...
    def save_result(self, submission_id: str, result: dict[str, Any]) -> None: ...
    def get_result(self, submission_id: str) -> dict[str, Any] | None: ...


logger = get_logger("jobs.store")

_ACTIVE_STATUSES = {
    JobStatus.queued.value,
    JobStatus.claimed.value,
    JobStatus.processing.value,
    JobStatus.waiting_for_review.value,
    JobStatus.retrying.value,
}


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


class _BaseMemoryStore:
    """Shared in-memory implementation (unit tests / ephemeral dev runs)."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._results: dict[str, dict] = {}
        self._lock = threading.RLock()

    def create_job(self, record: JobRecord) -> tuple[JobRecord, bool]:
        with self._lock:
            existing = self.find_active_by_submission(record.submission_id)
            if existing is not None:
                return existing, False  # idempotent duplicate protection
            self._jobs[record.job_id] = record
            return record, True

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def find_active_by_submission(self, submission_id: str) -> JobRecord | None:
        for job in self._jobs.values():
            if job.submission_id == submission_id and job.status in _ACTIVE_STATUSES:
                return job
        return None

    def update_job(self, job_id: str, **fields: Any) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            data = job.model_dump()
            data.update(fields)
            job = JobRecord.model_validate(data)
            self._jobs[job_id] = job
            return job

    def claim_next_job(self, worker_id: str, lease_seconds: float) -> JobRecord | None:
        """Atomically claim the oldest claimable queued/retrying job (lease-based)."""
        now = datetime.now(UTC)
        with self._lock:
            candidates = [
                j
                for j in self._jobs.values()
                if j.status in (JobStatus.queued, JobStatus.retrying)
                and (j.next_attempt_at is None or _parse(j.next_attempt_at) <= now)
            ]
            if not candidates:
                return None
            job = min(candidates, key=lambda j: j.created_at)
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
            return self.update_job(
                job.job_id,
                status=JobStatus.claimed,
                worker_id=worker_id,
                lease_expires_at=lease_until,
                heartbeat_at=utcnow(),
                started_at=job.started_at or utcnow(),
            )

    def reclaim_expired_leases(self) -> int:
        """Dead-worker recovery: expired leases become queued again."""
        now = datetime.now(UTC)
        reclaimed = 0
        with self._lock:
            for job in list(self._jobs.values()):
                lease_expired = job.status in (JobStatus.claimed, JobStatus.processing) and (
                    job.lease_expires_at and _parse(job.lease_expires_at) < now
                )
                if lease_expired:
                    self.update_job(
                        job.job_id,
                        status=JobStatus.queued,
                        worker_id=None,
                        lease_expires_at=None,
                        attempt=job.attempt + 1,
                    )
                    reclaimed += 1
        if reclaimed:
            logger.info("Reclaimed expired leases", count=reclaimed)
        return reclaimed

    def list_jobs(self, limit: int = 200) -> list[JobRecord]:
        """Most recent jobs first (dev UI / inspection helper)."""
        with self._lock:
            ordered = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return ordered[:limit]

    def save_result(self, submission_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._results[submission_id] = result

    def get_result(self, submission_id: str) -> dict[str, Any] | None:
        return self._results.get(submission_id)

    def mark_submission(self, submission_id: str, status: str, detail: str | None = None) -> None:
        """Fallback stub for non-Postgres stores."""
        pass


class InMemoryJobStore(_BaseMemoryStore):
    """EPHEMERAL — unit tests only. Not a production fallback."""


class SQLiteJobStore(_BaseMemoryStore):
    """
    Durable LOCAL DEVELOPMENT store (WAL-mode SQLite file).

    Production deployments swap in a PostgreSQL-backed JobStore implementing the
    same protocol. Every mutation is flushed synchronously so a crashed process
    loses nothing; the store is reloaded from disk on startup.
    """

    def __init__(self, db_path: str = "data/jobs.db") -> None:
        import os

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                submission_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        super().__init__()
        for row in self._conn.execute("SELECT payload FROM jobs"):
            job = JobRecord.model_validate_json(row[0])
            self._jobs[job.job_id] = job
        import json

        for row in self._conn.execute("SELECT submission_id, payload FROM results"):
            self._results[row[0]] = json.loads(row[1])

    def _persist_job(self, job: JobRecord) -> None:
        self._conn.execute(
            "INSERT INTO jobs (job_id, submission_id, status, created_at, payload) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, payload=excluded.payload",
            (job.job_id, job.submission_id, job.status.value, job.created_at, job.model_dump_json()),
        )
        self._conn.commit()

    def create_job(self, record: JobRecord) -> tuple[JobRecord, bool]:
        with self._lock:
            created, ok = super().create_job(record)
            if ok:
                self._persist_job(created)
            return created, ok

    def update_job(self, job_id: str, **fields: Any) -> JobRecord | None:
        with self._lock:
            updated = super().update_job(job_id, **fields)
            if updated is not None:
                self._persist_job(updated)
            return updated

    def save_result(self, submission_id: str, result: dict[str, Any]) -> None:
        import json

        with self._lock:
            super().save_result(submission_id, result)
            self._conn.execute(
                "INSERT INTO results (submission_id, payload) VALUES (?, ?) "
                "ON CONFLICT(submission_id) DO UPDATE SET payload=excluded.payload",
                (submission_id, json.dumps(result, default=str)),
            )
            self._conn.commit()


__all__ = ["InMemoryJobStore", "JobRecord", "JobStatus", "JobStore", "SQLiteJobStore"]
