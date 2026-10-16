"""Developer Database Console Router for live PostgreSQL inspection and test data management."""

from __future__ import annotations

import logging
import os
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["console"])

ROOT_DIR = Path(__file__).resolve().parents[4]
VIEWER_HTML_PATH = ROOT_DIR / "viewer.html"

ALLOWED_CATEGORIES = {
    "answer_keys": "Answer Key & Questions",
    "questions": "Answer Key & Questions",
    "expected_concepts": "Answer Key & Questions",
    "keywords": "Answer Key & Questions",
    "mandatory_terms": "Answer Key & Questions",
    "answer_key_diagrams": "Answer Key & Questions",
    "diagram_requirements": "Answer Key & Questions",
    "question_policies": "Answer Key & Questions",
    "assessments": "Assessments & Submissions",
    "submissions": "Assessments & Submissions",
    "submission_pages": "Assessments & Submissions",
    "submission_files": "Assessments & Submissions",
    "assessment_students": "Assessments & Submissions",
    "assessment_submissions": "Assessments & Submissions",
    "evaluation_results": "Grading & Evaluation",
    "criterion_scores": "Grading & Evaluation",
    "student_totals": "Grading & Evaluation",
    "final_results": "Grading & Evaluation",
    "review_tasks": "Grading & Evaluation",
    "teacher_reviews": "Grading & Evaluation",
    "teacher_overrides": "Grading & Evaluation",
    "reconstructed_answers": "Grading & Evaluation",
    "risk_results": "Grading & Evaluation",
    "users": "Academic & Auth",
    "profiles": "Academic & Auth",
    "institutions": "Academic & Auth",
    "classes": "Academic & Auth",
    "subjects": "Academic & Auth",
    "teacher_classes": "Academic & Auth",
    "teacher_subjects": "Academic & Auth",
}

RESET_TABLES = [
    "answer_key_diagrams",
    "expected_concepts",
    "keywords",
    "mandatory_terms",
    "diagram_requirements",
    "questions",
    "question_policies",
    "answer_keys",
    "criterion_scores",
    "evaluation_results",
    "final_results",
    "review_tasks",
    "teacher_reviews",
    "teacher_overrides",
    "student_totals",
    "risk_results",
    "verification_comparisons",
    "verification_results",
    "reconstructed_answers",
    "question_regions",
    "question_spans",
    "student_diagrams",
    "ocr_results",
    "submission_files",
    "submission_pages",
    "assessment_submissions",
    "submissions",
    "assessment_students",
    "job_record_events",
    "job_records",
    "assessments",
]


def _format_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return f"<{len(value)} bytes binary>"
    return value


@router.get("/console/tables")
async def list_tables(request: Request) -> dict[str, Any]:
    """List all database tables with real live row counts."""
    db = request.app.state.database
    if db is None or getattr(db, "pool", None) is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
            """
        )
        tables_meta = []
        for r in rows:
            tname = r["table_name"]
            try:
                cnt = await conn.fetchval(f'SELECT count(*) FROM "{tname}"')
            except Exception:
                cnt = 0
            category = ALLOWED_CATEGORIES.get(tname, "Other Tables")
            tables_meta.append({"name": tname, "count": cnt, "category": category})

    return {"tables": tables_meta}


@router.get("/console/table/{table_name}")
async def get_table_data(
    table_name: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
) -> dict[str, Any]:
    """Retrieve column metadata and rows for a table."""
    db = request.app.state.database
    if db is None or getattr(db, "pool", None) is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    async with db.pool.acquire() as conn:
        # Validate table exists
        exists = await conn.fetchval(
            """
            SELECT count(*) FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = $1
            """,
            table_name,
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' does not exist")

        # Get column names
        cols_meta = await conn.fetch(
            """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
            """,
            table_name,
        )
        columns = [c["column_name"] for c in cols_meta]

        total_count = await conn.fetchval(f'SELECT count(*) FROM "{table_name}"')

        # Find best ordering column
        order_col = None
        for candidate in ["created_at", "updated_at", "question_number", "ordinal", "version", "id"]:
            if candidate in columns:
                order_col = candidate
                break

        order_clause = f'ORDER BY "{order_col}" DESC' if order_col else ""
        query = f'SELECT * FROM "{table_name}" {order_clause} LIMIT {limit} OFFSET {offset}'
        raw_rows = await conn.fetch(query)

        rows = []
        for r in raw_rows:
            row_dict = {col: _format_cell(r[col]) for col in columns}
            rows.append(row_dict)

    return {
        "table": table_name,
        "total_count": total_count,
        "columns": columns,
        "rows": rows,
        "limit": limit,
        "offset": offset,
    }


@router.post("/console/reset-test-data")
async def reset_test_data(request: Request) -> dict[str, Any]:
    """Wipe uploaded test assessments, answer keys, and submissions, preserving auth/users."""
    db = request.app.state.database
    if db is None or getattr(db, "pool", None) is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    async with db.pool.acquire() as conn:
        truncate_query = f"TRUNCATE TABLE {', '.join(RESET_TABLES)} CASCADE;"
        await conn.execute(truncate_query)

    # Clean local storage folders
    storage_dirs = [
        ROOT_DIR / "data" / "storage" / "answer-keys",
        ROOT_DIR / "data" / "storage" / "key-diagrams",
        ROOT_DIR / "data" / "storage" / "original-pdfs",
        ROOT_DIR / "data" / "rendered_pages",
        ROOT_DIR / "data" / "preprocessed_pages",
        ROOT_DIR / "data" / "region_crops",
    ]
    for d in storage_dirs:
        if d.exists():
            for item in d.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    try:
                        item.unlink()
                    except Exception:
                        pass

    return {
        "status": "success",
        "message": "All uploaded test answer keys and student papers successfully erased.",
    }


@router.get("/viewer", response_class=HTMLResponse)
async def serve_viewer() -> HTMLResponse:
    """Serve the interactive database viewer console."""
    if VIEWER_HTML_PATH.exists():
        content = VIEWER_HTML_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content)
    return HTMLResponse("<h1>viewer.html not found</h1>", status_code=404)
