"""Shared test fixtures for unit and integration testing."""

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw

from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import (
    InferenceRequest,
    InferenceResponse,
    InferenceTiming,
    MemorySnapshot,
    TokenUsage,
)
from answer_eval.models.profiles import ModelCapabilities, ModelProfile, ProviderType
from answer_eval.runtime.profiles import RuntimeConfig


class MockInferenceProvider(InferenceProvider):
    """In-memory mock inference provider for testing perception agents and pipeline."""

    def __init__(
        self,
        mock_text: str = '{"raw_text": "The protocall is use for comunication", "lines": ["The protocall is use for comunication"], "uncertain_spans": [], "flags": []}',
        mock_diagram_text: str = '{"diagram_present": true, "diagram_type_guess": "flowchart", "labels": [{"text": "Transport", "uncertain": false}], "components": [{"type": "box", "label": "Transport", "description": "outer box"}], "relationships": [], "visual_quality": {"legibility": "good", "label_clarity": "good", "completeness_appearance": "complete"}, "uncertain_elements": []}',
        should_fail_structured: bool = False,
    ) -> None:
        self.mock_text = mock_text
        self.mock_diagram_text = mock_diagram_text
        self.should_fail_structured = should_fail_structured
        self.call_history: list[InferenceRequest] = []
        self.model_profile: ModelProfile | None = None
        self.runtime_config: RuntimeConfig | None = None

    async def initialize(
        self,
        model: ModelProfile,
        config: RuntimeConfig,
        hardware: HardwareProfile | None = None,
    ) -> None:
        self.model_profile = model
        self.runtime_config = config

    async def health_check(self) -> bool:
        return True

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(vision=True, structured_output=True, thinking=False)

    def get_memory_usage(self) -> MemorySnapshot:
        return MemorySnapshot(
            vram_used_gb=3.5,
            vram_free_gb=8.5,
            ram_used_gb=4.0,
            ram_available_gb=28.0,
        )

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        self.call_history.append(request)
        is_diag = "diagram" in request.prompt.lower()
        if "smoke_test_schema" in request.request_id or "test_number" in request.prompt:
            content = '{"status": "pass", "test_number": 1}'
        elif is_diag:
            content = self.mock_diagram_text
        else:
            content = self.mock_text

        return InferenceResponse(
            request_id=request.request_id,
            provider="mock",
            model_id=self.model_profile.model_id if self.model_profile else "mock_4b",
            quantization=self.model_profile.quantization if self.model_profile else "Q8_0",
            text=content,
            usage=TokenUsage(prompt_tokens=50, completion_tokens=30, total_tokens=80),
            timing=InferenceTiming(total_inference_ms=120.0, tokens_per_second=45.0),
            memory=self.get_memory_usage(),
        )

    async def infer_structured(
        self,
        request: InferenceRequest,
        schema: type | dict[str, Any],
        max_retries: int = 2,
    ) -> InferenceResponse:
        import json

        resp = await self.infer(request)
        if self.should_fail_structured:
            from answer_eval.core.errors import InferenceOutputValidationError

            raise InferenceOutputValidationError("Mock forced validation failure")

        cleaned = resp.text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)
        resp.structured_data = data
        return resp

    async def shutdown(self) -> None:
        pass


@pytest.fixture
def mock_provider() -> MockInferenceProvider:
    provider = MockInferenceProvider()
    provider.model_profile = ModelProfile(
        model_id="qwen_vl_4b_q8",
        display_name="Qwen3-VL 4B Q8",
        family="qwen3_vl",
        size_class="4b",
        provider_type=ProviderType.LLAMA_SERVER,
        quantization="Q8_0",
        checkpoint_path="models/test.gguf",
    )
    return provider


@pytest.fixture
def temp_workspace() -> Path:
    temp_dir = tempfile.mkdtemp(prefix="answer_eval_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_pdf(temp_workspace: Path) -> Path:
    """Create a valid synthetic 2-page student answer sheet PDF."""
    pdf_path = temp_workspace / "sample_answer_sheet.pdf"
    doc = fitz.open()

    # Page 1
    page1 = doc.new_page(width=595, height=842)  # A4 standard
    p1 = fitz.Point(50, 80)
    page1.insert_text(p1, "Q1: Explain the TCP protocol in computer networks.", fontsize=12)
    p2 = fitz.Point(50, 140)
    page1.insert_text(p2, "Answer: The protocall is use for comunication between clients.", fontsize=11)
    # Draw simple diagram box
    page1.draw_rect(fitz.Rect(50, 220, 300, 380), color=(0, 0, 0), width=1.5)
    page1.insert_text(fitz.Point(120, 290), "[ Transport Layer ]", fontsize=11)

    # Page 2 (Continuation)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text(fitz.Point(50, 80), "Q1 (Continued):", fontsize=12)
    page2.insert_text(
        fitz.Point(50, 120),
        "It guarantees reliable delivery using acknowledgments and windowing.",
        fontsize=11,
    )

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_image() -> Image.Image:
    """Create a sample PIL image with text and drawing."""
    img = Image.new("RGB", (600, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 560, 360], outline=(0, 0, 0), width=2)
    draw.text((60, 60), "Student Answer Sheet Sample", fill=(0, 0, 0))
    return img
