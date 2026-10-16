"""Unit tests for Module 11: Answer Reconstruction."""

from answer_eval.agents.diagram.schemas import (
    DiagramComponent,
    DiagramLabel,
    DiagramResult,
    DiagramVisualQuality,
)
from answer_eval.agents.ocr.schemas import OCRResult, OCRUncertainSpan
from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.agents.reconstruction.service import ReconstructionService
from answer_eval.core.provenance import Provenance
from answer_eval.processing.segmentation.schemas import BoundingBox, QuestionRegion, RegionType


def test_multi_page_answer_reconstruction() -> None:
    service = ReconstructionService()

    # Region 1 (Page 1)
    r1 = QuestionRegion(
        region_id="REG-P01-01",
        page_number=1,
        submission_id="SUB-001",
        question_id="Q1",
        reading_order=1,
        bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=0.5),
        crop_image_hash="hash_p1",
    )
    ocr1 = OCRResult(
        raw_text="The protocall is use for comunication",
        lines=["The protocall is use for comunication"],
        uncertain_spans=[OCRUncertainSpan(text="protocall", reason="ambiguous_character")],
        flags=["slanted_text"],
        word_count=6,
        provenance=Provenance(
            submission_id="SUB-001",
            page_number=1,
            region_id="REG-P01-01",
            question_id="Q1",
            source_image_hash="hash_p1",
            model_id="qwen_vl_4b_q8",
            request_id="req-1",
        ),
    )

    # Region 2 (Page 2 - continuation)
    r2 = QuestionRegion(
        region_id="REG-P02-01",
        page_number=2,
        submission_id="SUB-001",
        question_id="Q1",
        reading_order=2,
        bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=0.4),
        crop_image_hash="hash_p2",
    )
    ocr2 = OCRResult(
        raw_text="and guarantees reliable packet delivery.",
        lines=["and guarantees reliable packet delivery."],
        uncertain_spans=[],
        flags=[],
        word_count=5,
        provenance=Provenance(
            submission_id="SUB-001",
            page_number=2,
            region_id="REG-P02-01",
            question_id="Q1",
            source_image_hash="hash_p2",
            model_id="qwen_vl_4b_q8",
            request_id="req-2",
        ),
    )

    # Diagram Region (Page 1)
    r_diag = QuestionRegion(
        region_id="REG-P01-02",
        page_number=1,
        submission_id="SUB-001",
        question_id="Q1",
        region_type=RegionType.DIAGRAM,
        reading_order=3,
        bbox=BoundingBox(x_min=0.0, y_min=0.5, x_max=1.0, y_max=1.0),
        crop_image_hash="hash_p1_diag",
    )
    diag_res = DiagramResult(
        diagram_present=True,
        diagram_type_guess="flowchart",
        labels=[DiagramLabel(text="Transport", uncertain=False)],
        components=[DiagramComponent(type="box", label="Transport")],
        relationships=[],
        visual_quality=DiagramVisualQuality(legibility="good", label_clarity="good"),
        uncertain_elements=[],
        provenance=Provenance(
            submission_id="SUB-001",
            page_number=1,
            region_id="REG-P01-02",
            question_id="Q1",
            source_image_hash="hash_p1_diag",
            model_id="qwen_vl_4b_q8",
            request_id="req-diag-1",
        ),
    )

    canonical = service.reconstruct_answer(
        submission_id="SUB-001",
        question_id="Q1",
        ocr_results=[(r1, ocr1), (r2, ocr2)],
        diagram_results=[(r_diag, diag_res)],
    )

    assert isinstance(canonical, CanonicalStructuredAnswer)
    assert canonical.submission_id == "SUB-001"
    assert canonical.question_id == "Q1"
    assert canonical.source_pages == [1, 2]
    assert canonical.raw_text == "The protocall is use for comunication\n\nand guarantees reliable packet delivery."
    assert canonical.word_count == 11
    assert len(canonical.segments) == 2
    assert len(canonical.diagrams) == 1
    assert len(canonical.uncertainties) == 1
    assert canonical.uncertainties[0].text == "protocall"
    assert canonical.provenance.model_id == "qwen_vl_4b_q8"
