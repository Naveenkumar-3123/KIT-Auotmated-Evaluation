"""Worker fleet persistence + token auth (Milestone 15, specs #56-#60/#64).

Workers register once and receive a bearer token (only its SHA-256 hash is
stored). Every subsequent call verifies that hash. The Computers page reads
the fleet view from here (#60).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

import asyncpg


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def register_worker(
    pool: asyncpg.Pool,
    *,
    worker_id: str | None,
    hostname: str | None,
    hardware: dict[str, Any],
    model_profile: str | None,
    capabilities: list[str],
) -> dict[str, Any]:
    """Upsert a worker node; generate a fresh token on (re-)registration."""
    wid = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    token = secrets.token_urlsafe(32)
    row = await pool.fetchrow(
        """
        insert into worker_nodes
            (worker_id, token_hash, hostname, hardware, model_profile, capabilities, status)
        values ($1, $2, $3, $4::jsonb, $5, $6::text[], 'online')
        on conflict (worker_id) do update set
            token_hash = excluded.token_hash,
            hostname = excluded.hostname,
            hardware = excluded.hardware,
            model_profile = excluded.model_profile,
            capabilities = excluded.capabilities,
            status = 'online',
            last_seen_at = now()
        returning worker_id, hostname, hardware, model_profile, capabilities, status, last_seen_at
        """,
        wid,
        _hash_token(token),
        hostname,
        hardware,
        model_profile,
        capabilities,
    )
    return {"worker": dict(row), "token": token}


async def verify_worker_token(pool: asyncpg.Pool, worker_id: str, token: str) -> bool:
    row = await pool.fetchrow(
        "select token_hash from worker_nodes where worker_id = $1", worker_id
    )
    if row is None:
        return False
    return secrets.compare_digest(row["token_hash"], _hash_token(token))


async def record_heartbeat(
    pool: asyncpg.Pool,
    *,
    worker_id: str,
    stage: str | None,
    current_job_id: str | None,
    progress: float | None,
    ram_used_gb: float | None,
    vram_used_gb: float | None,
    status: str | None = None,
) -> dict[str, Any]:
    """Record one heartbeat; returns the fleet-facing snapshot for this worker."""
    await pool.execute(
        """
        insert into worker_heartbeats
            (worker_id, stage, current_job_id, ram_used_gb, vram_used_gb, progress)
        values ($1, $2, $3::uuid, $4, $5, $6)
        """,
        worker_id,
        stage,
        uuid.UUID(current_job_id) if current_job_id else None,
        ram_used_gb,
        vram_used_gb,
        progress,
    )
    row = await pool.fetchrow(
        """
        update worker_nodes set
            last_seen_at = now(),
            status = coalesce($2, case when current_job_id is null then 'idle' else 'busy' end),
            current_job_id = coalesce($3::uuid, current_job_id)
        where worker_id = $1
        returning worker_id, status, current_job_id, last_seen_at
        """,
        worker_id,
        status,
        current_job_id,
    )
    return dict(row) if row else {}


async def list_workers(pool: asyncpg.Pool, *, stale_after_s: int = 120) -> list[dict[str, Any]]:
    """Fleet view for the Computers page (#60): node + latest heartbeat."""
    rows = await pool.fetch(
        """
        select n.worker_id, n.hostname, n.hardware, n.model_profile, n.capabilities,
               n.status as registered_status, n.current_job_id, n.last_seen_at,
               (select stage from worker_heartbeats hb where hb.worker_id = n.worker_id order by created_at desc limit 1) as stage,
               (select progress from worker_heartbeats hb where hb.worker_id = n.worker_id order by created_at desc limit 1) as progress,
               (select ram_used_gb from worker_heartbeats hb where hb.worker_id = n.worker_id order by created_at desc limit 1) as ram_used_gb,
               (select vram_used_gb from worker_heartbeats hb where hb.worker_id = n.worker_id order by created_at desc limit 1) as vram_used_gb,
               (select created_at from worker_heartbeats hb where hb.worker_id = n.worker_id order by created_at desc limit 1) as beat_at,
               (select sub.roll_number from submissions sub where sub.id = n.current_job_id limit 1) as roll_number
        from worker_nodes n
        order by n.worker_id
        """
    )
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        last_seen = item.pop("last_seen_at")
        beat_at = item.pop("beat_at")

        if isinstance(last_seen, str):
            try:
                last_seen = dt.datetime.fromisoformat(last_seen)
            except Exception:
                pass
        if isinstance(beat_at, str):
            try:
                beat_at = dt.datetime.fromisoformat(beat_at)
            except Exception:
                pass

        stale = (
            last_seen is None
            or (now - (last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=dt.UTC))).total_seconds()
            > stale_after_s
        )
        item["online"] = bool(last_seen) and not stale
        item["last_seen_at"] = last_seen.isoformat() if last_seen else None
        item["latest_beat_at"] = beat_at.isoformat() if beat_at else None
        if item["current_job_id"] is not None:
            item["current_job_id"] = str(item["current_job_id"])
        results.append(item)
    return results


__all__ = [
    "list_workers",
    "record_heartbeat",
    "register_worker",
    "verify_worker_token",
]
