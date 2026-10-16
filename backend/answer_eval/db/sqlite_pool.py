"""Embedded SQLite database adapter for single-PC local development.

Provides an asyncpg-compatible interface (acquire(), fetchrow(), fetch(), fetchval(), execute(), transaction())
so that EvalAI works out-of-the-box when PostgreSQL is not installed or reachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SQLiteRecord(dict):
    """Asyncpg.Record-compatible mapping for SQLite rows."""

    def __init__(self, keys: list[str], values: tuple[Any, ...]):
        parsed_values: list[Any] = []
        for v in values:
            if isinstance(v, str) and len(v) >= 2 and (
                (v[0] == "{" and v[-1] == "}") or (v[0] == "[" and v[-1] == "]")
            ):
                try:
                    parsed_values.append(json.loads(v))
                    continue
                except Exception:
                    pass
            parsed_values.append(v)
        super().__init__(zip(keys, parsed_values))
        self._keys = keys
        self._values = tuple(parsed_values)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        return super().get(key, default)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class _JsonAgg:
    """SQLite aggregate function implementing Postgres jsonb_agg / json_agg."""

    def __init__(self) -> None:
        self.items: list[Any] = []

    def step(self, value: Any) -> None:
        if value is not None:
            if isinstance(value, str) and len(value) >= 2 and (
                (value[0] == "{" and value[-1] == "}") or (value[0] == "[" and value[-1] == "]")
            ):
                try:
                    self.items.append(json.loads(value))
                    return
                except Exception:
                    pass
            self.items.append(value)

    def finalize(self) -> str:
        return json.dumps(self.items)


class _BoolOr:
    """SQLite aggregate function implementing Postgres bool_or."""

    def __init__(self) -> None:
        self.result = False

    def step(self, value: Any) -> None:
        if bool(value):
            self.result = True

    def finalize(self) -> int:
        return 1 if self.result else 0


class _BoolAnd:
    """SQLite aggregate function implementing Postgres bool_and."""

    def __init__(self) -> None:
        self.result = True

    def step(self, value: Any) -> None:
        if not bool(value):
            self.result = False

    def finalize(self) -> int:
        return 1 if self.result else 0


class _TransactionContext:
    """Async context manager providing transaction support via SQLite SAVEPOINTs."""

    def __init__(self, connection: SQLiteConnection) -> None:
        self._connection = connection
        self._sp_name = f"sp_{uuid.uuid4().hex[:8]}"

    async def __aenter__(self) -> SQLiteConnection:
        await self._connection.execute(f"SAVEPOINT {self._sp_name};")
        return self._connection

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            try:
                await self._connection.execute(f"ROLLBACK TO {self._sp_name};")
            except Exception:
                pass
            try:
                await self._connection.execute(f"RELEASE SAVEPOINT {self._sp_name};")
            except Exception:
                pass
        else:
            try:
                await self._connection.execute(f"RELEASE SAVEPOINT {self._sp_name};")
            except Exception:
                pass


class SQLiteConnection:
    """Connection wrapper executing queries on a dedicated connection with asyncpg-compatible API."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    def _prepare_sql_and_params(self, query: str, args: tuple[Any, ...]) -> tuple[str, list[Any]]:
        # Remove PostgreSQL typecasts like ::jsonb, ::text, ::uuid, ::numeric(5,2), ::text[]
        sql = re.sub(r"::[a-zA-Z_0-9]+(?:\([^)]*\))?(?:\[\])?", "", query)
        # Replace $1, $2 with ?1, ?2
        sql = re.sub(r"\$(\d+)", r"?\1", sql)

        # Transform PostgreSQL '= ANY(?N)' or '= any(?N)' into 'IN (SELECT value FROM json_each(?N))'
        sql = re.sub(
            r"=\s*any\s*\(\s*(\?\d+)\s*\)",
            r"IN (SELECT value FROM json_each(\1))",
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(
            r"(?:!=|<>)\s*any\s*\(\s*(\?\d+)\s*\)",
            r"NOT IN (SELECT value FROM json_each(\1))",
            sql,
            flags=re.IGNORECASE,
        )

        # Transform PostgreSQL UPDATE table alias if present (e.g. UPDATE tbl a SET ... WHERE a.id = ?1)
        m = re.match(r"^\s*update\s+([a-zA-Z_0-9]+)\s+([a-zA-Z_0-9]+)\s+set\s+", sql, flags=re.IGNORECASE)
        if m:
            tbl, alias = m.group(1), m.group(2)
            if alias.lower() not in ("set", "or", "from"):
                sql = re.sub(r"^\s*update\s+" + tbl + r"\s+" + alias + r"\s+set\s+", f"update {tbl} set ", sql, flags=re.IGNORECASE)
                sql = re.sub(r"\b" + alias + r"\.([a-zA-Z_0-9]+)", r"\1", sql)

        # Convert parameter types
        converted_args: list[Any] = []
        for arg in args:
            if isinstance(arg, uuid.UUID):
                converted_args.append(str(arg))
            elif isinstance(arg, datetime):
                converted_args.append(arg.isoformat())
            elif isinstance(arg, (list, dict, tuple, set)):
                converted_args.append(json.dumps(list(arg) if isinstance(arg, (set, tuple)) else arg))
            else:
                converted_args.append(arg)

        return sql, converted_args

    def _sync_fetchrow(self, sql: str, params: list[Any]) -> SQLiteRecord | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            keys = [d[0].lower() for d in cur.description] if cur.description else []
            return SQLiteRecord(keys, tuple(row))

    def _sync_fetch(self, sql: str, params: list[Any]) -> list[SQLiteRecord]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                return []
            keys = [d[0].lower() for d in cur.description] if cur.description else []
            return [SQLiteRecord(keys, tuple(r)) for r in rows]

    def _sync_fetchval(self, sql: str, params: list[Any]) -> Any:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None or len(row) == 0:
                return None
            val = row[0]
            if isinstance(val, str) and len(val) >= 2 and (
                (val[0] == "{" and val[-1] == "}") or (val[0] == "[" and val[-1] == "]")
            ):
                try:
                    return json.loads(val)
                except Exception:
                    pass
            return val

    def _sync_execute(self, sql: str, params: list[Any]) -> str:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return f"UPDATE {cur.rowcount}"

    async def fetchrow(self, query: str, *args: Any) -> SQLiteRecord | None:
        sql, params = self._prepare_sql_and_params(query, args)
        return await asyncio.to_thread(self._sync_fetchrow, sql, params)

    async def fetch(self, query: str, *args: Any) -> list[SQLiteRecord]:
        sql, params = self._prepare_sql_and_params(query, args)
        return await asyncio.to_thread(self._sync_fetch, sql, params)

    async def fetchval(self, query: str, *args: Any) -> Any:
        sql, params = self._prepare_sql_and_params(query, args)
        return await asyncio.to_thread(self._sync_fetchval, sql, params)

    async def execute(self, query: str, *args: Any) -> str:
        sql, params = self._prepare_sql_and_params(query, args)
        return await asyncio.to_thread(self._sync_execute, sql, params)

    def transaction(self) -> _TransactionContext:
        return _TransactionContext(self)


class _AcquireContext:
    def __init__(self, connection: SQLiteConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> SQLiteConnection:
        return self._connection

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class SQLitePool:
    """Emulates asyncpg.Pool using an embedded SQLite database."""

    def __init__(self, db_path: str = "data/evalai.db") -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._connection_wrapper: SQLiteConnection | None = None

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,  # Autocommit mode; transactions managed via SAVEPOINTs
        )
        self._conn.create_function("now", 0, _now_iso)
        self._conn.create_function("gen_random_uuid", 0, _gen_uuid)
        self._conn.create_function(
            "jsonb_build_object",
            -1,
            lambda *a: json.dumps({a[i]: a[i + 1] for i in range(0, len(a) - 1, 2)}),
        )
        self._conn.create_function(
            "json_build_object",
            -1,
            lambda *a: json.dumps({a[i]: a[i + 1] for i in range(0, len(a) - 1, 2)}),
        )
        self._conn.create_aggregate("jsonb_agg", 1, _JsonAgg)
        self._conn.create_aggregate("json_agg", 1, _JsonAgg)
        self._conn.create_aggregate("bool_or", 1, _BoolOr)
        self._conn.create_aggregate("bool_and", 1, _BoolAnd)
        self._conn.create_function(
            "regexp_replace",
            3,
            lambda t, p, r: re.sub(p, r, str(t)) if t is not None else None,
        )
        self._connection_wrapper = SQLiteConnection(self._conn, self._lock)
        self._create_schema()

    def _create_schema(self) -> None:
        assert self._conn is not None

        # Detect outdated schema definitions and drop incompatible empty tables
        with self._lock:
            cur = self._conn.cursor()
            legacy_checks = [
                ("assessments", "teacher_id"),
                ("answer_keys", "assessment_id"),
                ("submissions", "roll_number"),
                ("submissions", "pdf_sha256"),
                ("assessment_students", "roll_number"),
            ]
            for tbl, required_col in legacy_checks:
                cur.execute(f"PRAGMA table_info({tbl})")
                cols = [r[1] for r in cur.fetchall()]
                if cols and required_col not in cols:
                    logger.info(
                        "Upgrading SQLite schema: replacing legacy %s table (missing %s)", tbl, required_col
                    )
                    cur.execute(f"DROP TABLE IF EXISTS {tbl}")

            # Ensure submissions table has any recently introduced columns
            cur.execute("PRAGMA table_info(submissions)")
            sub_cols = [r[1] for r in cur.fetchall()]
            if sub_cols:
                if "uploaded_by" not in sub_cols:
                    logger.info("Upgrading SQLite schema: adding uploaded_by to submissions")
                    cur.execute("ALTER TABLE submissions ADD COLUMN uploaded_by TEXT")
                if "status_detail" not in sub_cols:
                    logger.info("Upgrading SQLite schema: adding status_detail to submissions")
                    cur.execute("ALTER TABLE submissions ADD COLUMN status_detail TEXT")
                if "flags" not in sub_cols:
                    logger.info("Upgrading SQLite schema: adding flags to submissions")
                    cur.execute("ALTER TABLE submissions ADD COLUMN flags TEXT NOT NULL DEFAULT '[]'")

            cur.execute("PRAGMA table_info(questions)")
            q_cols = [r[1] for r in cur.fetchall()]
            if q_cols and "options" not in q_cols:
                logger.info("Upgrading SQLite schema: adding options to questions")
                cur.execute("ALTER TABLE questions ADD COLUMN options TEXT NOT NULL DEFAULT '[]'")

            cur.execute("PRAGMA table_info(answer_key_diagrams)")
            d_cols = [r[1] for r in cur.fetchall()]
            if d_cols and "option_code" not in d_cols:
                logger.info("Upgrading SQLite schema: adding option_code to answer_key_diagrams")
                cur.execute("ALTER TABLE answer_key_diagrams ADD COLUMN option_code TEXT")

        schema_sql = """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            email TEXT NOT NULL UNIQUE,
            hashed_password TEXT NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 0,
            verification_code TEXT,
            verification_expires_at TEXT,
            reset_token TEXT,
            reset_expires_at TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS institutions (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL DEFAULT '',
            institution_id TEXT,
            role TEXT NOT NULL DEFAULT 'teacher',
            department_ids TEXT NOT NULL DEFAULT '[]',
            subjects TEXT NOT NULL DEFAULT '[]',
            settings TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS classes (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            institution_id TEXT,
            created_by TEXT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            institution_id TEXT,
            created_by TEXT,
            name TEXT NOT NULL,
            code TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS teacher_classes (
            teacher_id TEXT NOT NULL,
            class_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (now()),
            PRIMARY KEY (teacher_id, class_id)
        );

        CREATE TABLE IF NOT EXISTS teacher_subjects (
            teacher_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (now()),
            PRIMARY KEY (teacher_id, subject_id)
        );

        CREATE TABLE IF NOT EXISTS assessments (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            teacher_id TEXT NOT NULL,
            class_id TEXT,
            subject_id TEXT,
            title TEXT NOT NULL DEFAULT 'Untitled assessment',
            status TEXT NOT NULL DEFAULT 'draft',
            pass_percentage REAL NOT NULL DEFAULT 40,
            total_marks REAL NOT NULL DEFAULT 0,
            question_count INTEGER NOT NULL DEFAULT 0,
            locked_answer_key_version INTEGER,
            locked_policy_version INTEGER,
            rubric_version TEXT,
            started_at TEXT,
            completed_at TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS answer_keys (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            source_object_key TEXT NOT NULL,
            source_format TEXT NOT NULL,
            source_sha256 TEXT,
            raw_parser_json TEXT,
            parser_model TEXT,
            parser_prompt_version TEXT,
            schema_version TEXT NOT NULL DEFAULT 'answer-key-v1',
            status TEXT NOT NULL DEFAULT 'parsing',
            parse_error TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now()),
            UNIQUE (assessment_id, version)
        );

        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            answer_key_id TEXT NOT NULL,
            question_number INTEGER NOT NULL,
            ordinal INTEGER,
            question_text TEXT NOT NULL DEFAULT '',
            maximum_marks REAL NOT NULL,
            answer_type TEXT NOT NULL DEFAULT 'descriptive',
            expected_answer_text TEXT,
            math_rubric TEXT,
            parser_uncertainties TEXT,
            options TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS question_answer_keys (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (now()),
            UNIQUE (assessment_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS expected_concepts (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            question_id TEXT NOT NULL,
            concept_code TEXT NOT NULL,
            description TEXT NOT NULL,
            maximum_marks REAL NOT NULL,
            ordinal INTEGER,
            UNIQUE (question_id, concept_code)
        );

        CREATE TABLE IF NOT EXISTS keywords (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            question_id TEXT NOT NULL,
            term TEXT NOT NULL,
            UNIQUE (question_id, term)
        );

        CREATE TABLE IF NOT EXISTS mandatory_terms (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            question_id TEXT NOT NULL,
            term TEXT NOT NULL,
            UNIQUE (question_id, term)
        );

        CREATE TABLE IF NOT EXISTS diagram_hints (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            question_id TEXT NOT NULL,
            hint_type TEXT,
            label TEXT,
            ordinal INTEGER
        );

        CREATE TABLE IF NOT EXISTS answer_key_diagrams (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            question_id TEXT NOT NULL,
            diagram_code TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            type_label TEXT,
            image_object_key TEXT NOT NULL,
            source_page INTEGER,
            bbox TEXT,
            parser_uncertain INTEGER NOT NULL DEFAULT 0,
            option_code TEXT
        );

        CREATE TABLE IF NOT EXISTS diagram_requirements (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            question_id TEXT NOT NULL,
            required INTEGER NOT NULL DEFAULT 0,
            count_required INTEGER NOT NULL DEFAULT 0,
            required_labels TEXT NOT NULL DEFAULT '[]',
            required_components TEXT NOT NULL DEFAULT '[]',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS strictness_policies (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            question_from INTEGER,
            question_to INTEGER,
            question_number INTEGER,
            level TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS word_count_policies (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            question_from INTEGER,
            question_to INTEGER,
            question_number INTEGER,
            minimum_words INTEGER NOT NULL,
            mode TEXT NOT NULL,
            trigger_shortfall_words INTEGER NOT NULL,
            marks_deducted REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS diagram_policies (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            question_from INTEGER,
            question_to INTEGER,
            question_number INTEGER,
            required_elements TEXT NOT NULL,
            marks_allocated REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resolved_policy_snapshots (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            policy_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS question_policies (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            question_number INTEGER NOT NULL,
            strictness_level TEXT NOT NULL DEFAULT 'moderate',
            minimum_words INTEGER NOT NULL DEFAULT 0,
            word_count_mode TEXT NOT NULL DEFAULT 'once',
            trigger_shortfall_words INTEGER NOT NULL DEFAULT 0,
            marks_deducted REAL NOT NULL DEFAULT 0,
            diagram_required INTEGER NOT NULL DEFAULT 0,
            min_diagrams INTEGER NOT NULL DEFAULT 0,
            missing_diagram_deductions TEXT NOT NULL DEFAULT '[]',
            source_rule_ids TEXT NOT NULL DEFAULT '[]',
            rubric_snapshot TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            UNIQUE (assessment_id, version, question_number)
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'uploaded',
            status_detail TEXT,
            pdf_object_key TEXT,
            pdf_sha256 TEXT,
            page_count INTEGER,
            flags TEXT NOT NULL DEFAULT '[]',
            uploaded_by TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS submission_files (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            submission_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            object_key TEXT NOT NULL,
            sha256 TEXT,
            size_bytes INTEGER,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS assessment_students (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            display_name TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            status_detail TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now()),
            UNIQUE (assessment_id, roll_number)
        );

        CREATE TABLE IF NOT EXISTS job_records (
            job_id TEXT PRIMARY KEY,
            submission_id TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            worker_id TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now()),
            lease_expires_at TEXT,
            next_attempt_at TEXT,
            payload TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS job_results (
            submission_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS job_record_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS evaluation_reviews (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            assessment_id TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            teacher_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            flag_reason TEXT,
            adjusted_score REAL,
            teacher_feedback TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS worker_nodes (
            worker_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL,
            hostname TEXT,
            hardware TEXT NOT NULL DEFAULT '{}',
            model_profile TEXT,
            capabilities TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'offline',
            current_job_id TEXT,
            registered_at TEXT NOT NULL DEFAULT (now()),
            last_seen_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            stage TEXT,
            current_job_id TEXT,
            ram_used_gb REAL,
            vram_used_gb REAL,
            progress REAL,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS evaluation_results (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            submission_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            marks_awarded REAL NOT NULL DEFAULT 0,
            marks_maximum REAL NOT NULL DEFAULT 0,
            confidence REAL,
            raw_evaluation_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS criterion_scores (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            result_id TEXT NOT NULL,
            concept_code TEXT NOT NULL,
            awarded REAL NOT NULL DEFAULT 0,
            maximum REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            match_type TEXT,
            evidence TEXT NOT NULL DEFAULT '[]',
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS verification_results (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            result_id TEXT NOT NULL,
            criteria TEXT NOT NULL DEFAULT '[]',
            proposed_marks REAL NOT NULL DEFAULT 0,
            model_id TEXT,
            prompt_version TEXT,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS verification_comparisons (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            result_id TEXT NOT NULL,
            comparison TEXT NOT NULL DEFAULT '{}',
            total_delta REAL NOT NULL DEFAULT 0,
            agreement_rate REAL,
            major_disagreement INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS risk_results (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            result_id TEXT NOT NULL,
            risk_score REAL NOT NULL DEFAULT 0,
            level TEXT NOT NULL,
            signals TEXT NOT NULL DEFAULT '[]',
            mandatory_review INTEGER NOT NULL DEFAULT 0,
            reasons TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS teacher_reviews (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            result_id TEXT,
            assessment_id TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reasons TEXT NOT NULL DEFAULT '[]',
            reviewer_id TEXT,
            note TEXT,
            decided_at TEXT,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS teacher_overrides (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            review_id TEXT NOT NULL,
            target TEXT NOT NULL,
            target_key TEXT,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            reviewer_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS final_results (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            submission_id TEXT NOT NULL,
            assessment_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            marks_awarded REAL NOT NULL DEFAULT 0,
            marks_maximum REAL NOT NULL DEFAULT 0,
            deductions TEXT NOT NULL DEFAULT '[]',
            breakdown TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL DEFAULT 'ai',
            approved_by TEXT,
            result_id TEXT,
            review_id TEXT,
            answer_key_version INTEGER,
            policy_version INTEGER,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now()),
            UNIQUE (submission_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS student_totals (
            id TEXT PRIMARY KEY DEFAULT (gen_random_uuid()),
            submission_id TEXT NOT NULL UNIQUE,
            assessment_id TEXT NOT NULL,
            total REAL NOT NULL DEFAULT 0,
            maximum REAL NOT NULL DEFAULT 0,
            percentage REAL NOT NULL DEFAULT 0,
            passed INTEGER,
            rank INTEGER,
            status TEXT NOT NULL DEFAULT 'in_progress',
            version INTEGER NOT NULL DEFAULT 1,
            computed_at TEXT NOT NULL DEFAULT (now()),
            created_at TEXT NOT NULL DEFAULT (now()),
            updated_at TEXT NOT NULL DEFAULT (now())
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            before TEXT,
            after TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL DEFAULT (now())
        );
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(schema_sql)

    def acquire(self) -> _AcquireContext:
        if self._connection_wrapper is None:
            raise RuntimeError("SQLite database pool is not connected")
        return _AcquireContext(self._connection_wrapper)

    async def fetchrow(self, query: str, *args: Any) -> SQLiteRecord | None:
        if self._connection_wrapper is None:
            raise RuntimeError("SQLite database pool is not connected")
        return await self._connection_wrapper.fetchrow(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[SQLiteRecord]:
        if self._connection_wrapper is None:
            raise RuntimeError("SQLite database pool is not connected")
        return await self._connection_wrapper.fetch(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self._connection_wrapper is None:
            raise RuntimeError("SQLite database pool is not connected")
        return await self._connection_wrapper.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        if self._connection_wrapper is None:
            raise RuntimeError("SQLite database pool is not connected")
        return await self._connection_wrapper.execute(query, *args)

    def transaction(self) -> _TransactionContext:
        if self._connection_wrapper is None:
            raise RuntimeError("SQLite database pool is not connected")
        return _TransactionContext(self._connection_wrapper)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                self._connection_wrapper = None
