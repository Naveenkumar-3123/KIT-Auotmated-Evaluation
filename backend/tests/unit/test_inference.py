"""Unit tests for Inference Provider Abstraction and Health Suites."""

import pytest
from pydantic import BaseModel

from answer_eval.inference.factory import create_inference_provider
from answer_eval.inference.health import run_multimodal_smoke_test
from answer_eval.inference.types import (
    InferenceRequest,
    ReasoningMode,
)
from answer_eval.models.profiles import ModelProfile, ProviderType
from tests.conftest import MockInferenceProvider


def test_provider_factory() -> None:
    llama_model = ModelProfile(
        model_id="qwen_vl_4b_q8",
        display_name="4B",
        size_class="4b",
        provider_type=ProviderType.LLAMA_SERVER,
        checkpoint_path="models/4b.gguf",
    )
    provider = create_inference_provider(llama_model)
    assert provider.__class__.__name__ == "LlamaServerProvider"

    vllm_model = ModelProfile(
        model_id="qwen_vl_cloud",
        display_name="Cloud",
        size_class="large",
        provider_type=ProviderType.VLLM,
        checkpoint_path="Qwen/32B",
        endpoint="http://localhost:8000/v1",
    )
    vllm_prov = create_inference_provider(vllm_model)
    assert vllm_prov.__class__.__name__ == "VLLMProvider"


@pytest.mark.asyncio
async def test_mock_inference_and_structured(mock_provider: MockInferenceProvider) -> None:
    req = InferenceRequest(
        request_id="req-1",
        prompt="Extract text",
        reasoning_mode=ReasoningMode.DIRECT,
    )

    resp = await mock_provider.infer(req)
    assert resp.request_id == "req-1"
    assert resp.provider == "mock"
    assert resp.timing.total_inference_ms > 0

    # Structured inference
    class OutputSchema(BaseModel):
        raw_text: str
        lines: list[str]

    struct_resp = await mock_provider.infer_structured(req, schema=OutputSchema)
    assert struct_resp.structured_data is not None
    assert "raw_text" in struct_resp.structured_data


@pytest.mark.asyncio
async def test_smoke_test_suite(mock_provider: MockInferenceProvider) -> None:
    smoke_res = await run_multimodal_smoke_test(mock_provider)
    assert smoke_res.is_healthy is True
    assert smoke_res.text_inference_passed is True
    assert smoke_res.vision_inference_passed is True
    assert smoke_res.structured_json_passed is True
