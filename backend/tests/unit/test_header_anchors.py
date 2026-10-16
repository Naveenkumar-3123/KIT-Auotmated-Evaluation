"""Unit tests: region-header anchor harvesting (mapping robustness step 1)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from answer_eval.processing.image.schemas import ImageQualityMetrics, PreprocessedPage
from answer_eval.processing.mapping.header_anchors import (
    build_header_observations,
    extract_header_strip_png,
    harvest_header_mapping,
    harvest_header_markers,
    header_band_bbox,
)
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    QuestionRegion,
    RegionType,
)

VALID = list(range(1, 7))  # Q1..Q6


def make_page(path: Path, page_number: int = 1) -> dict:
    image = Image.new("RGB", (1000, 2000), "white")
    image.save(path)
    return PreprocessedPage(
        submission_id="SUB-H",
        page_number=page_number,
        original_image_path=str(path),
        original_page_hash=f"h-orig-{page_number}",
        preprocessed_image_path=str(path),
        preprocessed_page_hash=f"h-pre-{page_number}",
        width_px=1000,
        height_px=2000,
        quality_metrics=ImageQualityMetrics(blur_score=250.0, brightness_score=220.0, contrast_score=70.0),
    ).model_dump()


def region(index: int, y_min: float, y_max: float, page: int = 1) -> QuestionRegion:
    return QuestionRegion(
        region_id=f"REG-P{page:02d}-{index:02d}",
        page_number=page,
        submission_id="SUB-H",
        bbox=BoundingBox(x_min=0.2, y_min=y_min, x_max=1.0, y_max=y_max),
        region_type=RegionType.ANSWER_TEXT,
        reading_order=index,
    )


# ---------------------------------------------------------------------------
# Header band + observations
# ---------------------------------------------------------------------------


def test_header_band_bbox_is_top_fraction_of_region() -> None:
    bbox = BoundingBox(x_min=0.2, y_min=0.1, x_max=1.0, y_max=0.5)
    band = header_band_bbox(bbox)
    assert band.y_min == 0.1
    assert abs(band.y_max - (0.1 + 0.4 * 0.18)) < 1e-6
    assert (band.x_min, band.x_max) == (0.2, 1.0)


def test_build_header_observations_pinned_at_region_top() -> None:
    reg = region(1, 0.30, 0.70)
    observations = build_header_observations(1, reg, ["Q3", "explain the process"])
    assert [o.text for o in observations] == ["Q3", "explain the process"]
    for obs in observations:
        assert obs.bbox.y_min == 0.30
        # Pinned band keeps the marker at-or-above the region's top edge so
        # assign_regions' timeline binds the region to its own anchor.
        assert (obs.bbox.y_min + obs.bbox.y_max) / 2 <= 0.30 + 0.01
        assert obs.bbox.x_min == 0.2 and obs.bbox.x_max == 1.0


def test_extract_header_strip_png_crops_region_band(tmp_path) -> None:
    page_path = tmp_path / "page.png"
    image = Image.new("RGB", (1000, 2000), "white")
    ImageDraw.Draw(image).rectangle([400, 210, 700, 218], fill="black")  # ink in band
    image.save(page_path)

    reg = region(1, 0.10, 0.50)  # band = y 0.10..0.172 -> px 200..344
    strip = extract_header_strip_png(str(page_path), tmp_path / "strip.png", region_bbox=reg.bbox)
    with Image.open(strip) as cropped:
        assert cropped.size == (800, 144)


# ---------------------------------------------------------------------------
# Full harvest mapping
# ---------------------------------------------------------------------------


class _FakeOcr:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines


def _fake_ocr_factory(responses: list[list[str]]):
    queue = list(responses)

    def _ocr(_region: QuestionRegion) -> _FakeOcr:
        return _FakeOcr(queue.pop(0) if queue else [])

    return _ocr


def test_harvest_header_mapping_builds_spans_and_repairs_tail(tmp_path) -> None:
    page = make_page(tmp_path / "page.png")
    regions = [region(1, 0.05, 0.40), region(2, 0.45, 0.75), region(3, 0.80, 1.0)]
    # Q5 header missing (student forgot the number) -> tail repair pairs the
    # third region with the only unanswered question, flagged for review.
    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[page],
        regions=regions,
        valid_question_numbers=[3, 4, 5],
        ocr_region=_fake_ocr_factory([["Q3"], ["Q4"], ["some body text"]]),
        work_dir=tmp_path,
    )
    assert harvested is not None
    assert [(s.question_id, s.region_ids) for s in harvested.spans] == [
        ("Q3", ["REG-P01-01"]),
        ("Q4", ["REG-P01-02"]),
        ("Q5", ["REG-P01-03"]),
    ]
    for span in harvested.spans:
        assert span.mapping_uncertain
        assert "header_anchor_mapping" in span.uncertainty_reasons
    tail = harvested.spans[-1]
    assert "tail_assigned_in_reading_order" in tail.uncertainty_reasons
    assert harvested.unassigned.region_ids == []


def test_harvest_header_mapping_requires_two_anchors(tmp_path) -> None:
    page = make_page(tmp_path / "page.png")
    regions = [region(1, 0.05, 0.40), region(2, 0.45, 0.75)]
    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[page],
        regions=regions,
        valid_question_numbers=[3, 4],
        ocr_region=_fake_ocr_factory([["Q3"], []]),
        work_dir=tmp_path,
    )
    assert harvested is None  # a single header anchor is too weak to trust


def test_harvest_header_mapping_headerless_tail_continues_previous_question(tmp_path) -> None:
    page = make_page(tmp_path / "page.png")
    regions = [region(1, 0.05, 0.40), region(2, 0.45, 0.75), region(3, 0.80, 1.0)]
    # All questions have spans, so the unnumbered trailing block keeps
    # continuation semantics (part of Q4's answer split across blocks).
    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[page],
        regions=regions,
        valid_question_numbers=[3, 4],
        ocr_region=_fake_ocr_factory([["Q3"], ["Q4"], []]),
        work_dir=tmp_path,
    )
    assert harvested is not None
    assert [(s.question_id, s.region_ids) for s in harvested.spans] == [
        ("Q3", ["REG-P01-01"]),
        ("Q4", ["REG-P01-02", "REG-P01-03"]),
    ]
    assert harvested.unassigned.region_ids == []


def test_harvest_header_mapping_tail_repair_requires_enough_trailing_blocks(tmp_path) -> None:
    page = make_page(tmp_path / "page.png")
    regions = [region(1, 0.05, 0.40), region(2, 0.45, 0.75)]
    # Two missing questions but only one trailing block: the gap cannot be
    # explained by re-assignment, so continuation semantics are kept.
    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[page],
        regions=regions,
        valid_question_numbers=[3, 4, 5],
        ocr_region=_fake_ocr_factory([["Q3"], []]),
        work_dir=tmp_path,
    )
    assert harvested is None  # single anchor below the two-anchor threshold anyway


def test_harvest_header_mapping_empty_when_no_headers(tmp_path) -> None:
    page = make_page(tmp_path / "page.png")
    regions = [region(1, 0.05, 0.40)]
    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[page],
        regions=regions,
        valid_question_numbers=[3],
        ocr_region=_fake_ocr_factory([["just an answer"]]),
        work_dir=tmp_path,
    )
    assert harvested is None


def test_harvest_header_mapping_survives_ocr_failures(tmp_path) -> None:
    page = make_page(tmp_path / "page.png")
    regions = [region(1, 0.05, 0.40), region(2, 0.45, 0.75)]

    def _boom(_region: QuestionRegion) -> _FakeOcr:
        raise RuntimeError("inference offline")

    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[page],
        regions=regions,
        valid_question_numbers=[3, 4],
        ocr_region=_boom,
        work_dir=tmp_path,
    )
    assert harvested is None


def test_harvest_header_mapping_across_pages(tmp_path) -> None:
    p1 = make_page(tmp_path / "p1.png", page_number=1)
    p2 = make_page(tmp_path / "p2.png", page_number=2)
    regions = [region(1, 0.05, 0.40, page=1), region(1, 0.05, 0.40, page=2)]
    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[p1, p2],
        regions=regions,
        valid_question_numbers=[3, 4],
        ocr_region=_fake_ocr_factory([["Q3"], ["Q4"]]),
        work_dir=tmp_path,
    )
    assert harvested is not None
    assert [(s.question_id, s.start_page) for s in harvested.spans] == [("Q3", 1), ("Q4", 2)]
    assert harvested.spans[0].region_ids == ["REG-P01-01"]
    assert harvested.spans[1].region_ids == ["REG-P02-01"]


# ---------------------------------------------------------------------------
# Marker harvesting
# ---------------------------------------------------------------------------


def test_harvest_header_markers_parses_number() -> None:
    reg = region(1, 0.30, 0.70)
    markers = harvest_header_markers(1, reg, ["Q3"], VALID)
    assert len(markers) == 1
    assert markers[0].question_number == 3
    assert markers[0].page_number == 1
    assert markers[0].y_center <= 0.30 + 0.01


def test_harvest_header_markers_flags_number_outside_answer_key() -> None:
    reg = region(1, 0.30, 0.70)
    markers = harvest_header_markers(1, reg, ["Q9"], VALID)
    assert len(markers) == 1
    assert "question_number_not_in_answer_key" in markers[0].warnings


def test_harvest_header_markers_ignores_body_text() -> None:
    reg = region(1, 0.30, 0.70)
    markers = harvest_header_markers(1, reg, ["The process of retransmission"], VALID)
    assert markers == []


def test_repair_declines_when_trailing_blocks_outnumber_the_gap(tmp_path) -> None:
    # 16-mark-answer scenario: Q3 and Q4 anchored, three headerless trailing
    # continuation blocks, only Q5 missing. 3 trailing > 2 x 1 -> the tail does
    # NOT explain the gap; continuation must be kept (no shredding of Q4).
    page = make_page(tmp_path / "page.png")
    regions = [
        region(1, 0.05, 0.40),
        region(2, 0.45, 0.60),
        region(3, 0.65, 0.75),
        region(4, 0.80, 0.90),
        region(5, 0.92, 1.0),
    ]
    harvested = harvest_header_mapping(
        submission_id="SUB-H",
        page_records=[page],
        regions=regions,
        valid_question_numbers=[3, 4, 5],
        ocr_region=_fake_ocr_factory([["Q3"], ["Q4"], [], [], []]),
        work_dir=tmp_path,
    )
    assert harvested is not None
    by_id = {s.question_id: s for s in harvested.spans}
    assert set(by_id) == {"Q3", "Q4"}  # no Q5 span was invented
    # Trailing blocks keep continuation semantics with Q4.
    assert by_id["Q4"].region_ids == ["REG-P01-02", "REG-P01-03", "REG-P01-04", "REG-P01-05"]
    assert harvested.unassigned.region_ids == []

