"""Profile repository: rows in public.profiles keyed by auth.users.id."""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

_PROFILE_COLUMNS = "id, email, full_name, institution_id, role, department_ids, subjects"

_UNSET = object()


def _coerce_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except ValueError as exc:
        raise ValueError(f"Invalid user id '{user_id}'") from exc


def _to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["id"] = str(data["id"])
    if data.get("institution_id") is not None:
        data["institution_id"] = str(data["institution_id"])
    data["department_ids"] = _as_str_list(data.get("department_ids"))
    data["subjects"] = _as_str_list(data.get("subjects"))
    return data


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return []
        return [str(item) for item in decoded] if isinstance(decoded, list) else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


async def ensure_profile(
    pool: asyncpg.Pool,
    *,
    user_id: str,
    email: str,
    full_name: str = "",
    department_ids: list[str] | None = None,
    subjects: list[str] | None = None,
) -> dict[str, Any]:
    """Insert or synchronize profile on login/signup, matching on user_id or email."""
    norm_email = (email or "").lower().strip()
    u_id = _coerce_user_id(user_id)
    deps = department_ids or []
    subjs = subjects or []

    async with pool.acquire() as connection:
        # Check if profile exists by ID or email
        existing = await connection.fetchrow(
            "SELECT id, email, full_name, department_ids, subjects FROM profiles WHERE id = $1 OR LOWER(email) = $2 LIMIT 1",
            u_id,
            norm_email,
        )
        if existing:
            current_name = existing.get("full_name") or ""
            resolved_name = full_name.strip() if full_name and full_name.strip() else current_name
            resolved_deps = deps if deps else _as_str_list(existing.get("department_ids"))
            resolved_subjs = subjs if subjs else _as_str_list(existing.get("subjects"))

            update_query = f"""
                UPDATE profiles
                SET email = $1,
                    full_name = $2,
                    department_ids = $3,
                    subjects = $4,
                    updated_at = NOW()
                WHERE id = $5
                RETURNING {_PROFILE_COLUMNS}
            """
            row = await connection.fetchrow(
                update_query,
                norm_email,
                resolved_name,
                resolved_deps,
                resolved_subjs,
                existing["id"],
            )
            result = _to_dict(row)
            if result:
                return result

        # Insert new profile
        insert_query = f"""
            INSERT INTO profiles (id, email, full_name, department_ids, subjects)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING {_PROFILE_COLUMNS}
        """
        try:
            row = await connection.fetchrow(
                insert_query,
                u_id,
                norm_email,
                full_name.strip() if full_name else "",
                deps,
                subjs,
            )
            result = _to_dict(row)
            return result or {}
        except Exception:
            # Fallback in case of concurrent insert race condition
            fallback = await connection.fetchrow(
                "SELECT id, email, full_name, department_ids, subjects FROM profiles WHERE id = $1 OR LOWER(email) = $2 LIMIT 1",
                u_id,
                norm_email,
            )
            result = _to_dict(fallback)
            return result or {}


async def get_profile(pool: asyncpg.Pool, user_id: str) -> dict[str, Any] | None:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            f"select {_PROFILE_COLUMNS} from profiles where id = $1",
            _coerce_user_id(user_id),
        )
    return _to_dict(row)


async def update_profile(
    pool: asyncpg.Pool,
    user_id: str,
    *,
    full_name: str | None = None,
    department_ids: list[str] | None = None,
    subjects: list[str] | None = None,
    institution_id: Any = _UNSET,
) -> dict[str, Any] | None:
    assignments: list[str] = []
    values: list[Any] = [_coerce_user_id(user_id)]
    placeholder = 2

    if full_name is not None:
        assignments.append(f"full_name = ${placeholder}")
        values.append(full_name)
        placeholder += 1
    if department_ids is not None:
        assignments.append(f"department_ids = ${placeholder}")
        values.append(department_ids)
        placeholder += 1
    if subjects is not None:
        assignments.append(f"subjects = ${placeholder}")
        values.append(subjects)
        placeholder += 1
    if institution_id is not _UNSET:
        assignments.append(
            f"institution_id = ${placeholder}::uuid"
            if institution_id
            else "institution_id = null"
        )
        if institution_id:
            values.append(uuid.UUID(institution_id))
            placeholder += 1

    if not assignments:
        return await get_profile(pool, user_id)

    query = (
        f"update profiles set {', '.join(assignments)}, updated_at = now() "
        f"where id = $1 returning {_PROFILE_COLUMNS}"
    )
    async with pool.acquire() as connection:
        row = await connection.fetchrow(query, *values)
    return _to_dict(row)


def _json_list(items: list[str]) -> str:
    import json

    return json.dumps(list(items))
