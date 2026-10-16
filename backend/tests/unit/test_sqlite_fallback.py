"""Test SQLitePool fallback integration with repositories and security."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from answer_eval.core.security import hash_password, verify_password
from answer_eval.db.sqlite_pool import SQLitePool
from answer_eval.db.repositories import users as users_repo
from answer_eval.db.repositories import profiles as profiles_repo


@pytest.fixture
def sqlite_pool(tmp_path: Path):
    db_file = tmp_path / "test_evalai.db"
    pool = SQLitePool(str(db_file))
    pool.initialize()
    yield pool
    pool.close()


@pytest.mark.asyncio
async def test_user_lifecycle_with_sqlite_pool(sqlite_pool: SQLitePool):
    email = "naveen83d.a@gmail.com"
    raw_password = "SecretPassword123"
    hashed = hash_password(raw_password)
    code = "123456"
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)

    # 1. Create user
    user = await users_repo.create_user(
        sqlite_pool,
        email=email,
        hashed_password=hashed,
        verification_code=code,
        verification_expires_at=expires,
    )
    assert user is not None
    assert user["email"] == email
    assert user["is_verified"] is False
    user_id = user["id"]

    # 2. Get user by email
    fetched = await users_repo.get_user_by_email(sqlite_pool, email)
    assert fetched is not None
    assert fetched["id"] == user_id
    assert verify_password(raw_password, fetched["hashed_password"])

    # 3. Create/Ensure Profile
    profile = await profiles_repo.ensure_profile(
        sqlite_pool,
        user_id=user_id,
        email=email,
        full_name="Naveen A",
        department_ids=["Computer Science & Engineering"],
        subjects=["DS"],
    )
    assert profile is not None
    assert profile["full_name"] == "Naveen A"
    assert "DS" in profile["subjects"]

    # 4. Verify user with code
    verified = await users_repo.verify_user(sqlite_pool, email, code)
    assert verified is not None
    assert verified["is_verified"] is True

    # 5. Fetch profile
    prof_fetched = await profiles_repo.get_profile(sqlite_pool, user_id)
    assert prof_fetched is not None
    assert prof_fetched["email"] == email
