"""Unit tests for Module 9: OCR Agent (Exact Verbatim Transcription)."""

from pathlib import Path

import pytest

from answer_eval.agents.ocr.agent import OCRAgent, count_words_deterministic
from answer_eval.agents.ocr.schemas import OCRResult
from answer_eval.inference.types import (
    InferenceResponse,
    InferenceTiming,
    ReasoningMode,
    TokenUsage,
)
from answer_eval.processing.segmentation.schemas import BoundingBox, QuestionRegion
from tests.conftest import MockInferenceProvider


class _ScriptedProvider(MockInferenceProvider):
    """Mock provider returning scripted OCR text / stop reasons for validation tests."""

    def __init__(self, responses: list[tuple[str, str | None]]) -> None:
        super().__init__()
        self._responses = list(responses)

    async def infer(self, request):  # type: ignore[override]
        self.call_history.append(request)
        text, stop_reason = self._responses.pop(0) if self._responses else ("", None)
        return InferenceResponse(
            request_id=request.request_id,
            provider="mock",
            model_id="mock_4b",
            text=text,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            timing=InferenceTiming(total_inference_ms=100.0),
            stop_reason=stop_reason,
        )


def test_deterministic_word_count() -> None:
    text = "The protocall is use for comunication between network layers."
    assert count_words_deterministic(text) == 9
    assert count_words_deterministic("   ") == 0
    assert count_words_deterministic("one\ntwo\tthree") == 3


@pytest.mark.asyncio
async def test_ocr_agent_extraction(mock_provider: MockInferenceProvider, temp_workspace: Path) -> None:
    # Create fake crop image file
    crop_file = temp_workspace / "crop1.png"
    crop_file.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_bytes")

    region = QuestionRegion(
        region_id="REG-P01-01",
        page_number=1,
        submission_id="SUB-01",
        question_id="Q1",
        bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=0.5),
        crop_image_path=str(crop_file),
        crop_image_hash="abc_crop_hash",
    )

    ocr_agent = OCRAgent(inference_provider=mock_provider)
    result = await ocr_agent.extract_text(region)

    assert isinstance(result, OCRResult)
    # Check verbatim spelling mistake preservation
    assert "protocall" in result.raw_text
    assert "comunication" in result.raw_text
    assert result.word_count == 6
    assert result.provenance.region_id == "REG-P01-01"
    assert result.provenance.submission_id == "SUB-01"
    assert result.provenance.source_image_hash == "abc_crop_hash"
    assert result.provenance.model_id == "qwen_vl_4b_q8"


def _make_region(temp_workspace: Path) -> QuestionRegion:
    crop_file = temp_workspace / "crop1.png"
    crop_file.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_bytes")
    return QuestionRegion(
        region_id="REG-P01-01",
        page_number=1,
        submission_id="SUB-01",
        question_id="Q1",
        bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=0.5),
        crop_image_path=str(crop_file),
        crop_image_hash="abc_crop_hash",
    )


@pytest.mark.asyncio
async def test_ocr_request_disables_thinking_and_sets_budget(
    mock_provider: MockInferenceProvider, temp_workspace: Path
) -> None:
    ocr_agent = OCRAgent(inference_provider=mock_provider)
    result = await ocr_agent.extract_text(_make_region(temp_workspace))

    assert result.status == "success"
    req = mock_provider.call_history[0]
    # Thinking disabled for OCR + deterministic temperature + adequate budget
    assert req.reasoning_mode == ReasoningMode.DIRECT
    assert req.temperature == 0.0
    assert req.max_tokens >= 4096


@pytest.mark.asyncio
async def test_empty_response_never_success_after_retries(temp_workspace: Path) -> None:
    provider = _ScriptedProvider([("", None), ("", None)])
    ocr_agent = OCRAgent(inference_provider=provider)
    result = await ocr_agent.extract_text(_make_region(temp_workspace))

    assert result.status == "failed"
    assert result.raw_text == ""
    assert len(provider.call_history) == 2  # controlled retry cap, no infinite loop


@pytest.mark.asyncio
async def test_empty_then_valid_retry_succeeds(temp_workspace: Path) -> None:
    provider = _ScriptedProvider([("", None), ("Bagging ensemble", "stop")])
    ocr_agent = OCRAgent(inference_provider=provider)
    result = await ocr_agent.extract_text(_make_region(temp_workspace))

    assert result.status == "success"
    assert result.raw_text == "Bagging ensemble"
    assert len(provider.call_history) == 2


@pytest.mark.asyncio
async def test_generation_limit_marks_truncated(temp_workspace: Path) -> None:
    provider = _ScriptedProvider([("partial transcription text", "length")])
    ocr_agent = OCRAgent(inference_provider=provider)
    result = await ocr_agent.extract_text(_make_region(temp_workspace))

    assert result.status == "truncated"
    assert "generation_limit" in result.flags
