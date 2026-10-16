"""Unit tests for TestUIAdapter in tools/test_ui/adapter.py."""

from pathlib import Path

import pytest
from PIL import Image

from answer_eval.core.errors import PDFValidationError
from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.processing.segmentation.schemas import BoundingBox, QuestionRegion, RegionType
from tests.conftest import MockInferenceProvider
from tools.test_ui.adapter import (
    GranularPipelineResult,
    PipelineExecutionOptions,
    PipelineProgressEvent,
    TestUIAdapter,
)


def test_ui_adapter_models_and_hardware(temp_workspace: Path) -> None:
    adapter = TestUIAdapter(workspace_root=Path("."))
    models = adapter.get_available_models()
    assert len(models) >= 3

    m_ids = [m.model_id for m in models]
    assert "qwen_vl_4b_q8" in m_ids
    assert "qwen_vl_4b_q4" in m_ids
    assert "qwen_vl_large_local" in m_ids

    hw = adapter.get_hardware_status()
    assert isinstance(hw, HardwareProfile)
    assert hw.system_ram_total_gb > 0


def test_ui_adapter_session_lifecycle(temp_workspace: Path) -> None:
    adapter = TestUIAdapter(workspace_root=temp_workspace, temp_dir=temp_workspace / "temp_ui")
    sid, sdir = adapter.create_session()
    assert sdir.exists()
    assert sid.startswith("sess_")

    # Save PDF
    dummy_pdf_bytes = b"%PDF-1.5 valid dummy pdf bytes"
    saved_path = adapter.save_uploaded_pdf(
        file_bytes=dummy_pdf_bytes,
        original_filename="student_paper.pdf",
        session_dir=sdir,
    )
    assert saved_path.exists()
    assert saved_path.suffix == ".pdf"

    # Non-PDF extension rejection
    with pytest.raises(PDFValidationError):
        adapter.save_uploaded_pdf(
            file_bytes=b"malicious executable",
            original_filename="script.exe",
            session_dir=sdir,
        )

    # Clear session
    adapter.clear_session(sdir)
    assert not sdir.exists()


def test_ui_adapter_draw_boxes(sample_image: Image.Image, temp_workspace: Path) -> None:
    img_path = temp_workspace / "page.png"
    sample_image.save(img_path)

    regions = [
        QuestionRegion(
            region_id="REG-01",
            page_number=1,
            submission_id="SUB-01",
            question_id="Q1",
            bbox=BoundingBox(x_min=0.1, y_min=0.1, x_max=0.9, y_max=0.4),
            region_type=RegionType.ANSWER_TEXT,
        ),
        QuestionRegion(
            region_id="REG-02",
            page_number=1,
            submission_id="SUB-01",
            question_id="Q1",
            bbox=BoundingBox(x_min=0.1, y_min=0.5, x_max=0.9, y_max=0.9),
            region_type=RegionType.DIAGRAM,
        ),
    ]

    adapter = TestUIAdapter(workspace_root=temp_workspace)
    annotated = adapter.draw_segmentation_boxes_on_page(img_path, regions)
    assert isinstance(annotated, Image.Image)
    assert annotated.size == sample_image.size


def test_ui_adapter_ground_truth_and_fixture_saving(sample_image: Image.Image, temp_workspace: Path) -> None:
    adapter = TestUIAdapter(workspace_root=temp_workspace)

    metrics = adapter.calculate_ocr_metrics_for_region(
        predicted_text="The protocall is use for comunication",
        ground_truth_text="The protocall is use for comunication",
    )
    assert metrics["exact_match"] is True
    assert metrics["cer"] == 0.0

    # Save as fixture
    crop_path = temp_workspace / "test_crop.png"
    sample_image.save(crop_path)

    t_img, t_gt = adapter.save_as_benchmark_fixture(
        crop_image_path=crop_path,
        ground_truth_text="The protocall is use for comunication",
        sample_id="test_sample_01",
        known_misspellings=["protocall", "comunication"],
    )
    assert t_img.exists()
    assert t_gt.exists()


@pytest.mark.asyncio
async def test_ui_adapter_pipeline_execution_with_progress(
    sample_pdf: Path,
    mock_provider: MockInferenceProvider,
    temp_workspace: Path,
) -> None:
    adapter = TestUIAdapter(workspace_root=temp_workspace, temp_dir=temp_workspace / "temp_ui")
    sid, sdir = adapter.create_session()

    progress_events: list[PipelineProgressEvent] = []

    def on_progress(evt: PipelineProgressEvent) -> None:
        progress_events.append(evt)

    opts = PipelineExecutionOptions(
        model_id="qwen_vl_4b_q8",
        render_dpi=150,
        mock_mode=True,
    )

    result = await adapter.execute_perception_pipeline(
        pdf_path=sample_pdf,
        session_dir=sdir,
        options=opts,
        progress_callback=on_progress,
        custom_inference_provider=mock_provider,
    )

    assert isinstance(result, GranularPipelineResult)
    assert result.error_message is None
    assert len(progress_events) >= 5
    assert len(result.preprocessed_pages) == 2
    assert len(result.segmentation_results) == 2
    assert len(result.ocr_results) >= 1
    assert len(result.canonical_answers) >= 1
    assert result.total_duration_ms > 0
