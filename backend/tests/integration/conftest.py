"""Integration-only fixtures.

The durable job store lives in the shared live database. Any integration test
that starts an assessment now enqueues real job_records (the API bridge), so
stale transient rows can leak between runs and break the determinism of tests
that claim "the oldest queued job" (e.g. test_jobs_pg). Sweep transient rows
before each integration test; tests are self-contained and never depend on
persisted queued/claimed jobs.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _sweep_transient_job_records():
    yield
    # Sweep AFTER each test so even a crashing test leaves the store clean for
    # the next one. Deleting only transient statuses; completed/failed/cancelled
    # (dead-letter) rows are retained.
    dsn = os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL")
    if not dsn or not Path(".env").exists():
        return
    try:
        import asyncpg
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001
        return

    async def sweep() -> None:
        conn = await asyncpg.connect(dsn, statement_cache_size=0)
        try:
            rows = await conn.fetch(
                "select job_id from job_records where status in ('queued','claimed','retrying','processing')"
            )
            ids = [r["job_id"] for r in rows]
            if ids:
                await conn.execute("delete from job_record_events where job_id = any($1::text[])", ids)
                await conn.execute(
                    "delete from job_records where status in ('queued','claimed','retrying','processing')"
                )
        finally:
            await conn.close()

    try:
        asyncio.run(sweep())
    except Exception:  # noqa: BLE001 - cleanup must never fail the test suite
        return
