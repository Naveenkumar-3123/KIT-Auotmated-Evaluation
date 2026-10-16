"""Unit tests for OllamaProvider and VisionService."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from answer_eval.core.errors import (
    VisionRequestError,
)
from answer_eval.inference.ollama_provider import OllamaProvider, _encode_image_to_data_uri
from answer_eval.inference.types import ImageInput, InferenceRequest, ReasoningMode
from answer_eval.services.vision import VisionService


def test_ollama_provider_initialization() -> None:
    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3-vl:4b",
        timeout_seconds=90.0,
        max_retries=3,
    )
    assert provider.base_url == "http://127.0.0.1:11434/v1"
    assert provider.model_name == "qwen3-vl:4b"
    assert provider.timeout_seconds == 90.0
    assert provider.max_retries == 3


def test_encode_image_to_data_uri(temp_workspace: Path, sample_image: Image.Image) -> None:
    img_path = temp_workspace / "sample.png"
    sample_image.save(img_path)

    img_input = ImageInput(image_path=str(img_path), mime_type="image/png")
    data_uri = _encode_image_to_data_uri(img_input)

    assert data_uri.startswith("data:image/png;base64,")
    assert len(data_uri) > 50

    # Nonexistent path
    with pytest.raises(VisionRequestError):
        _encode_image_to_data_uri(ImageInput(image_path="nonexistent.png"))


@pytest.mark.asyncio
async def test_ollama_detailed_health_check_online() -> None:
    provider = OllamaProvider(base_url="http://127.0.0.1:11434/v1", model_name="qwen3-vl:4b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "qwen3-vl:4b", "object": "model"}]}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        health = await provider.check_detailed_health()
        assert health["available"] is True
        assert "qwen3-vl:4b" in health["installed_models"]


@pytest.mark.asyncio
async def test_ollama_detailed_health_check_model_missing() -> None:
    provider = OllamaProvider(base_url="http://127.0.0.1:11434/v1", model_name="qwen3-vl:30b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "qwen3-vl:4b", "object": "model"}]}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        health = await provider.check_detailed_health()
        assert health["available"] is False
        assert "ollama pull qwen3-vl:30b" in health["help_message"]


@pytest.mark.asyncio
async def test_provider_consumes_ocr_config_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider must read num_ctx/num_predict from configuration, not literals."""
    monkeypatch.setenv("OLLAMA_OCR_NUM_CTX", "32768")
    monkeypatch.setenv("OLLAMA_OCR_NUM_PREDICT", "8192")

    provider = OllamaProvider(base_url="http://127.0.0.1:11434/v1", model_name="qwen3-vl:4b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": "OK"},
        "prompt_eval_count": 5,
        "eval_count": 1,
        "done_reason": "stop",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        # max_tokens unset -> generation budget comes from configuration
        req = InferenceRequest(request_id="req-env", prompt="Hello")
        await provider.infer(req)

        sent_payload = mock_post.call_args.kwargs["json"]
        assert sent_payload["options"]["num_ctx"] == 32768
        assert sent_payload["options"]["num_predict"] == 8192


@pytest.mark.asyncio
async def test_provider_defaults_match_working_configuration() -> None:
    """With no overrides the effective request must match the tested defaults."""
    provider = OllamaProvider(base_url="http://127.0.0.1:11434/v1", model_name="qwen3-vl:4b")
    assert provider._ocr_cfg.num_ctx == 16384
    assert provider._ocr_cfg.num_predict == 4096
    assert provider._ocr_cfg.temperature == 0.0
    # Empty ocr.model inherits the globally configured model
    assert provider._resolve_ocr_model() == "qwen3-vl:4b"


@pytest.mark.asyncio
async def test_ollama_infer_success_native_direct_think_disabled() -> None:
    """DIRECT mode (OCR default) must hit native /api/chat with think=false."""
    provider = OllamaProvider(base_url="http://127.0.0.1:11434/v1", model_name="qwen3-vl:4b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": "QWEN_CONNECTION_OK"},
        "prompt_eval_count": 10,
        "eval_count": 5,
        "done_reason": "stop",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        req = InferenceRequest(request_id="req-1", prompt="Hello", max_tokens=4096)
        resp = await provider.infer(req)
        assert resp.text == "QWEN_CONNECTION_OK"
        assert resp.usage.total_tokens == 15
        assert resp.provider == "ollama"
        assert resp.stop_reason == "stop"
        assert resp.thinking_disabled is True

        # Native endpoint used, thinking explicitly disabled, budget forwarded
        called_url = mock_post.call_args.args[0]
        assert called_url.endswith("/api/chat")
        sent_payload = mock_post.call_args.kwargs["json"]
        assert sent_payload["think"] is False
        assert sent_payload["options"]["num_predict"] == 4096
        assert sent_payload["options"]["temperature"] == 0.1

        # Assistant prefill with closed <think> block forces direct transcription
        roles = [m["role"] for m in sent_payload["messages"]]
        assert roles[-1] == "assistant"
        assert "<think>" in sent_payload["messages"][-1]["content"]
        assert "</think>" in sent_payload["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_ollama_infer_compat_path_normal_mode() -> None:
    """NORMAL mode keeps using the OpenAI-compatible /v1/chat/completions API."""
    provider = OllamaProvider(base_url="http://127.0.0.1:11434/v1", model_name="qwen3-vl:4b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "COMPAT_OK"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        req = InferenceRequest(
            request_id="req-2",
            prompt="Hello",
            reasoning_mode=ReasoningMode.NORMAL,
        )
        resp = await provider.infer(req)
        assert resp.text == "COMPAT_OK"
        assert resp.stop_reason == "stop"

        called_url = mock_post.call_args.args[0]
        assert called_url.endswith("/chat/completions")
        sent_payload = mock_post.call_args.kwargs["json"]
        assert "think" not in sent_payload


@pytest.mark.asyncio
async def test_vision_service_methods(temp_workspace: Path, sample_image: Image.Image) -> None:
    img_path = temp_workspace / "doc.png"
    sample_image.save(img_path)

    provider = OllamaProvider(base_url="http://127.0.0.1:11434/v1", model_name="qwen3-vl:4b")
    service = VisionService(provider=provider)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # VisionService uses ReasoningMode.DIRECT -> native /api/chat response format
    mock_resp.json.return_value = {
        "message": {"content": "The protocall is use for comunication"},
        "prompt_eval_count": 20,
        "eval_count": 10,
        "done_reason": "stop",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        # Text
        txt = await service.generate_text("Hi")
        assert "protocall" in txt

        # Image analysis
        vis = await service.analyze_image(image=img_path, prompt="Describe")
        assert "protocall" in vis

        # OCR
        ocr = await service.extract_ocr(image=img_path)
        assert "protocall" in ocr
