"""Asyncpg connection pool lifecycle for the EvalAI control plane."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

logger = logging.getLogger(__name__)

# Pooler-specific query params that asyncpg would reject as startup parameters.
_NONSTANDARD_QUERY_PARAMS = {"pgbouncer", "connection_limit", "pool_timeout"}


def sanitize_dsn(dsn: str) -> str:
    """Drop non-Postgres query params (e.g. Supabase's ?pgbouncer=true)."""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return dsn
    if not parts.query:
        return dsn
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _NONSTANDARD_QUERY_PARAMS
    ]
    if len(kept) == len(parse_qsl(parts.query, keep_blank_values=True)):
        return dsn
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


async def _init_connection(connection: asyncpg.Connection) -> None:
    """Decode json/jsonb into Python objects instead of raw strings."""
    await connection.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await connection.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


from answer_eval.db.sqlite_pool import SQLitePool

class Database:
    """Thin wrapper around an asyncpg pool with automatic SQLite local fallback.

    `statement_cache_size=0` keeps the pool compatible with pgbouncer/Supavisor
    transaction pooling; it is harmless on direct connections.
    """

    def __init__(self, dsn: str, *, min_size: int = 0, max_size: int = 10) -> None:
        self._dsn = sanitize_dsn(dsn)
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any | None = None

    @property
    def connected(self) -> bool:
        return self._pool is not None

    @property
    def is_sqlite(self) -> bool:
        return isinstance(self._pool, SQLitePool)

    @property
    def pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("Database pool is not connected")
        return self._pool

    async def connect(self) -> None:
        if self._pool is not None:
            return

        # If DSN is explicitly SQLite or empty
        if not self._dsn or self._dsn.startswith("sqlite"):
            db_path = self._canonical_sqlite_path()
            logger.info("Using embedded SQLite database at %s", db_path)
            sqlite_pool = SQLitePool(db_path)
            sqlite_pool.initialize()
            self._pool = sqlite_pool
            return

        logger.info("Connecting to application database")
        try:
            pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                statement_cache_size=0,
                command_timeout=5,
                init=_init_connection,
            )
            # Verify connectivity immediately so unreachable PostgreSQL triggers SQLite fallback
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1;")
            self._pool = pool
            logger.info("Connected to PostgreSQL application database")
        except Exception as exc:
            db_path = self._canonical_sqlite_path()
            logger.warning(
                "PostgreSQL connection to %s failed (%s). "
                "Automatically activating embedded SQLite fallback at %s for local testing.",
                self._dsn.split("@")[-1] if "@" in self._dsn else self._dsn,
                exc,
                db_path,
            )
            sqlite_pool = SQLitePool(db_path)
            sqlite_pool.initialize()
            self._pool = sqlite_pool

    @staticmethod
    def _canonical_sqlite_path() -> str:
        from pathlib import Path
        root_data = Path(__file__).resolve().parents[3] / "data" / "evalai.db"
        if root_data.exists():
            return str(root_data)
        return "data/evalai.db"

    async def close(self) -> None:
        if self._pool is not None:
            if hasattr(self._pool, "close"):
                if asyncio.iscoroutinefunction(self._pool.close):
                    await self._pool.close()
                else:
                    self._pool.close()
            self._pool = None
