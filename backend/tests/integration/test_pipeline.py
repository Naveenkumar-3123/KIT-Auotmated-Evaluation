"""Integration test: End-to-end perception pipeline from PDF to Canonical Structured JSON."""

from pathlib import Path

import pytest

from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.pipeline import EvaluationPipeline
from answer_eval.processing.image.preprocessing import ImagePreprocessor
from answer_eval.processing.pdf.processor import PDFProcessor
from answer_eval.processing.segmentation.segmenter import QuestionSegmenter
from tests.conftest import MockInferenceProvider


@pytest.mark.asyncio
async def test_full_pipeline_integration(
    sample_pdf: Path,
    mock_provider: MockInferenceProvider,
    temp_workspace: Path,
) -> None:
    """
    Test complete perception pipeline execution:
    1. Render multi-page student answer sheet PDF
    2. Image Preprocessing (deskew, border cleanup, quality analysis)
    3. Question Layout Segmentation (detect blocks and diagrams)
    4. Perception Agents (exact OCR & diagram observation)
    5. Reconstruct canonical answers preserving immutable raw OCR and provenance
    """
    pdf_processor = PDFProcessor(
        default_dpi=150,
        output_dir=temp_workspace / "rendered_pages",
    )
    image_preprocessor = ImagePreprocessor(
        output_dir=temp_workspace / "preprocessed_pages",
    )
    question_segmenter = QuestionSegmenter(
        crops_output_dir=temp_workspace / "region_crops",
    )

    pipeline = EvaluationPipeline(
        inference_provider=mock_provider,
        pdf_processor=pdf_processor,
        image_preprocessor=image_preprocessor,
        question_segmenter=question_segmenter,
    )

    answers = await pipeline.process_submission(
        pdf_path=sample_pdf,
        submission_id="SUB-INT-001",
    )

    assert len(answers) >= 1
    ans = answers[0]
    assert isinstance(ans, CanonicalStructuredAnswer)
    assert ans.submission_id == "SUB-INT-001"
    assert ans.question_id is not None
    assert len(ans.source_pages) >= 1
    assert len(ans.raw_text) > 0
    assert ans.word_count > 0
    assert len(ans.segments) >= 1
    assert ans.provenance.submission_id == "SUB-INT-001"
    assert ans.provenance.model_id == "qwen_vl_4b_q8"

    # Verify all intermediary files exist on disk
    rendered_files = list((temp_workspace / "rendered_pages").glob("*.png"))
    prep_files = list((temp_workspace / "preprocessed_pages").glob("*.png"))
    crop_files = list((temp_workspace / "region_crops").glob("*.png"))

    assert len(rendered_files) == 2  # 2 pages in sample PDF
    assert len(prep_files) == 2
    assert len(crop_files) >= 2
