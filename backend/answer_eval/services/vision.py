"""High-level reusable Vision and OCR service."""

import uuid
from pathlib import Path
from typing import Any

from answer_eval.core.config import load_settings
from answer_eval.core.errors import VisionRequestError
from answer_eval.core.logging import get_logger
from answer_eval.inference.factory import create_inference_provider
from answer_eval.inference.ollama_provider import OllamaProvider
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import ImageInput, InferenceRequest, ReasoningMode
from answer_eval.prompts.manager import PromptManager

logger = get_logger("services.vision")


class VisionService:
    """
    High-level reusable service for multimodal vision, OCR extraction,
    and text generation using the configured inference provider (Ollama / Qwen-VL).
    """

    def __init__(
        self,
        provider: InferenceProvider | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self.provider = provider or create_inference_provider()
        self.prompt_manager = prompt_manager or PromptManager()

    async def check_health(self) -> dict[str, Any]:
        """Verify inference backend connectivity and model availability."""
        if isinstance(self.provider, OllamaProvider):
            return await self.provider.check_detailed_health()
        is_healthy = await self.provider.health_check()
        return {
            "available": is_healthy,
            "provider": getattr(self.provider, "provider_type", "unknown"),
        }

    async def generate_text(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Execute text-only generation."""
        req = InferenceRequest(
            request_id=f"txt-{uuid.uuid4().hex[:8]}",
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_mode=ReasoningMode.DIRECT,
        )
        resp = await self.provider.infer(req)
        return resp.text.strip()

    async def analyze_image(
        self,
        image: str | bytes | Path,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Execute image analysis with a custom prompt."""
        image_input = self._prepare_image_input(image)
        req = InferenceRequest(
            request_id=f"vis-{uuid.uuid4().hex[:8]}",
            prompt=prompt,
            images=[image_input],
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_mode=ReasoningMode.DIRECT,
        )
        resp = await self.provider.infer(req)
        return resp.text.strip()

    async def extract_ocr(
        self,
        image: str | bytes | Path,
        custom_prompt: str | None = None,
    ) -> str:
        """
        Execute exact verbatim OCR transcription using the strict OCR prompt.
        Preserves all spelling, formatting, and inserts uncertainty markers.
        Generation budget and temperature come from the centralized OCR config
        (settings: ocr.num_predict / ocr.temperature).
        """
        prompt = custom_prompt or self.prompt_manager.get_prompt_template("ocr")
        ocr_cfg = load_settings().ocr
        image_input = self._prepare_image_input(image)

        req = InferenceRequest(
            request_id=f"ocr-{uuid.uuid4().hex[:8]}",
            prompt=prompt,
            images=[image_input],
            temperature=ocr_cfg.temperature,
            max_tokens=ocr_cfg.num_predict,
            reasoning_mode=ReasoningMode.DIRECT,
        )

        resp = await self.provider.infer(req)
        return resp.text.strip()

    def _prepare_image_input(self, image: str | bytes | Path) -> ImageInput:
        """Convert path or raw bytes to ImageInput with normalized mime type."""
        if isinstance(image, bytes):
            return ImageInput(image_bytes=image, mime_type="image/png")

        p = Path(image)
        if not p.exists() or not p.is_file():
            raise VisionRequestError(f"Image file not found at: {p}", details={"path": str(p)})

        ext = p.suffix.lower()
        mime = "image/png"
        if ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".webp":
            mime = "image/webp"

        return ImageInput(image_path=str(p.resolve()), mime_type=mime)
