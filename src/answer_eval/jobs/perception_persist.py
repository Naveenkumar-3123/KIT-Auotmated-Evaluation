"""Persist perception artifacts (pages, spans, regions, OCR) for the evidence view.

The Processing-Details modal reads ``submission_pages``, ``question_spans``,
``question_regions`` and ``ocr_results`` — but nothing wrote to those tables.
This module uploads the on-disk page renders and region crops into object
storage (content-addressed by ``input_hash`` so re-runs never collide) and
writes the rows.

Best-effort by design: any failure is logged and swallowed so evidence
persistence can never break grading.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import asyncpg

from answer_eval.core.logging import get_logger
from answer_eval.storage import StorageProvider

logger = get_logger(__name__)

# DB check constraint allows ('answer_text','diagram','mixed','blank',
# 'margin_note'); the segmenter's RegionType adds 'unknown'.
_REGION_TYPE_DB = {
    "answer_text": "answer_text",
    "diagram": "diagram",
    "mixed": "mixed",
    "unknown": "blank",
}


def _read_image(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        p = Path(path)
        if p.is_file():
            return p.read_bytes()
    except OSError:
        return None
    return None


def _region_type(value: str | None) -> str:
    return _REGION_TYPE_DB.get(str(value or "").lower(), "answer_text")


async def _persist_pages(conn, submission_id: str, state: dict[str, Any], storage: StorageProvider) -> int:
    input_hash = str(state.get("input_hash") or "nohash")
    page_records = [p for p in (state.get("page_records") or []) if isinstance(p, dict)]
    count = 0
    for page in sorted(page_records, key=lambda p: int(p.get("page_number") or 0)):
        number = int(page.get("page_number") or 0)
        original_key = None
        preprocessed_key = None
        original_bytes = _read_image(page.get("original_image_path"))
        if original_bytes:
            original_key = storage.put(
                "pages",
                f"{submission_id}/{input_hash}/page-{number:02d}-original.png",
                original_bytes,
                content_type="image/png",
            )
        preprocessed_bytes = _read_image(page.get("preprocessed_image_path"))
        if preprocessed_bytes:
            preprocessed_key = storage.put(
                "pages",
                f"{submission_id}/{input_hash}/page-{number:02d}-preprocessed.png",
                preprocessed_bytes,
                content_type="image/png",
            )
        await conn.execute(
            """
            insert into submission_pages
                (submission_id, page_number, image_object_key,
                 original_object_key, width_px, height_px, quality_metrics)
            values ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            uuid.UUID(submission_id),
            number,
            preprocessed_key,
            original_key,
            int(page.get("width_px") or 0) or None,
            int(page.get("height_px") or 0) or None,
            page.get("quality_metrics") or {},
        )
        count += 1
    return count


async def _persist_spans(conn, submission_id: str, state: dict[str, Any]) -> dict[str, str]:
    span_ids: dict[str, str] = {}
    for span in state.get("question_spans") or []:
        if not isinstance(span, dict):
            continue
        qid = str(span.get("question_id") or "").strip()
        if not qid:
            continue
        span_id = await conn.fetchval(
            """
            insert into question_spans
                (submission_id, question_id, start_page, end_page,
                 region_ids, diagram_region_ids, mapping_uncertain,
                 uncertainty_reasons)
            values ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8::jsonb)
            returning id
            """,
            uuid.UUID(submission_id),
            qid,
            int(span.get("start_page") or 1),
            int(span.get("end_page") or 1),
            span.get("region_ids") or [],
            span.get("diagram_region_ids") or [],
            bool(span.get("mapping_uncertain", False)),
            span.get("uncertainty_reasons") or [],
        )
        span_ids[qid] = str(span_id)
    return span_ids
async def _persist_regions_and_ocr(
    conn,
    submission_id: str,
    state: dict[str, Any],
    storage: StorageProvider,
    span_ids: dict[str, str],
) -> tuple[int, int]:
    input_hash = str(state.get("input_hash") or "nohash")
    ocr_by_region: dict[str, dict[str, Any]] = {}
    for region_id, dump in state.get("ocr_records") or []:
        if isinstance(dump, dict):
            ocr_by_region[str(region_id)] = dump

    region_records = [
        r
        for r in (state.get("region_records") or [])
        if isinstance(r, dict) and r.get("region_id")
    ]
    region_records.sort(
        key=lambda r: (int(r.get("page_number") or 0), int(r.get("reading_order") or 0))
    )

    regions = 0
    ocrs = 0
    for region in region_records:
        region_id = str(region.get("region_id") or "")
        crop_key = None
        crop_bytes = _read_image(region.get("crop_image_path"))
        if crop_bytes:
            crop_key = storage.put(
                "crops",
                f"{submission_id}/{input_hash}/{region_id}.png",
                crop_bytes,
                content_type="image/png",
            )
        bbox = region.get("bbox") or {}
        qid = region.get("question_id")
        region_db_id = await conn.fetchval(
            """
            insert into question_regions
                (span_id, submission_id, page_number, bbox, region_type,
                 reading_order, crop_object_key, confidence)
            values ($1::uuid, $2::uuid, $3, $4::jsonb, $5, $6, $7, $8)
            returning id
            """,
            uuid.UUID(span_ids[qid]) if qid in span_ids else None,
            uuid.UUID(submission_id),
            int(region.get("page_number") or 1),
            {
                "x_min": bbox.get("x_min"),
                "y_min": bbox.get("y_min"),
                "x_max": bbox.get("x_max"),
                "y_max": bbox.get("y_max"),
            },
            _region_type(region.get("region_type")),
            int(region.get("reading_order") or 0),
            crop_key,
            float(region.get("classification_confidence") or 0),
        )
        regions += 1

        ocr = ocr_by_region.get(region_id)
        if not ocr or region_db_id is None:
            continue
        provenance = ocr.get("provenance") or {}
        await conn.execute(
            """
            insert into ocr_results
                (region_id, raw_text, lines, uncertain_spans, flags,
                 word_count, model_id, prompt_version, status)
            values ($1::uuid, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7, $8, $9)
            """,
            region_db_id,
            str(ocr.get("raw_text") or ""),
            ocr.get("lines") or [],
            ocr.get("uncertain_spans") or [],
            ocr.get("flags") or [],
            int(ocr.get("word_count") or 0),
            provenance.get("model_id"),
            provenance.get("prompt_version"),
            str(ocr.get("status") or "success"),
        )
        ocrs += 1
    return regions, ocrs


async def _persist(
    submission_id: str,
    state: dict[str, Any],
    storage: StorageProvider,
    pool: asyncpg.Pool,
) -> dict[str, int]:
    if not (state.get("page_records") or state.get("region_records")):
        return {"pages": 0, "spans": 0, "regions": 0, "ocr": 0}
    counts = {"pages": 0, "spans": 0, "regions": 0, "ocr": 0}
    async with pool.acquire() as conn, conn.transaction():
        # Idempotent re-runs: evidence is fully derived, so replace it.
        # ocr_results cascade-delete with their regions.
        await conn.execute(
            """
                delete from ocr_results where region_id in (
                    select id from question_regions where submission_id = $1::uuid
                )
                """,
            uuid.UUID(submission_id),
        )
        for table in ("question_regions", "question_spans", "submission_pages"):
            await conn.execute(
                f"delete from {table} where submission_id = $1::uuid",
                uuid.UUID(submission_id),
            )
        counts["pages"] = await _persist_pages(conn, submission_id, state, storage)
        span_ids = await _persist_spans(conn, submission_id, state)
        counts["spans"] = len(span_ids)
        counts["regions"], counts["ocr"] = await _persist_regions_and_ocr(
            conn, submission_id, state, storage, span_ids
        )
    return counts


def persist_perception(
    submission_id: str,
    state: dict[str, Any],
    storage: StorageProvider,
    run_coro,
    pool: asyncpg.Pool,
) -> dict[str, int] | None:
    """Persist evidence, best-effort; runs the coroutine on the caller's loop.

    ``run_coro`` must execute an awaitable to completion (the job store's
    ``run_coroutine_threadsafe`` bridge) because asyncpg pools are bound to the
    event loop that created them — the PostgresJobStore keeps its own loop.
    """
    try:
        counts = run_coro(
            asyncio.wait_for(_persist(submission_id, state, storage, pool), timeout=180)
        )
        logger.info(
            "Perception evidence persisted",
            submission_id=submission_id,
            pages=counts["pages"],
            spans=counts["spans"],
            regions=counts["regions"],
            ocr=counts["ocr"],
        )
        return counts
    except Exception:  # noqa: BLE001 - evidence must never break grading
        logger.warning("persist_perception failed", submission_id=submission_id, exc_info=True)
        return None

