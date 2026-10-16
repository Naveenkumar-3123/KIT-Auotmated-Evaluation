"""Region-header anchor harvesting (mapping robustness step 1).

Scanned answer sheets frequently yield ZERO left-margin anchors, which used to
degrade mapping to a positional guess. Students, however, almost always write
the question number again at the top of their answer block. This module OCRs
that header band per segmented region and turns hits into real anchors:

    region header "Q3"  ->  MarkerPosition(page=1, y=region top)
    QuestionSpan built directly from those markers (no margin needed)
    leftover regions/questions repaired in reading order - flagged, never silent

Every span produced here carries ``header_anchor_mapping`` uncertainty so the
teacher-review routing still applies: stronger than the sequential fallback
(real question numbers), weaker than flush-left margin anchors.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from answer_eval.core.logging import get_logger
from answer_eval.processing.image.schemas import PreprocessedPage
from answer_eval.processing.mapping.markers import detect_markers
from answer_eval.processing.mapping.schemas import (
    LineObservation,
    MarkerPosition,
    QuestionMappingResult,
    QuestionSpan,
    UnassignedContent,
)
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    PageSegmentationResult,
    QuestionRegion,
)

logger = get_logger("processing.mapping.header_anchors")

# Top fraction of a region's height treated as its header band.
DEFAULT_HEADER_RATIO = 0.18
# Answer blocks may be indented; the margin rule is relaxed accordingly.
REGION_HEADER_MARGIN_X = 0.35
# Header observations are pinned to a thin band at the region's top edge so
# ``assign_regions``' timeline (marker at-or-above a region's top edge) binds
# the region to its own anchor.
_PIN_BAND_HEIGHT = 0.005


def header_band_bbox(region_bbox: BoundingBox, *, header_ratio: float = DEFAULT_HEADER_RATIO) -> BoundingBox:
    """Normalized bbox of a region's top band."""
    band_height = (region_bbox.y_max - region_bbox.y_min) * header_ratio
    return BoundingBox(
        x_min=region_bbox.x_min,
        y_min=region_bbox.y_min,
        x_max=region_bbox.x_max,
        y_max=min(1.0, region_bbox.y_min + band_height),
    )


def extract_header_strip_png(
    image_path: str,
    destination: Path,
    *,
    region_bbox: BoundingBox,
    header_ratio: float = DEFAULT_HEADER_RATIO,
) -> Path:
    """Crop the region's header band from a page image as a PNG for OCR."""
    image = Image.open(str(image_path)).convert("RGB")
    width, height = image.size
    band = header_band_bbox(region_bbox, header_ratio=header_ratio)
    y0 = max(0, int(height * band.y_min))
    y1 = max(y0 + 8, min(height, int(height * band.y_max)))
    x0 = max(0, int(width * band.x_min))
    x1 = max(x0 + 8, min(width, int(width * band.x_max)))
    strip = image.crop((x0, y0, x1, y1))
    destination.parent.mkdir(parents=True, exist_ok=True)
    strip.save(destination, format="PNG")
    return destination
def build_header_observations(
    page_number: int,
    region: QuestionRegion,
    texts: list[str],
) -> list[LineObservation]:
    """Turn header OCR lines into LineObservations pinned at the region top."""
    y_top = region.bbox.y_min
    y_bottom = min(1.0, y_top + _PIN_BAND_HEIGHT)
    observations: list[LineObservation] = []
    for index, text in enumerate(texts):
        cleaned = text.strip()
        if not cleaned:
            continue
        observations.append(
            LineObservation(
                page_number=page_number,
                text=cleaned,
                bbox=BoundingBox(
                    x_min=region.bbox.x_min,
                    y_min=y_top,
                    x_max=region.bbox.x_max,
                    y_max=y_bottom,
                ),
                reading_order=index + 1,
            )
        )
    return observations


def harvest_header_markers(
    page_number: int,
    region: QuestionRegion,
    header_texts: list[str],
    valid_question_numbers: list[int],
) -> list[MarkerPosition]:
    """Parse question markers from a region's header OCR lines.

    Uses the shared marker-shape rules with a relaxed left-margin threshold
    (answer blocks are often indented). Markers outside the answer key are
    returned WITH their warning so callers can filter or flag - never drop
    evidence silently.
    """
    observations = build_header_observations(page_number, region, header_texts)
    if not observations:
        return []
    return detect_markers(
        {page_number: observations},
        valid_question_numbers,
        left_margin_x=REGION_HEADER_MARGIN_X,
    ).get(page_number, [])


def _answer_regions(regions: list[QuestionRegion]) -> list[QuestionRegion]:
    return sorted(
        (r for r in regions if r.region_type.value != "diagram"),
        key=lambda r: (r.page_number, r.reading_order),
    )


def _page_results(submission_id: str, regions: list[QuestionRegion]) -> list[PageSegmentationResult]:
    return [
        PageSegmentationResult(
            submission_id=submission_id,
            page_number=page,
            regions=[r for r in regions if r.page_number == page],
            source_page_hash="mapping-only",
        )
        for page in sorted({r.page_number for r in regions})
    ]


def repair_missing_tail(
    mapping: QuestionMappingResult,
    regions: list[QuestionRegion],
    missing_numbers: list[int],
) -> None:
    """Pair unanswered questions with trailing unnumbered regions.

    ``assign_regions`` attaches every headerless region after the last marker
    to that marker's question (continuation semantics). When questions are
    missing entirely, those trailing blocks are far more likely to BE the
    missing answers - re-claim the tail and pair it in reading order.

    GUARD: only applied when the trailing count plausibly matches the gap
    (``missing <= trailing <= 2 x missing``). A 16-mark answer streaming over
    4-5 pages produces many trailing continuation blocks; re-claiming those
    for a missing short question would shred the long answer. In that case
    continuation semantics are kept and the LLM semantic mapper (or the
    teacher) resolves the gap instead. The guess is always flagged.
    """
    if not missing_numbers:
        return
    last_marker = max(
        (marker for span in mapping.spans for marker in span.markers),
        key=lambda m: (m.page_number, m.y_center),
        default=None,
    )
    if last_marker is None:
        return

    def _after_last_marker(r: QuestionRegion) -> bool:
        return (r.page_number, r.bbox.y_min) > (last_marker.page_number, last_marker.y_center)

    trailing = [r for r in _answer_regions(regions) if _after_last_marker(r)]
    if len(trailing) < len(missing_numbers) or len(trailing) > 2 * len(missing_numbers):
        return  # keep continuation semantics - the tail does not explain the gap

    donors = trailing[-len(missing_numbers):]
    donor_ids = {r.region_id for r in donors}
    for span in mapping.spans:
        span.region_ids = [rid for rid in span.region_ids if rid not in donor_ids]

    for region, number in zip(donors, missing_numbers, strict=False):
        span = QuestionSpan(
            question_id=f"Q{number}",
            question_number=number,
            start_page=region.page_number,
            end_page=region.page_number,
        )
        span.region_ids.append(region.region_id)
        span.add_uncertainty("header_anchor_mapping")
        span.add_uncertainty("tail_assigned_in_reading_order")
        mapping.spans.append(span)

    extra = trailing[:-len(missing_numbers)] if len(trailing) > len(missing_numbers) else []
    if extra:
        mapping.unassigned = UnassignedContent(
            region_ids=[*mapping.unassigned.region_ids, *(r.region_id for r in extra)],
            reasons=[*(mapping.unassigned.reasons or []), "header_more_regions_than_questions"],
        )


def _safe_header_markers(
    page_region: QuestionRegion,
    texts: list[str],
    valid_question_numbers: list[int],
) -> list[MarkerPosition]:
    """harvest_header_markers guarded per-region: OCR noise ("0", gibberish)
    must never kill the whole mapping stage."""
    try:
        return harvest_header_markers(page_region.page_number, page_region, texts, valid_question_numbers)
    except Exception as exc:  # noqa: BLE001 - defense in depth
        logger.warning("header marker parse failed", region_id=page_region.region_id, error=str(exc))
        return []


def harvest_header_mapping(
    *,
    submission_id: str,
    page_records: list[Any],
    regions: list[QuestionRegion],
    valid_question_numbers: list[int],
    ocr_region: Callable[[QuestionRegion], Any],
    work_dir: Path,
    header_ratio: float = DEFAULT_HEADER_RATIO,
) -> QuestionMappingResult | None:
    """Build question spans from region-header anchors when margins yield none.

    ``ocr_region`` performs OCR on a temp region (the workflow node bridges the
    async OCRAgent). Returns ``None`` when too few anchors were found (<2, or
    <1 for single-question rubrics) so callers can use the sequential fallback.
    """
    if not valid_question_numbers or not regions:
        return None

    page_image: dict[int, str] = {}
    for dump in page_records:
        try:
            page = PreprocessedPage.model_validate(dump)
        except Exception:  # noqa: BLE001 - one bad page record must not abort mapping
            continue
        page_image[page.page_number] = page.preprocessed_image_path

    answer_regions = _answer_regions(regions)
    if not answer_regions:
        return None

    valid = set(valid_question_numbers)
    min_anchors = min(2, len(valid_question_numbers))
    kept_markers: list[MarkerPosition] = []
    seen: set[int] = set()

    for region in answer_regions:
        image_path = page_image.get(region.page_number)
        if image_path is None:
            continue
        try:
            strip_path = extract_header_strip_png(
                image_path,
                work_dir / f"header-{region.region_id}.png",
                region_bbox=region.bbox,
                header_ratio=header_ratio,
            )
            header_region = QuestionRegion(
                region_id=f"HEADER-{region.region_id}",
                page_number=region.page_number,
                submission_id=submission_id,
                bbox=header_band_bbox(region.bbox, header_ratio=header_ratio),
                crop_image_path=str(strip_path),
            )
            ocr = ocr_region(header_region)
            texts = [line for line in (ocr.lines or []) if line and str(line).strip()]
        except Exception as exc:  # noqa: BLE001 - one unreadable header must not kill the job
            logger.warning("header anchor OCR failed", region_id=region.region_id, error=str(exc))
            continue

        for marker in _safe_header_markers(region, texts, valid_question_numbers):
            if marker.question_number in valid and marker.question_number not in seen:
                seen.add(marker.question_number)
                kept_markers.append(marker)

    if len(seen) < min_anchors:
        return None

    spans: list[QuestionSpan] = []
    for marker in sorted(kept_markers, key=lambda m: (m.page_number, m.y_center)):
        span = QuestionSpan(
            question_id=f"Q{marker.question_number}",
            question_number=marker.question_number,
            start_page=marker.page_number,
            end_page=marker.page_number,
            markers=[marker],
        )
        span.add_uncertainty("header_anchor_mapping")
        spans.append(span)

    mapping = QuestionMappingResult(submission_id=submission_id, spans=spans, unassigned=UnassignedContent())
    from answer_eval.processing.mapping.mapper import assign_regions

    mapping = assign_regions(mapping, _page_results(submission_id, regions))

    covered = {span.question_number for span in mapping.spans}
    missing = [n for n in valid_question_numbers if n not in covered]
    if missing:
        repair_missing_tail(mapping, regions, missing)

    logger.info(
        "header anchor mapping applied",
        submission_id=submission_id,
        anchors=len(seen),
        spans=len(mapping.spans),
        tail_repaired=len(missing),
    )
    return mapping
