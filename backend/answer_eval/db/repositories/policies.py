"""Policy rules CRUD + resolved snapshot persistence."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg

from answer_eval.grading.policy_resolution import (
    DiagramRule,
    KeyQuestionFacts,
    StrictnessRule,
    WordCountRule,
    resolve_policies,
    snapshot_for_storage,
)


def _uuid(value: str) -> uuid.UUID:
    return uuid.UUID(str(value))


async def replace_rules(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    strictness: list[StrictnessRule],
    word_count: list[WordCountRule],
    diagrams: list[DiagramRule],
) -> None:
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "delete from strictness_policies where assessment_id = $1", _uuid(assessment_id)
        )
        await connection.execute(
            "delete from word_count_policies where assessment_id = $1", _uuid(assessment_id)
        )
        await connection.execute(
            "delete from diagram_policies where assessment_id = $1", _uuid(assessment_id)
        )
        for rule in strictness:
            await connection.execute(
                """insert into strictness_policies
                   (assessment_id, scope_type, question_from, question_to, question_number, level)
                   values ($1, $2, $3, $4, $5, $6)""",
                _uuid(assessment_id),
                "question" if rule.question_number else "range",
                rule.question_from or None,
                rule.question_to or None,
                rule.question_number,
                rule.level,
            )
        for rule in word_count:
            await connection.execute(
                """insert into word_count_policies
                   (assessment_id, scope_type, question_from, question_to, question_number,
                    minimum_words, mode, trigger_shortfall_words, marks_deducted)
                   values ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                _uuid(assessment_id),
                "question" if rule.question_number else "range",
                rule.question_from or None,
                rule.question_to or None,
                rule.question_number,
                rule.minimum_words,
                rule.mode,
                rule.trigger_shortfall_words,
                rule.marks_deducted,
            )
        for rule in diagrams:
            await connection.execute(
                """insert into diagram_policies
                   (assessment_id, scope_type, question_from, question_to, question_number,
                    required, minimum_diagrams, missing_diagram_deductions)
                   values ($1, $2, $3, $4, $5, $6, $7, $8)""",
                _uuid(assessment_id),
                "question" if rule.question_number else "range",
                rule.question_from or None,
                rule.question_to or None,
                rule.question_number,
                rule.required,
                rule.minimum_diagrams,
                list(rule.missing_diagram_deductions),
            )


async def key_question_facts(pool: asyncpg.Pool, assessment_id: str) -> dict[int, KeyQuestionFacts]:
    rows = await pool.fetch(
        """
        select q.question_number, q.maximum_marks,
               coalesce(dr.required, false) as key_required,
               coalesce(dr.count_required, 0) as key_count
        from question_answer_keys qak
        join questions q on q.id = qak.question_id
        left join diagram_requirements dr on dr.question_id = q.id
        where qak.assessment_id = $1 and qak.active
        """,
        _uuid(assessment_id),
    )
    facts: dict[int, KeyQuestionFacts] = {}
    for row in rows:
        facts[int(row["question_number"])] = KeyQuestionFacts(
            maximum_marks=float(row["maximum_marks"]),
            key_diagram_required=bool(row["key_required"]),
            key_diagram_count=int(row["key_count"] or 0),
        )
    return facts


async def persist_resolved(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    resolved_rows: list[dict[str, Any]],
    rubric_snapshots: dict[int, dict[str, Any]] | None = None,
) -> int:
    """Store a new resolved policy version and return its version number.

    The UI saves policies with several near-simultaneous PUTs; the version must
    therefore be computed INSIDE the write transaction (otherwise two requests
    read the same max(version) and collide on the unique key), with a retry on
    the rare residual race between concurrent transactions.
    """
    last_exc: Exception | None = None
    for _attempt in range(3):
        try:
            async with pool.acquire() as connection, connection.transaction():
                version_row = await connection.fetchval(
                    "select coalesce(max(version), 0) + 1 from question_policies where assessment_id = $1",
                    _uuid(assessment_id),
                )
                version = int(version_row or 1)
                await connection.execute(
                    "delete from question_policies where assessment_id = $1", _uuid(assessment_id)
                )
                for row in resolved_rows:
                    number = row["question_number"]
                    await connection.execute(
                        """
                        insert into question_policies
                            (assessment_id, version, question_number, strictness_level,
                             minimum_words, word_count_mode, trigger_shortfall_words, marks_deducted,
                             diagram_required, min_diagrams, missing_diagram_deductions,
                             source_rule_ids, rubric_snapshot)
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        """,
                        _uuid(assessment_id),
                        version,
                        number,
                        row["strictness_level"],
                        row["minimum_words"],
                        row["word_count_mode"],
                        row["trigger_shortfall_words"],
                        row["marks_deducted"],
                        row["diagram_required"],
                        row["min_diagrams"],
                        row["missing_diagram_deductions"],
                        row["source_rule_ids"],
                        (rubric_snapshots or {}).get(number, {}),
                    )
            return version
        except asyncpg.exceptions.UniqueViolationError as exc:  # pragma: no cover - race window
            last_exc = exc
            continue
    assert last_exc is not None
    raise last_exc


async def get_resolved(
    pool: asyncpg.Pool, *, assessment_id: str, version: int | None = None
) -> list[dict[str, Any]]:
    if version is None:
        row = await pool.fetchrow(
            """select id from question_policies where assessment_id = $1
               order by version desc limit 1""",
            _uuid(assessment_id),
        )
        if row is None:
            return []
        rows = await pool.fetch(
            """select * from question_policies where assessment_id = $1
               order by version desc, question_number""",
            _uuid(assessment_id),
        )
    else:
        rows = await pool.fetch(
            "select * from question_policies where assessment_id = $1 and version = $2 order by question_number",
            _uuid(assessment_id),
            version,
        )
    results = []
    latest_version = max((r["version"] for r in rows), default=0)
    for row in rows:
        if version is None and row["version"] != latest_version:
            continue
        item = dict(row)
        item["id"] = str(item["id"])
        results.append(item)
    return results


async def build_and_store_resolution(
    pool: asyncpg.Pool,
    *,
    assessment_id: str,
    question_numbers: list[int],
    strictness: list[StrictnessRule],
    word_count: list[WordCountRule],
    diagrams: list[DiagramRule],
    rubric_snapshots: dict[int, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    facts = await key_question_facts(pool, assessment_id)
    resolved = resolve_policies(
        question_numbers=question_numbers,
        strictness_rules=strictness,
        word_count_rules=word_count,
        diagram_rules=diagrams,
        key_facts=facts,
    )
    rows = snapshot_for_storage(resolved)
    version = await persist_resolved(
        pool,
        assessment_id=assessment_id,
        resolved_rows=rows,
        rubric_snapshots=rubric_snapshots,
    )
    return await get_resolved(pool, assessment_id=assessment_id), version
