"""Unit tests for Module 10: Diagram Extraction Agent & Fallback Resiliency."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from answer_eval.agents.diagram.agent import DiagramAgent
from answer_eval.agents.diagram.schemas import DiagramResult
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    QuestionRegion,
    RegionType,
)
from tests.conftest import MockInferenceProvider


@pytest.fixture
def dummy_crop_image(temp_workspace: Path) -> str:
    img = Image.new("RGB", (300, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 280, 180], outline=(0, 0, 0), width=2)
    draw.text((50, 50), "Diagram Block", fill=(0, 0, 0))
    p = temp_workspace / "diagram_crop.png"
    img.save(p)
    return str(p)


@pytest.mark.asyncio
async def test_diagram_agent_extraction(mock_provider: MockInferenceProvider, dummy_crop_image: str) -> None:
    region = QuestionRegion(
        region_id="REG-P01-02",
        page_number=1,
        submission_id="SUB-01",
        question_id="Q1",
        region_type=RegionType.DIAGRAM,
        bbox=BoundingBox(x_min=0.0, y_min=0.5, x_max=1.0, y_max=1.0),
        crop_image_path=dummy_crop_image,
        crop_image_hash="diag_crop_hash",
    )

    diagram_agent = DiagramAgent(inference_provider=mock_provider)
    result = await diagram_agent.extract_diagram(region)

    assert isinstance(result, DiagramResult)
    assert result.diagram_present is True
    assert result.diagram_type_guess == "flowchart"
    assert len(result.labels) >= 1
    assert result.labels[0].text == "Transport"
    assert len(result.components) >= 1
    assert result.components[0].label == "Transport"
    assert result.visual_quality.legibility == "good"
    assert result.provenance.region_id == "REG-P01-02"
    assert result.provenance.source_image_hash == "diag_crop_hash"


@pytest.mark.asyncio
async def test_diagram_agent_not_a_diagram_fallback(dummy_crop_image: str) -> None:
    """Test F: When VLM reports diagram_present=false, agent performs OCR fallback."""
    provider = MockInferenceProvider(
        mock_text='{"raw_text": "are combined to improve accuracy and reduce overfitting.", "lines": ["are combined to improve accuracy and reduce overfitting."], "uncertain_spans": [], "flags": []}',
        mock_diagram_text='{"diagram_present": false, "diagram_type_guess": "none", "labels": [], "components": [], "relationships": [], "visual_quality": {"legibility": "good", "label_clarity": "good", "completeness_appearance": "complete"}, "uncertain_elements": []}',
    )

    region = QuestionRegion(
        region_id="REG-P01-02",
        page_number=1,
        submission_id="SUB-01",
        question_id="Q1",
        region_type=RegionType.DIAGRAM,
        bbox=BoundingBox(x_min=0.0, y_min=0.4, x_max=1.0, y_max=0.7),
        crop_image_path=dummy_crop_image,
        crop_image_hash="text_crop_hash",
    )

    agent = DiagramAgent(inference_provider=provider)
    result = await agent.extract_diagram(region)

    assert isinstance(result, DiagramResult)
    assert result.diagram_present is False
    assert result.diagram_type_guess == "none"
    assert result.fallback_ocr_text is not None
    assert "improve accuracy" in result.fallback_ocr_text


@pytest.mark.asyncio
async def test_diagram_agent_markdown_fenced_json(dummy_crop_image: str) -> None:
    """Test G: Diagram response wrapped in markdown code fences is handled cleanly."""
    fenced_json = (
        "```json\n"
        "{\n"
        '  "diagram_present": true,\n'
        '  "diagram_type_guess": "block_diagram",\n'
        '  "labels": [{"text": "Layer 1", "uncertain": false}],\n'
        '  "components": [{"type": "box", "label": "Layer 1", "description": "physical"}],\n'
        '  "relationships": [],\n'
        '  "visual_quality": {"legibility": "good", "label_clarity": "good", "completeness_appearance": "complete"},\n'
        '  "uncertain_elements": []\n'
        "}\n"
        "```"
    )
    provider = MockInferenceProvider(mock_diagram_text=fenced_json)

    region = QuestionRegion(
        region_id="REG-P01-03",
        page_number=1,
        submission_id="SUB-01",
        question_id="Q1",
        region_type=RegionType.DIAGRAM,
        bbox=BoundingBox(x_min=0.0, y_min=0.7, x_max=1.0, y_max=1.0),
        crop_image_path=dummy_crop_image,
        crop_image_hash="fenced_crop_hash",
    )

    agent = DiagramAgent(inference_provider=provider)
    result = await agent.extract_diagram(region)

    assert result.diagram_present is True
    assert result.diagram_type_guess == "block_diagram"
    assert len(result.components) == 1
    assert result.components[0].label == "Layer 1"


@pytest.mark.asyncio
async def test_diagram_agent_invalid_json_fallback(dummy_crop_image: str) -> None:
    """Test H: When structured JSON fails validation, agent falls back to OCR instead of crashing."""
    provider = MockInferenceProvider(
        mock_text='{"raw_text": "Fallback OCR text from handwriting", "lines": ["Fallback OCR text from handwriting"], "uncertain_spans": [], "flags": []}',
        should_fail_structured=True,
    )

    region = QuestionRegion(
        region_id="REG-P01-02",
        page_number=1,
        submission_id="SUB-01",
        question_id="Q1",
        region_type=RegionType.DIAGRAM,
        bbox=BoundingBox(x_min=0.0, y_min=0.3, x_max=1.0, y_max=0.6),
        crop_image_path=dummy_crop_image,
        crop_image_hash="invalid_json_crop_hash",
    )

    agent = DiagramAgent(inference_provider=provider)
    # Must NOT raise DiagramExtractionError; must return fallback DiagramResult
    result = await agent.extract_diagram(region)

    assert isinstance(result, DiagramResult)
    assert result.diagram_present is False
    assert result.fallback_ocr_text is not None
    assert "Fallback OCR text" in result.fallback_ocr_text
