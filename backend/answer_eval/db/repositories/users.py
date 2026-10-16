"""User repository: rows in public.users for native PostgreSQL authentication."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

_USER_COLUMNS = (
    "id, email, hashed_password, is_verified, verification_code, "
    "verification_expires_at, reset_token, reset_expires_at, created_at, updated_at"
)


def _to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["id"] = str(data["id"])
    if "is_verified" in data:
        data["is_verified"] = bool(data["is_verified"])
    return data


async def create_user(
    pool: asyncpg.Pool,
    *,
    email: str,
    hashed_password: str,
    verification_code: str,
    verification_expires_at: datetime,
) -> dict[str, Any]:
    """Create a new user with an unverified status and verification code."""
    query = f"""
        INSERT INTO users (email, hashed_password, is_verified, verification_code, verification_expires_at)
        VALUES ($1, $2, FALSE, $3, $4)
        RETURNING {_USER_COLUMNS}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query,
            email.lower().strip(),
            hashed_password,
            verification_code,
            verification_expires_at,
        )
    result = _to_dict(row)
    assert result is not None
    return result


async def get_user_by_email(pool: asyncpg.Pool, email: str) -> dict[str, Any] | None:
    """Look up a user by email address."""
    query = f"SELECT {_USER_COLUMNS} FROM users WHERE LOWER(email) = LOWER($1)"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, email.strip())
    return _to_dict(row)


async def get_user_by_id(pool: asyncpg.Pool, user_id: str) -> dict[str, Any] | None:
    """Look up a user by user UUID."""
    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        return None
    query = f"SELECT {_USER_COLUMNS} FROM users WHERE id = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_uuid)
    return _to_dict(row)


async def verify_user(pool: asyncpg.Pool, email: str, code: str) -> dict[str, Any] | None:
    """Verify a user if the code matches and has not expired."""
    now = datetime.now(timezone.utc)
    query = f"""
        UPDATE users
        SET is_verified = TRUE,
            verification_code = NULL,
            verification_expires_at = NULL,
            updated_at = NOW()
        WHERE LOWER(email) = LOWER($1)
          AND verification_code = $2
          AND verification_expires_at >= $3
        RETURNING {_USER_COLUMNS}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, email.strip(), code.strip(), now)
    return _to_dict(row)


async def update_verification_code(
    pool: asyncpg.Pool,
    email: str,
    code: str,
    expires_at: datetime,
) -> bool:
    """Update verification code for resending."""
    query = """
        UPDATE users
        SET verification_code = $1,
            verification_expires_at = $2,
            updated_at = NOW()
        WHERE LOWER(email) = LOWER($3)
    """
    async with pool.acquire() as conn:
        result = await conn.execute(query, code.strip(), expires_at, email.strip())
    return "UPDATE 1" in result


async def set_reset_token(
    pool: asyncpg.Pool,
    email: str,
    token: str,
    expires_at: datetime,
) -> bool:
    """Store password reset token and expiration."""
    query = """
        UPDATE users
        SET reset_token = $1,
            reset_expires_at = $2,
            updated_at = NOW()
        WHERE LOWER(email) = LOWER($3)
    """
    async with pool.acquire() as conn:
        result = await conn.execute(query, token, expires_at, email.strip())
    return "UPDATE 1" in result


async def reset_password(
    pool: asyncpg.Pool,
    token: str,
    hashed_password: str,
) -> dict[str, Any] | None:
    """Reset password using a valid reset token."""
    now = datetime.now(timezone.utc)
    query = f"""
        UPDATE users
        SET hashed_password = $1,
            reset_token = NULL,
            reset_expires_at = NULL,
            updated_at = NOW()
        WHERE reset_token = $2
          AND reset_expires_at >= $3
        RETURNING {_USER_COLUMNS}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, hashed_password, token, now)
    return _to_dict(row)


async def update_password(
    pool: asyncpg.Pool,
    user_id: str,
    hashed_password: str,
) -> bool:
    """Directly update user password (for authenticated user)."""
    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        return False
    query = "UPDATE users SET hashed_password = $1, updated_at = NOW() WHERE id = $2"
    async with pool.acquire() as conn:
        result = await conn.execute(query, hashed_password, user_uuid)
    return "UPDATE 1" in result
