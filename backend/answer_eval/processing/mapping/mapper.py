"""QuestionSpanMapper: cross-page question mapping (Milestone 7, specs #30-33).

Deterministic walk over pages in reading order:

    Q11 marker found on page 1  -> all following content belongs to Q11
    page 2 has no new marker    -> continue Q11
    page 5 marker for Q12       -> close Q11, begin Q12

A question may span ANY number of pages. When mapping is ambiguous the mapper
never silently assigns content: it sets ``mapping_uncertain`` with reasons so
the pipeline can route the question to teacher verification.
"""

from __future__ import annotations

import re

from answer_eval.core.logging import get_logger
from answer_eval.processing.mapping.markers import detect_markers
from answer_eval.processing.mapping.schemas import (
    LineObservation,
    MarkerPosition,
    QuestionMappingResult,
    QuestionSpan,
    UnassignedContent,
)
from answer_eval.processing.segmentation.schemas import PageSegmentationResult

logger = get_logger("processing.mapping")

# Vertical tolerance when comparing a region's top edge against a marker line.
_Y_EPSILON = 0.01


class QuestionSpanMapper:
    """Maps OCR/layout line observations to cross-page question spans."""

    def map(
        self,
        lines_by_page: dict[int, list[LineObservation]],
        valid_question_numbers: list[int],
        *,
        submission_id: str = "",
    ) -> QuestionMappingResult:
        markers_by_page = detect_markers(lines_by_page, valid_question_numbers)
        valid = set(valid_question_numbers)

        spans: list[QuestionSpan] = []
        current: QuestionSpan | None = None
        seen_numbers: set[int] = set()
        first_page = min(lines_by_page) if lines_by_page else 1
        preamble_uncertain = False

        def _open(marker: MarkerPosition, page_number: int) -> QuestionSpan:
            return QuestionSpan(
                question_id=f"Q{marker.question_number}",
                question_number=marker.question_number,
                start_page=page_number,
                end_page=page_number,
            )

        for page_number in sorted(lines_by_page):
            page_markers = markers_by_page.get(page_number, [])
            if not page_markers:
                # Continuation page: content keeps belonging to the open span.
                if current is not None:
                    current.end_page = max(current.end_page, page_number)
                elif not spans and page_number >= first_page and any(lines_by_page[page_number]):
                    preamble_uncertain = True
                continue

            for marker in page_markers:
                known = marker.question_number in valid
                duplicate = marker.question_number in seen_numbers
                out_of_order = current is not None and marker.question_number < current.question_number

                if current is None:
                    current = _open(marker, page_number)
                    if preamble_uncertain:
                        current.add_uncertainty("content_before_first_marker")
                        preamble_uncertain = False
                elif duplicate and not out_of_order and marker.question_number == current.question_number:
                    # Same anchor repeated (e.g. margin note); keep content in
                    # the open span but record the ambiguity.
                    current.add_uncertainty(f"duplicate_marker_q{marker.question_number}")
                    current.markers.append(marker)
                    continue
                else:
                    spans.append(current)
                    current = _open(marker, page_number)
                    if out_of_order:
                        current.add_uncertainty("out_of_order_marker")
                    if duplicate:
                        current.add_uncertainty(f"duplicate_marker_q{marker.question_number}")

                if not known:
                    current.add_uncertainty("unknown_question_number")
                for warning in marker.warnings:
                    current.add_uncertainty(warning)
                current.markers.append(marker)
                seen_numbers.add(marker.question_number)

        if current is not None:
            spans.append(current)

        result = QuestionMappingResult(
            submission_id=submission_id,
            spans=spans,
            unassigned=UnassignedContent(),
        )
        logger.info(
            "question mapping complete",
            submission_id=submission_id,
            spans=len(result.spans),
            uncertain=sum(1 for s in result.spans if s.mapping_uncertain),
        )
        return result


def assign_regions(
    mapping: QuestionMappingResult,
    page_results: list[PageSegmentationResult],
) -> QuestionMappingResult:
    """Assign segmented regions to spans using marker positions (spec #30).

    A region belongs to the last marker at-or-above its top edge on its page;
    a page without markers continues the previously opened question. Regions
    above the FIRST marker of the paper cannot be attributed confidently and
    land in ``unassigned`` instead of being silently attached.
    """
    span_by_number = {span.question_number: span for span in mapping.spans}

    timeline: list[tuple[int, float, int, QuestionSpan]] = []
    for span in mapping.spans:
        for marker in span.markers:
            timeline.append((marker.page_number, marker.y_center, marker.question_number, span))
    timeline.sort(key=lambda item: (item[0], item[1]))

    def _span_for(page_number: int, y_top: float) -> QuestionSpan | None:
        on_page = [(y, s) for p, y, _q, s in timeline if p == page_number]
        below_or_at = [ys for ys in on_page if ys[0] <= y_top + _Y_EPSILON]
        if below_or_at:
            return below_or_at[-1][1]
        earlier = [s for p, _y, _q, s in timeline if p < page_number]
        if earlier:
            return earlier[-1]
        return None

    unassigned_regions: list[str] = []
    for page_result in sorted(page_results, key=lambda pr: pr.page_number):
        for region in sorted(page_result.regions, key=lambda r: r.reading_order):
            span = _span_for(page_result.page_number, region.bbox.y_min)
            if span is None:
                unassigned_regions.append(region.region_id)
                continue
            bucket = span.diagram_region_ids if region.region_type.value == "diagram" else span.region_ids
            if region.region_id not in bucket:
                bucket.append(region.region_id)

    mapping.unassigned = UnassignedContent(
        region_ids=unassigned_regions,
        reasons=["before_first_marker"] if unassigned_regions else [],
    )
    return mapping

