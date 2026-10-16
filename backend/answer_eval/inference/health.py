"""Health check and multimodal smoke test suite for inference providers."""

import io
import time
from typing import Any

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from answer_eval.core.logging import get_logger
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import ImageInput, InferenceRequest

logger = get_logger("inference.health")


class SmokeTestResult(BaseModel):
    """Result of inference server verification test."""

    is_healthy: bool
    text_inference_passed: bool = False
    vision_inference_passed: bool = False
    structured_json_passed: bool = False
    total_duration_ms: float = 0.0
    error_message: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _generate_synthetic_test_image() -> bytes:
    """Generate a lightweight synthetic 256x256 test image containing basic text."""
    img = Image.new("RGB", (256, 256), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 236, 236], outline=(0, 0, 0), width=2)
    draw.text((40, 100), "TEST 123", fill=(0, 0, 0))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


async def run_multimodal_smoke_test(
    provider: InferenceProvider,
    timeout_seconds: float = 30.0,
) -> SmokeTestResult:
    """
    Run health check, text inference, vision inference, and structured output test.
    Returns SmokeTestResult.
    """
    start_time = time.perf_counter()
    logger.info("Initiating multimodal smoke test")

    # 1. Health check
    is_healthy = await provider.health_check()
    if not is_healthy:
        return SmokeTestResult(
            is_healthy=False,
            error_message="Server health check returned unreachable/unhealthy status.",
        )

    text_passed = False
    vision_passed = False
    structured_passed = False
    error_msg = None
    diagnostics: dict[str, Any] = {}

    # 2. Small text inference test
    try:
        req = InferenceRequest(
            request_id="smoke_test_text",
            prompt="Respond with exactly 'OK'",
            max_tokens=10,
            temperature=0.0,
        )
        resp = await provider.infer(req)
        text_passed = len(resp.text.strip()) > 0
        diagnostics["text_sample"] = resp.text.strip()
    except Exception as e:
        error_msg = f"Text inference failed: {e}"
        logger.warning("Smoke test text inference failed", error=str(e))

    # 3. Vision inference test if supported
    caps = provider.get_capabilities()
    if caps.vision and text_passed:
        try:
            img_bytes = _generate_synthetic_test_image()
            req_vision = InferenceRequest(
                request_id="smoke_test_vision",
                prompt="What text is visible in this image?",
                images=[ImageInput(image_bytes=img_bytes, mime_type="image/png")],
                max_tokens=30,
                temperature=0.0,
            )
            resp_vision = await provider.infer(req_vision)
            vision_passed = len(resp_vision.text.strip()) > 0
            diagnostics["vision_sample"] = resp_vision.text.strip()
        except Exception as e:
            error_msg = f"Vision inference failed: {e}"
            logger.warning("Smoke test vision inference failed", error=str(e))
    elif not caps.vision:
        vision_passed = True  # Not required for non-vision models

    # 4. Structured output test
    if text_passed and (not caps.vision or vision_passed):
        try:

            class TestSchema(BaseModel):
                status: str
                test_number: int

            schema_req = InferenceRequest(
                request_id="smoke_test_schema",
                prompt="Respond in JSON: status='pass', test_number=1",
                max_tokens=50,
                temperature=0.0,
            )
            resp_struct = await provider.infer_structured(schema_req, schema=TestSchema)
            structured_passed = (
                resp_struct.structured_data is not None and resp_struct.structured_data.get("status") is not None
            )
            diagnostics["structured_sample"] = resp_struct.structured_data
        except Exception as e:
            error_msg = f"Structured output test failed: {e}"
            logger.warning("Smoke test structured output failed", error=str(e))

    total_ms = round((time.perf_counter() - start_time) * 1000, 2)
    overall_passed = is_healthy and text_passed and vision_passed and structured_passed

    logger.info(
        "Multimodal smoke test complete",
        overall_passed=overall_passed,
        duration_ms=total_ms,
        error=error_msg,
    )

    return SmokeTestResult(
        is_healthy=is_healthy,
        text_inference_passed=text_passed,
        vision_inference_passed=vision_passed,
        structured_json_passed=structured_passed,
        total_duration_ms=total_ms,
        error_message=error_msg,
        diagnostics=diagnostics,
    )
