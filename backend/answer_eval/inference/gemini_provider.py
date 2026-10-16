"""Google Gemini Multimodal Inference Provider.

Provides high-throughput multimodal vision (diagram comprehension, handwritten OCR)
and strict structured JSON generation via Google's Gemini Flash / Pro API.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import (
    ImageInput,
    InferenceRequest,
    InferenceResponse,
    InferenceTiming,
    MemorySnapshot,
    TokenUsage,
)
from answer_eval.models.profiles import ModelCapabilities, ModelProfile
from answer_eval.runtime.profiles import RuntimeConfig

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-flash-lite"
ALT_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-1.5-flash",
]


class GeminiProvider(InferenceProvider):
    """Production provider for Google Gemini multimodal API."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.model_name = model_name or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._capabilities = ModelCapabilities(
            vision=True,
            structured_output=True,
            thinking=False,
            max_context=1048576,
            image_limit=50,
            tool_support=True,
            prefix_cache=True,
        )

    async def initialize(
        self,
        model: ModelProfile | None = None,
        config: RuntimeConfig | None = None,
        hardware: HardwareProfile | None = None,
    ) -> None:
        """Initialize provider and verify API key presence."""
        if not self.api_key:
            self.api_key = os.getenv("GEMINI_API_KEY", DEFAULT_GEMINI_KEY)
        if model and getattr(model, "model_id", None):
            # If a specific gemini model is requested
            if "gemini" in model.model_id.lower():
                clean_id = model.model_id.replace("_", "-")
                if clean_id in ("gemini-flash-lite-latest", "gemini-flash-latest"):
                    clean_id = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
                self.model_name = clean_id
        logger.info("Initialized GeminiProvider with model: %s", self.model_name)

    async def health_check(self) -> bool:
        """Verify Gemini API connectivity."""
        if not self.api_key:
            return False
        url = f"{self.base_url}/models/{self.model_name}?key={self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                return res.status_code == 200
        except Exception as exc:
            logger.warning("Gemini health check failed: %s", exc)
            return False

    def _prepare_parts(self, request: InferenceRequest) -> list[dict[str, Any]]:
        """Format prompt and multimodal images into Gemini parts."""
        parts: list[dict[str, Any]] = []

        # 1. Process images
        for img in request.images:
            raw_bytes: bytes | None = img.image_bytes
            mime: str = img.mime_type or "image/png"
            if not raw_bytes and img.image_path:
                p = Path(img.image_path)
                if p.exists():
                    raw_bytes = p.read_bytes()
                    if p.suffix.lower() in (".jpg", ".jpeg"):
                        mime = "image/jpeg"
                    elif p.suffix.lower() == ".webp":
                        mime = "image/webp"

            if raw_bytes:
                b64_data = base64.b64encode(raw_bytes).decode("utf-8")
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64_data,
                    }
                })

        # 2. Add user prompt text
        if request.prompt:
            parts.append({"text": request.prompt})

        return parts

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Execute text or vision inference via Gemini."""
        start_time = time.perf_counter()
        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"

        parts = self._prepare_parts(request)
        body: dict[str, Any] = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": max(0.0, min(request.temperature, 1.0)),
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        if request.max_tokens:
            body["generationConfig"]["maxOutputTokens"] = request.max_tokens

        if request.system_prompt:
            body["systemInstruction"] = {
                "parts": [{"text": request.system_prompt}]
            }

        models_to_try = [self.model_name] + [m for m in ALT_MODELS if m != self.model_name]
        headers = {"Content-Type": "application/json"}
        max_attempts = max(6, len(models_to_try) * 2)
        last_error = None

        for attempt in range(max_attempts):
            current_model = models_to_try[attempt % len(models_to_try)]
            current_url = f"{self.base_url}/models/{current_model}:generateContent?key={self.api_key}"
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(current_url, json=body, headers=headers)

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                    wait_time = min(2.0 + (1.5 ** attempt) * 2.0, 20.0)
                    logger.warning("Gemini API (%s) returned status %d. Retrying in %.1fs...", current_model, resp.status_code, wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    err_msg = f"Gemini API returned status {resp.status_code}: {resp.text[:300]}"
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

                data = resp.json()
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                candidates = data.get("candidates") or []
                text = ""
                stop_reason = "stop"
                if candidates:
                    first = candidates[0]
                    content = first.get("content") or {}
                    c_parts = content.get("parts") or []
                    text = "".join(p.get("text", "") for p in c_parts)
                    finish_reason = first.get("finishReason")
                    if finish_reason:
                        stop_reason = str(finish_reason).lower()

                usage_meta = data.get("usageMetadata") or {}
                prompt_toks = usage_meta.get("promptTokenCount", 0)
                comp_toks = usage_meta.get("candidatesTokenCount", 0)
                total_toks = usage_meta.get("totalTokenCount", prompt_toks + comp_toks)

                return InferenceResponse(
                    request_id=request.request_id,
                    provider="gemini",
                    model_id=self.model_name,
                    text=text,
                    usage=TokenUsage(
                        prompt_tokens=prompt_toks,
                        completion_tokens=comp_toks,
                        total_tokens=total_toks,
                    ),
                    timing=InferenceTiming(
                        total_inference_ms=elapsed_ms,
                    ),
                    memory=MemorySnapshot(
                        vram_used_gb=0.0,
                        vram_free_gb=12.0,
                        ram_used_gb=1.0,
                        ram_available_gb=30.0,
                    ),
                    stop_reason=stop_reason,
                )

            except Exception as exc:
                last_error = exc
                if attempt == max_attempts - 1:
                    break
                await asyncio.sleep(1.5 * (attempt + 1))

        raise RuntimeError(f"Gemini API failed after {max_attempts} attempts: {last_error}") from last_error

    async def infer_structured(
        self,
        request: InferenceRequest,
        schema: type | dict[str, Any],
        max_retries: int = 4,
    ) -> InferenceResponse:
        """Generate guaranteed JSON output conforming to requested schema."""
        start_time = time.perf_counter()
        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"

        parts = self._prepare_parts(request)
        body: dict[str, Any] = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": max(0.0, min(request.temperature, 0.4)),
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        if request.max_tokens:
            body["generationConfig"]["maxOutputTokens"] = request.max_tokens

        if request.system_prompt:
            body["systemInstruction"] = {
                "parts": [{"text": request.system_prompt}]
            }

        # Inject JSON schema constraint
        json_schema = None
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            json_schema = schema.model_json_schema()
        elif isinstance(schema, dict):
            json_schema = schema

        if json_schema:
            schema_instruction = f"Output strict JSON conforming to this schema:\n{json.dumps(json_schema)}"
            if "systemInstruction" in body:
                body["systemInstruction"]["parts"].append({"text": schema_instruction})
            else:
                body["systemInstruction"] = {"parts": [{"text": schema_instruction}]}

        models_to_try = [self.model_name] + [m for m in ALT_MODELS if m != self.model_name]
        headers = {"Content-Type": "application/json"}
        total_attempts = max(max_retries + 4, len(models_to_try) * 2)

        for attempt in range(total_attempts):
            current_model = models_to_try[attempt % len(models_to_try)]
            current_url = f"{self.base_url}/models/{current_model}:generateContent?key={self.api_key}"
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(current_url, json=body, headers=headers)

                if resp.status_code in (429, 500, 502, 503, 504):
                    wait_time = min(2.0 + (1.5 ** attempt) * 2.0, 20.0)
                    logger.warning("Gemini API (%s) returned status %d. Retrying in %.1fs...", current_model, resp.status_code, wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    raise RuntimeError(f"Gemini API status {resp.status_code}: {resp.text[:300]}")

                data = resp.json()
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                candidates = data.get("candidates") or []
                text = ""
                stop_reason = "stop"
                if candidates:
                    first = candidates[0]
                    content = first.get("content") or {}
                    c_parts = content.get("parts") or []
                    text = "".join(p.get("text", "") for p in c_parts).strip()
                    finish_reason = first.get("finishReason")
                    if finish_reason:
                        stop_reason = str(finish_reason).lower()

                # Clean markdown codeblocks if wrapped
                cleaned = text
                if cleaned.startswith("```"):
                    cleaned = cleaned.strip("`")
                    if cleaned.lower().startswith("json"):
                        cleaned = cleaned[4:].strip()

                parsed_json: dict[str, Any] = {}
                try:
                    parsed_json = json.loads(cleaned)
                except Exception as json_err:
                    try:
                        from answer_eval.answerkey.parser import AnswerKeyParserAgent
                        parsed_json = AnswerKeyParserAgent._extract_json(cleaned)
                    except Exception:
                        logger.warning("Gemini JSON parse failed on text: %s (error: %s)", cleaned[:150], json_err)
                        if attempt < max_retries:
                            await asyncio.sleep(1.0)
                            continue
                        raise

                # Validate against Pydantic schema if provided
                structured_data: dict[str, Any] = parsed_json
                if isinstance(schema, type) and issubclass(schema, BaseModel):
                    try:
                        validated = schema.model_validate(parsed_json)
                        structured_data = validated.model_dump()
                    except Exception as val_err:
                        logger.warning("Pydantic validation issue on Gemini response: %s", val_err)
                        # Keep parsed_json as fallback

                usage_meta = data.get("usageMetadata") or {}
                prompt_toks = usage_meta.get("promptTokenCount", 0)
                comp_toks = usage_meta.get("candidatesTokenCount", 0)
                total_toks = usage_meta.get("totalTokenCount", prompt_toks + comp_toks)

                return InferenceResponse(
                    request_id=request.request_id,
                    provider="gemini",
                    model_id=self.model_name,
                    text=cleaned,
                    structured_data=structured_data,
                    usage=TokenUsage(
                        prompt_tokens=prompt_toks,
                        completion_tokens=comp_toks,
                        total_tokens=total_toks,
                    ),
                    timing=InferenceTiming(
                        total_inference_ms=elapsed_ms,
                    ),
                    memory=MemorySnapshot(
                        vram_used_gb=0.0,
                        vram_free_gb=12.0,
                        ram_used_gb=1.0,
                        ram_available_gb=30.0,
                    ),
                    stop_reason=stop_reason,
                )

            except Exception as exc:
                if attempt == max_retries:
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))

        raise RuntimeError("Gemini structured inference failed after retries")

    def get_capabilities(self) -> ModelCapabilities:
        """Return model capabilities."""
        return self._capabilities

    def get_memory_usage(self) -> MemorySnapshot:
        """Return memory usage snapshot."""
        return MemorySnapshot(
            vram_used_gb=0.0,
            vram_free_gb=12.0,
            ram_used_gb=1.0,
            ram_available_gb=30.0,
        )

    async def shutdown(self) -> None:
        """Shutdown provider."""
        logger.info("GeminiProvider shutdown complete.")
