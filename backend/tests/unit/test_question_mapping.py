"""Milestone 7 unit tests: QuestionSpanMapper + cross-page mapping (spec #93)."""

from __future__ import annotations

from answer_eval.processing.mapping import (
    LineObservation,
    QuestionSpanMapper,
    assign_regions,
    make_line,
    parse_marker_text,
)
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    PageSegmentationResult,
    QuestionRegion,
    RegionType,
)

VALID = list(range(1, 13))  # Q1..Q12


def lines(pages: dict[int, list[tuple[str, float, float]]]) -> dict[int, list[LineObservation]]:
    """pages: page -> [(text, x_min, y_min), ...] in reading order."""
    return {
        page: [make_line(page, text, x_min=x, y_min=y, order=i + 1) for i, (text, x, y) in enumerate(items)]
        for page, items in pages.items()
    }


def region(page: int, index: int, y_min: float, rtype: RegionType = RegionType.ANSWER_TEXT) -> QuestionRegion:
    return QuestionRegion(
        region_id=f"REG-P{page:02d}-{index:02d}",
        page_number=page,
        submission_id="SUB-1",
        bbox=BoundingBox(x_min=0.0, y_min=y_min, x_max=1.0, y_max=y_min + 0.2),
        region_type=rtype,
        reading_order=index,
    )


def segmentation(pages: dict[int, list[QuestionRegion]]) -> list[PageSegmentationResult]:
    return [
        PageSegmentationResult(
            submission_id="SUB-1",
            page_number=page,
            regions=regions,
            source_page_hash=f"hash-{page}",
        )
        for page, regions in sorted(pages.items())
    ]


# ---------------------------------------------------------------------------
# Marker parsing
# ---------------------------------------------------------------------------


def test_marker_shapes() -> None:
    for text, number in [("1", 1), ("1.", 1), ("Q1", 1), ("Q.1", 1), ("11", 11), ("12(a)", 12)]:
        parsed = parse_marker_text(text)
        assert parsed is not None and parsed[0] == number, text


def test_body_text_is_not_a_marker() -> None:
    # A bare number directly followed by several words is body text:
    assert parse_marker_text("11 The process of retransmission") is None
    assert parse_marker_text("The receiver sends an acknowledgement") is None


def test_zero_is_never_a_marker() -> None:
    # OCR noise (smudges, page borders) transcribes as "0"/"00"; MarkerPosition
    # requires >= 1, so the lexical layer must reject it before construction.
    assert parse_marker_text("0") is None
    assert parse_marker_text("00") is None
    assert parse_marker_text("Q0") is None
    assert parse_marker_text("0.") is None


# ---------------------------------------------------------------------------
# Mapping scenarios (spec #93)
# ---------------------------------------------------------------------------


def test_one_question_one_page() -> None:
    result = QuestionSpanMapper().map(
        lines({1: [("1", 0.03, 0.10), ("answer text about OSI model", 0.08, 0.20)]}),
        VALID,
    )
    assert [s.question_id for s in result.spans] == ["Q1"]
    span = result.spans[0]
    assert (span.start_page, span.end_page) == (1, 1)
    assert not span.mapping_uncertain


def test_one_question_five_pages_continuation() -> None:
    result = QuestionSpanMapper().map(
        lines(
            {
                1: [("11", 0.02, 0.05), ("start of long answer", 0.06, 0.30)],
                2: [("continues without a marker", 0.06, 0.15)],
                3: [("still continuing", 0.06, 0.15)],
                4: [("more content", 0.06, 0.15)],
                5: [("12", 0.02, 0.40), ("final part", 0.06, 0.60)],
            }
        ),
        VALID,
    )
    assert [(s.question_id, s.start_page, s.end_page) for s in result.spans] == [
        ("Q11", 1, 4),
        ("Q12", 5, 5),
    ]
    assert not result.spans[0].mapping_uncertain


def test_two_questions_share_one_page() -> None:
    """Question ends halfway down; next begins on the same page."""
    result = QuestionSpanMapper().map(
        lines({1: [("3", 0.02, 0.05), ("part one", 0.06, 0.20), ("4", 0.02, 0.55), ("part two", 0.06, 0.70)]}),
        VALID,
    )
    assert [s.question_id for s in result.spans] == ["Q3", "Q4"]
    assert all(not s.mapping_uncertain for s in result.spans)


def test_diagram_between_paragraphs_assigned_to_enclosing_question() -> None:
    mapping = QuestionSpanMapper().map(
        lines({1: [("5", 0.02, 0.10), ("text before diagram", 0.06, 0.25), ("text after diagram", 0.06, 0.75)]}),
        VALID,
    )
    mapped = assign_regions(
        mapping,
        segmentation(
            {
                1: [
                    region(1, 1, 0.18),
                    region(1, 2, 0.45, RegionType.DIAGRAM),
                    region(1, 3, 0.70),
                ]
            }
        ),
    )
    q5 = next(s for s in mapped.spans if s.question_id == "Q5")
    assert q5.region_ids == ["REG-P01-01", "REG-P01-03"]
    assert q5.diagram_region_ids == ["REG-P01-02"]
    assert not q5.mapping_uncertain


def test_no_marker_on_first_page_flags_uncertainty() -> None:
    result = QuestionSpanMapper().map(
        lines(
            {
                1: [("orphan continuation text", 0.06, 0.10)],
                2: [("2", 0.02, 0.30), ("answer", 0.06, 0.50)],
            }
        ),
        VALID,
    )
    assert [s.question_id for s in result.spans] == ["Q2"]
    assert "content_before_first_marker" in result.spans[0].uncertainty_reasons


def test_unknown_question_number_flagged_not_silently_dropped() -> None:
    result = QuestionSpanMapper().map(
        lines({1: [("31", 0.02, 0.05), ("content", 0.06, 0.20)], 2: [("35", 0.02, 0.10)]}),
        [*VALID, 35],
    )
    first = result.spans[0]
    assert first.question_number == 31
    assert "unknown_question_number" in first.uncertainty_reasons
    # A later valid anchor opens its own clean span — uncertainty does not leak.
    second = result.spans[1]
    assert second.question_number == 35
    assert "unknown_question_number" not in second.uncertainty_reasons


def test_out_of_order_marker_flagged() -> None:
    result = QuestionSpanMapper().map(
        lines(
            {
                1: [("7", 0.02, 0.05)],
                2: [("4", 0.02, 0.10), ("possibly misread anchor", 0.06, 0.30)],
            }
        ),
        VALID,
    )
    assert [s.question_number for s in result.spans] == [7, 4]
    assert "out_of_order_marker" in result.spans[1].uncertainty_reasons


def test_body_number_ignored_only_margin_counts() -> None:
    result = QuestionSpanMapper().map(
        lines({1: [("9", 0.45, 0.05), ("9 marks were awarded here", 0.10, 0.30), ("actual body", 0.06, 0.50)]}),
        VALID,
    )
    # "9" mid-page is not at the far-left margin -> no confident anchor.
    assert result.spans == []


def test_region_assignment_across_page_boundary() -> None:
    mapping = QuestionSpanMapper().map(
        lines(
            {
                1: [("11", 0.02, 0.08)],
                2: [("no marker continuation", 0.06, 0.10)],
                3: [("12", 0.02, 0.35)],
            }
        ),
        VALID,
    )
    mapped = assign_regions(
        mapping,
        segmentation(
            {
                1: [region(1, 1, 0.20)],
                2: [region(2, 1, 0.30)],
                3: [region(3, 1, 0.15), region(3, 2, 0.50)],
            }
        ),
    )
    q11 = next(s for s in mapped.spans if s.question_id == "Q11")
    q12 = next(s for s in mapped.spans if s.question_id == "Q12")
    # Page-2 region continues Q11 even though page 2 has no marker.
    assert q11.region_ids[:2] == ["REG-P01-01", "REG-P02-01"]
    # Page 3: region above the Q12 marker belongs to Q11; below belongs to Q12.
    assert "REG-P03-01" in q11.region_ids
    assert q12.region_ids == ["REG-P03-02"]


def test_region_before_first_marker_is_unassigned() -> None:
    mapping = QuestionSpanMapper().map(lines({1: [("1", 0.02, 0.50)]}), VALID)
    mapped = assign_regions(mapping, segmentation({1: [region(1, 1, 0.05), region(1, 2, 0.70)]}))
    assert mapped.unassigned.region_ids == ["REG-P01-01"]
    assert mapped.spans[0].region_ids == ["REG-P01-02"]



