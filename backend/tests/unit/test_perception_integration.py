"""Milestone 8 unit tests: perception pipeline integration + question packets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from answer_eval.agents.reconstruction.packets import build_question_packets
from answer_eval.core.provenance import Provenance
from answer_eval.inference.types import InferenceResponse, InferenceTiming, TokenUsage
from answer_eval.processing.image.schemas import ImageQualityMetrics, PreprocessedPage
from answer_eval.processing.mapping.margin_scan import (
    build_line_observations,
    detect_anchor_boxes,
)
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    QuestionRegion,
    RegionType,
)
from answer_eval.storage import LocalStorageProvider
from answer_eval.workflow import nodes
from tests.conftest import MockInferenceProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def draw_anchor_page(path: Path, anchors: list[int]) -> None:
    """White page 1000x2000 with one black anchor blob (left band) per y."""
    image = Image.new("RGB", (1000, 2000), "white")
    draw = ImageDraw.Draw(image)
    for y in anchors:
        draw.rectangle([20, y, 130, y + 60], fill="black")
    image.save(path)


def page_record(page_number: int, image_path: Path) -> dict:
    return PreprocessedPage(
        submission_id="SUB-M",
        page_number=page_number,
        original_image_path=str(image_path),
        original_page_hash=f"h-orig-{page_number}",
        preprocessed_image_path=str(image_path),
        preprocessed_page_hash=f"h-pre-{page_number}",
        width_px=1000,
        height_px=2000,
        quality_metrics=ImageQualityMetrics(blur_score=250.0, brightness_score=220.0, contrast_score=70.0),
    ).model_dump()


class ScriptedTextProvider(MockInferenceProvider):
    """Returns queued plain texts for strip OCR calls (JSON-encoded)."""

    def __init__(self, responses: list[str]) -> None:
        super().__init__()
        self._responses = list(responses)

    async def infer(self, request):  # type: ignore[override]
        text = self._responses.pop(0) if self._responses else ""
        payload = f'{{"raw_text": "{text}", "lines": ["{text}"], "uncertain_spans": [], "flags": []}}'
        return InferenceResponse(
            request_id=request.request_id,
            provider="mock",
            model_id="mock_4b",
            text=payload,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            timing=InferenceTiming(total_inference_ms=50.0),
        )


# ---------------------------------------------------------------------------
# Margin scanner
# ---------------------------------------------------------------------------


def test_margin_scan_detects_anchor_rows(tmp_path) -> None:
    page = tmp_path / "p1.png"
    draw_anchor_page(page, [300, 1400])
    boxes = detect_anchor_boxes(str(page))
    assert len(boxes) == 2
    assert boxes[0][0] < boxes[1][0]  # top-down order
    assert 0.10 < boxes[0][0] < 0.22
    assert 0.65 < boxes[1][0] < 0.75


def test_margin_scan_ignores_full_height_margin_rule(tmp_path) -> None:
    """A full-height vertical rule in the left band must not fuse all anchors.

    Scanned sheets have a printed margin line spanning every row; without
    removing it, ``detect_anchor_boxes`` collapses the whole band into one
    giant box and the mapper finds no question markers at all.
    """
    image = Image.new("RGB", (1000, 2000), "white")
    draw = ImageDraw.Draw(image)
    # Two anchor blobs in the left band.
    for y in (300, 1400):
        draw.rectangle([20, y, 130, y + 60], fill="black")
    # Full-height vertical rule just right of the anchors.
    draw.rectangle([150, 0, 152, 2000], fill="black")
    page = tmp_path / "rule.png"
    image.save(page)

    boxes = detect_anchor_boxes(str(page))
    assert len(boxes) == 2, f"expected 2 anchors, got {len(boxes)}: {boxes}"
    assert 0.10 < boxes[0][0] < 0.22
    assert 0.65 < boxes[1][0] < 0.75


def test_build_line_observations_aligns_texts_by_count(tmp_path) -> None:
    page = tmp_path / "p1.png"
    draw_anchor_page(page, [300, 1400])
    observations = build_line_observations(1, str(page), texts=["11", "12"])
    assert [o.text for o in observations] == ["11", "12"]
    assert all(o.bbox.x_max <= 0.16 for o in observations)


def test_build_line_observations_mismatch_keeps_empty(tmp_path) -> None:
    page = tmp_path / "p1.png"
    draw_anchor_page(page, [300, 1400])
    observations = build_line_observations(1, str(page), texts=["a", "b", "c"])
    assert all(o.text == "" for o in observations)


# ---------------------------------------------------------------------------
# map_questions workflow node
# ---------------------------------------------------------------------------


def _base_state(tmp_path: Path) -> dict:
    p1 = tmp_path / "page1.png"
    p2 = tmp_path / "page2.png"
    draw_anchor_page(p1, [300])  # anchor -> Q11
    draw_anchor_page(p2, [400])  # anchor -> Q12

    regions = [
        QuestionRegion(
            region_id="REG-P01-01",
            page_number=1,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.50, x_max=1.0, y_max=0.9),
            reading_order=1,
        ),
        QuestionRegion(
            region_id="REG-P02-01",
            page_number=2,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.60, x_max=1.0, y_max=0.95),
            reading_order=1,
        ),
    ]
    return {
        "submission_id": "SUB-M",
        "rubrics": {"Q11": {"question_id": "Q11"}, "Q12": {"question_id": "Q12"}},
        "page_records": [page_record(1, p1), page_record(2, p2)],
        "region_records": [r.model_dump() for r in regions],
    }


def test_map_questions_assigns_cross_page_spans(tmp_path) -> None:
    provider = ScriptedTextProvider(["11", "12"])
    updates = nodes.map_questions(_base_state(tmp_path), provider)

    spans = {span["question_id"]: span for span in updates["question_spans"]}
    assert set(spans) == {"Q11", "Q12"}
    assert (spans["Q11"]["start_page"], spans["Q11"]["end_page"]) == (1, 1)
    assert (spans["Q12"]["start_page"], spans["Q12"]["end_page"]) == (2, 2)

    by_rid = {r["region_id"]: r for r in updates["region_records"]}
    assert by_rid["REG-P01-01"]["question_id"] == "Q11"
    assert by_rid["REG-P02-01"]["question_id"] == "Q12"


def test_map_questions_is_idempotent(tmp_path) -> None:
    state = _base_state(tmp_path)
    state["question_spans"] = [{"question_id": "Q99"}]
    updates = nodes.map_questions(state, ScriptedTextProvider([]))
    assert updates.get("region_records") is None


def test_mapper_skips_without_page_records() -> None:
    updates = nodes.map_questions({"region_records": []}, ScriptedTextProvider([]))
    assert updates == {"current_stage": "mapping_questions"}


# ---------------------------------------------------------------------------
# Reconstruction grouping fix
# ---------------------------------------------------------------------------


def ocr_record(region_id: str) -> dict:
    from answer_eval.agents.ocr.schemas import OCRResult

    provenance = Provenance(
        submission_id="SUB-R",
        page_number=1,
        region_id=region_id,
        question_id=None,
        source_image_hash="hash-x",
        request_id=f"req-{region_id}",
        model_id="mock",
    )
    return OCRResult(raw_text="some handwriting text here", lines=["one"], word_count=4, provenance=provenance).model_dump()


def test_reconstruct_groups_by_mapped_question() -> None:
    r11 = QuestionRegion(
        region_id="REG-P01-01",
        page_number=1,
        submission_id="SUB-R",
        bbox=BoundingBox(x_min=0.0, y_min=0.1, x_max=1.0, y_max=0.5),
    ).model_dump()
    r12 = QuestionRegion(
        region_id="REG-P02-01",
        page_number=2,
        submission_id="SUB-R",
        bbox=BoundingBox(x_min=0.0, y_min=0.1, x_max=1.0, y_max=0.5),
    ).model_dump()
    r11["question_id"] = "Q11"  # set by map_questions
    r12["question_id"] = "Q12"

    state = {
        "submission_id": "SUB-R",
        "pdf_pages": 2,
        "regions_count": 2,
        "region_records": [r11, r12],
        "ocr_records": [["REG-P01-01", ocr_record("REG-P01-01")], ["REG-P02-01", ocr_record("REG-P02-01")]],
        "diagram_records": [],
        "mapping_uncertain_questions": ["Q11"],
    }
    updates = nodes.reconstruct_answers(state)
    answers = {a["question_id"]: a for a in updates["canonical_answers"]}
    assert set(answers) == {"Q11", "Q12"}
    assert "mapping_uncertain" in answers["Q11"]["flags"]
    assert "mapping_uncertain" not in answers["Q12"]["flags"]


# ---------------------------------------------------------------------------
# Canonical question packets (specs #34-35)
# ---------------------------------------------------------------------------


def test_packet_builder_stores_original_diagram_crops(tmp_path) -> None:
    from tests.unit.test_grading_rules import make_answer

    crop_path = tmp_path / "diag.png"
    Image.new("RGB", (50, 50), "white").save(crop_path)

    answer = make_answer("answer body text")
    answer.submission_id = "SUB-P"
    answer.question_id = "Q11"

    diagram_region = QuestionRegion(
        region_id="REG-P03-02",
        page_number=3,
        submission_id="SUB-P",
        question_id="Q11",
        bbox=BoundingBox(x_min=0.1, y_min=0.4, x_max=0.8, y_max=0.7),
        region_type=RegionType.DIAGRAM,
        reading_order=2,
        crop_image_path=str(crop_path),
    )

    storage = LocalStorageProvider(tmp_path / "storage")
    packets = build_question_packets([answer], [diagram_region], storage)

    assert len(packets) == 1
    packet = packets[0]
    assert packet.student_id == "SUB-P"
    assert packet.question_id == "Q11"
    assert packet.pages == [1]
    assert packet.word_count == 3  # deterministic split of "answer body text"
    diagram = packet.student_diagram_images[0]
    assert diagram.diagram_id == "STUDENT-Q11-D1"
    assert diagram.page == 3
    # The ORIGINAL image bytes are retrievable from immutable storage (#35).
    with storage.open(diagram.image_object_key) as handle:
        assert handle.read(8)[:4] == b"\x89PNG"


def test_packet_without_diagrams_has_empty_images(tmp_path) -> None:
    from tests.unit.test_grading_rules import make_answer

    answer = make_answer("plain text")
    answer.submission_id = "SUB-Q"
    answer.question_id = "Q3"

    packets = build_question_packets([answer], [], LocalStorageProvider(tmp_path / "s"))
    assert packets[0].student_diagram_images == []


# ---------------------------------------------------------------------------
# Region-header anchor fallback in map_questions (mapping robustness step 1)
# ---------------------------------------------------------------------------


def _no_margin_state(tmp_path: Path) -> dict:
    """Page with NO ink in the left margin band and three answer blocks."""
    page = tmp_path / "page.png"
    image = Image.new("RGB", (1000, 2000), "white")
    draw = ImageDraw.Draw(image)
    draw.text((400, 240), "Q3", fill="black")  # inside region 1 header band
    draw.text((400, 600), "answer body", fill="black")
    draw.text((400, 1040), "Q4", fill="black")  # inside region 2 header band
    draw.text((400, 1400), "answer body", fill="black")
    draw.text((400, 1800), "answer body", fill="black")  # region 3: no header
    image.save(page)

    regions = [
        QuestionRegion(
            region_id="REG-P01-01",
            page_number=1,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.10, x_max=1.0, y_max=0.45),
            reading_order=1,
        ),
        QuestionRegion(
            region_id="REG-P01-02",
            page_number=1,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.50, x_max=1.0, y_max=0.75),
            reading_order=2,
        ),
        QuestionRegion(
            region_id="REG-P01-03",
            page_number=1,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.80, x_max=1.0, y_max=0.98),
            reading_order=3,
        ),
    ]
    return {
        "submission_id": "SUB-M",
        "rubrics": {"Q3": {"question_id": "Q3"}, "Q4": {"question_id": "Q4"}, "Q5": {"question_id": "Q5"}},
        "page_records": [page_record(1, page)],
        "region_records": [r.model_dump() for r in regions],
    }


def test_map_questions_header_anchor_fallback(tmp_path) -> None:
    # OCR call order: margin strip (empty), then region headers 1..3.
    provider = ScriptedTextProvider(["", "3", "4", "momentum is mass times velocity"])
    updates = nodes.map_questions(_no_margin_state(tmp_path), provider)

    spans = {span["question_id"]: span for span in updates["question_spans"]}
    assert set(spans) == {"Q3", "Q4", "Q5"}
    assert spans["Q3"]["region_ids"] == ["REG-P01-01"]
    assert spans["Q4"]["region_ids"] == ["REG-P01-02"]
    # Q5 has no header anchor anywhere: the trailing block is re-claimed and
    # the guess is flagged for teacher review, never silent.
    assert spans["Q5"]["region_ids"] == ["REG-P01-03"]
    assert "tail_assigned_in_reading_order" in spans["Q5"]["uncertainty_reasons"]
    for span in spans.values():
        assert "header_anchor_mapping" in span["uncertainty_reasons"]
    assert set(updates["mapping_uncertain_questions"]) == {"Q3", "Q4", "Q5"}
    assert updates["unassigned_regions"] == []

    by_region = {r["region_id"]: r["question_id"] for r in updates["region_records"]}
    assert by_region == {
        "REG-P01-01": "Q3",
        "REG-P01-02": "Q4",
        "REG-P01-03": "Q5",
    }


class DualModeProvider(MockInferenceProvider):
    """OCR calls get OCR envelopes; semantic-mapping calls get raw JSON."""

    def __init__(self, ocr_texts: list[str], semantic_texts: list[str]) -> None:
        self._ocr = list(ocr_texts)
        self._semantic = list(semantic_texts)

    async def infer(self, request):  # type: ignore[override]
        import json

        if request.metadata.get("task") == "semantic_mapping":
            text = self._semantic.pop(0) if self._semantic else ""
        else:
            text = self._ocr.pop(0) if self._ocr else ""
            text = json.dumps({"raw_text": text, "lines": [text], "uncertain_spans": [], "flags": []})
        return InferenceResponse(
            request_id=request.request_id,
            provider="mock",
            model_id="mock_4b",
            text=text,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            timing=InferenceTiming(total_inference_ms=50.0),
        )


def test_map_questions_semantic_fallback_for_unnumbered_tail(tmp_path) -> None:
    # Margin anchor gives Q3; two trailing blocks are unnumbered. The tail is
    # too big for deterministic repair (2 trailing > 2 x 1 missing is false ->
    # repair declines only past 2x; here 2 <= 2 so repair would fire... use 3
    # trailing blocks to force the semantic path).
    p1 = tmp_path / "page.png"
    draw_anchor_page(p1, [300])  # left-band ink -> margin anchor "3"
    regions = [
        QuestionRegion(
            region_id="REG-P01-01",
            page_number=1,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.50, x_max=1.0, y_max=0.70),
            reading_order=1,
        ),
        QuestionRegion(
            region_id="REG-P01-02",
            page_number=1,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.74, x_max=1.0, y_max=0.84),
            reading_order=2,
        ),
        QuestionRegion(
            region_id="REG-P01-03",
            page_number=1,
            submission_id="SUB-M",
            bbox=BoundingBox(x_min=0.2, y_min=0.86, x_max=1.0, y_max=0.96),
            reading_order=3,
        ),
    ]
    state = {
        "submission_id": "SUB-M",
        "rubrics": {"Q3": {"question_id": "Q3"}, "Q4": {"question_id": "Q4"}},
        "page_records": [page_record(1, p1)],
        "region_records": [r.model_dump() for r in regions],
    }
    provider = DualModeProvider(
        ocr_texts=[
            "3",  # margin strip
            "answer about tcp retransmission",  # candidate R1
            "principal component analysis projects data",  # candidate R2
            "k means clustering groups similar points",  # candidate R3
        ],
        semantic_texts=[
            '{"assignments": [{"question_id": "Q4", "region_ids": ["REG-P01-02"]}]}',
        ],
    )

    updates = nodes.map_questions(state, provider)

    spans = {span["question_id"]: span for span in updates["question_spans"]}
    assert set(spans) == {"Q3", "Q4"}
    # Q4 was assigned BY CONTENT (no number was ever written).
    assert spans["Q4"]["region_ids"] == ["REG-P01-02"]
    assert "semantic_mapping" in spans["Q4"]["uncertainty_reasons"]
    assert "llm_assigned_by_content" in spans["Q4"]["uncertainty_reasons"]
    # The unmatched candidate stays with its continuation owner, flagged.
    assert spans["Q3"]["region_ids"] == ["REG-P01-01", "REG-P01-03"]
    assert "semantic_unmatched_tail" in spans["Q3"]["uncertainty_reasons"]
    assert set(updates["mapping_uncertain_questions"]) == {"Q3", "Q4"}
    by_region = {r["region_id"]: r["question_id"] for r in updates["region_records"]}
    assert by_region == {"REG-P01-01": "Q3", "REG-P01-02": "Q4", "REG-P01-03": "Q3"}




