"""Database migration runner for standalone PostgreSQL.

Applies `0001_postgres_init.sql` using asyncpg.
Usage:
    python backend/tools/migrate_db.py
"""

import asyncio
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from dotenv import load_dotenv
    load_dotenv(backend_dir / ".env")
    load_dotenv(backend_dir.parent / ".env")
except ImportError:
    pass

import asyncpg
from answer_eval.db.pool import sanitize_dsn


async def run_migrations(dsn: str | None = None) -> None:
    db_url = dsn or os.getenv("DATABASE_URL")
    if not db_url:
        print("[ERROR] DATABASE_URL environment variable is not set.")
        print("Please configure DATABASE_URL in backend/.env, for example:")
        print("  DATABASE_URL=postgresql://postgres:password@localhost:5432/evalai")
        sys.exit(1)

    clean_dsn = sanitize_dsn(db_url)
    migration_file = backend_dir / "answer_eval" / "db" / "migrations" / "0001_postgres_init.sql"
    if not migration_file.exists():
        print(f"[ERROR] Migration file not found: {migration_file}")
        sys.exit(1)

    sql = migration_file.read_text(encoding="utf-8")

    print(f"Connecting to database...")
    try:
        conn = await asyncpg.connect(clean_dsn)
    except Exception as e:
        print(f"[ERROR] Could not connect to PostgreSQL: {e}")
        print("Ensure PostgreSQL is running and credentials in DATABASE_URL are correct.")
        sys.exit(1)

    try:
        print("Applying migration 0001_postgres_init.sql...")
        await conn.execute(sql)
        print("[SUCCESS] Migrations executed successfully!")

        rows = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        table_names = [r["table_name"] for r in rows]
        print(f"Verified tables in public schema ({len(table_names)} tables):")
        for name in table_names:
            print(f"  - {name}")
    finally:
        await conn.close()


def main() -> None:
    asyncio.run(run_migrations())


if __name__ == "__main__":
    main()
