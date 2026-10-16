"""LlamaServerProvider: communicates with isolated standalone llama-server via HTTP."""

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from answer_eval.core.errors import (
    InferenceError,
    InferenceOOMError,
    InferenceOutputValidationError,
    InferenceServerError,
    InferenceTimeoutError,
    UnsupportedCapabilityError,
)
from answer_eval.core.logging import get_logger
from answer_eval.hardware.detector import detect_gpus
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
from answer_eval.models.capabilities import resolve_reasoning_mode
from answer_eval.models.profiles import ModelCapabilities, ModelProfile
from answer_eval.runtime.profiles import RuntimeConfig

logger = get_logger("inference.llama_server")


def _encode_image_to_data_uri(img: ImageInput) -> str:
    """Encode ImageInput to data URI string."""
    raw_bytes: bytes | None = img.image_bytes
    if raw_bytes is None and img.image_path:
        p = Path(img.image_path)
        if p.exists():
            with open(p, "rb") as f:
                raw_bytes = f.read()

    if not raw_bytes:
        raise InferenceError("ImageInput has neither bytes nor valid path.")

    encoded = base64.b64encode(raw_bytes).decode("utf-8")
    return f"data:{img.mime_type};base64,{encoded}"


def _get_current_memory() -> MemorySnapshot:
    """Collect current VRAM and RAM snapshot."""
    import psutil

    vmem = psutil.virtual_memory()
    ram_used = round((vmem.total - vmem.available) / (1024**3), 2)
    ram_avail = round(vmem.available / (1024**3), 2)

    vram_used = 0.0
    vram_free = 0.0
    gpus = detect_gpus()
    if gpus:
        vram_used = gpus[0].vram_used_gb
        vram_free = gpus[0].vram_free_gb

    return MemorySnapshot(
        vram_used_gb=vram_used,
        vram_free_gb=vram_free,
        ram_used_gb=ram_used,
        ram_available_gb=ram_avail,
    )


class LlamaServerProvider(InferenceProvider):
    """Inference provider communicating with standalone llama-server."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url or "http://127.0.0.1:8090"
        self.timeout_seconds = timeout_seconds
        self.model_profile: ModelProfile | None = None
        self.runtime_config: RuntimeConfig | None = None
        self.hardware_profile: HardwareProfile | None = None
        self._client: httpx.AsyncClient | None = None

    async def initialize(
        self,
        model: ModelProfile,
        config: RuntimeConfig,
        hardware: HardwareProfile | None = None,
    ) -> None:
        """Initialize provider with model and runtime configuration."""
        self.model_profile = model
        self.runtime_config = config
        self.hardware_profile = hardware
        self.base_url = f"http://{config.host}:{config.port}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
        )
        logger.info(
            "LlamaServerProvider initialized",
            base_url=self.base_url,
            model_id=model.model_id,
        )

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
            )
        return self._client

    async def health_check(self) -> bool:
        """Check if llama-server is responding to /health."""
        client = self._ensure_client()
        try:
            resp = await client.get("/health")
            return resp.status_code == 200
        except Exception as e:
            logger.debug("LlamaServer health check failed", error=str(e))
            return False

    def get_capabilities(self) -> ModelCapabilities:
        """Return capabilities of active model profile."""
        if self.model_profile is None:
            return ModelCapabilities()
        return self.model_profile.to_capabilities()

    def get_memory_usage(self) -> MemorySnapshot:
        """Get live memory snapshot."""
        return _get_current_memory()

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Execute chat completion inference."""
        client = self._ensure_client()
        start_time = time.perf_counter()
        warnings: list[str] = []

        # Resolve reasoning mode
        effective_mode, warning = resolve_reasoning_mode(
            request.reasoning_mode.value,
            self.model_profile or ModelProfile(model_id="unknown", display_name="unknown", checkpoint_path=""),
        )
        if warning:
            warnings.append(warning)

        # Build messages payload (OpenAI Vision compatible)
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        user_content: list[dict[str, Any]] | str
        if request.images:
            if not self.get_capabilities().vision:
                raise UnsupportedCapabilityError(
                    f"Model '{self.model_profile.model_id if self.model_profile else 'unknown'}' does not support vision inputs."
                )
            user_content_parts: list[dict[str, Any]] = []
            for img in request.images:
                data_uri = _encode_image_to_data_uri(img)
                user_content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    }
                )
            user_content_parts.append({"type": "text", "text": request.prompt})
            user_content = user_content_parts
        else:
            user_content = request.prompt

        messages.append({"role": "user", "content": user_content})

        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": False,
        }

        # Structured schema/grammar if provided
        if request.json_schema:
            payload["response_format"] = {
                "type": "json_object",
                "schema": request.json_schema,
            }
        elif request.grammar:
            payload["grammar"] = request.grammar

        try:
            resp = await client.post("/v1/chat/completions", json=payload)
        except httpx.TimeoutException as e:
            raise InferenceTimeoutError(
                f"Inference request timed out after {self.timeout_seconds}s.",
                details={"request_id": request.request_id},
            ) from e
        except httpx.ConnectError as e:
            raise InferenceServerError(
                f"Cannot connect to llama-server at {self.base_url}: {e}",
                details={"request_id": request.request_id},
            ) from e
        except Exception as e:
            raise InferenceServerError(
                f"Unexpected inference communication error: {e}",
                details={"request_id": request.request_id},
            ) from e

        total_ms = round((time.perf_counter() - start_time) * 1000, 2)

        if resp.status_code != 200:
            err_text = resp.text
            if "out of memory" in err_text.lower() or "cuda oom" in err_text.lower():
                raise InferenceOOMError(
                    f"CUDA Out Of Memory during llama-server inference: {err_text}",
                    details={"request_id": request.request_id, "status_code": resp.status_code},
                )
            raise InferenceServerError(
                f"llama-server returned HTTP {resp.status_code}: {err_text}",
                details={"request_id": request.request_id, "status_code": resp.status_code},
            )

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        content_text = choice.get("message", {}).get("content", "")

        # Usage
        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        # Timings if available from llama.cpp response extensions
        tok_per_sec = None
        if usage.completion_tokens > 0 and total_ms > 0:
            tok_per_sec = round((usage.completion_tokens / (total_ms / 1000.0)), 2)

        timing = InferenceTiming(
            total_inference_ms=total_ms,
            tokens_per_second=tok_per_sec,
        )

        mem_snap = _get_current_memory()

        return InferenceResponse(
            request_id=request.request_id,
            provider="llama_server",
            model_id=self.model_profile.model_id if self.model_profile else "unknown",
            quantization=self.model_profile.quantization if self.model_profile else None,
            text=content_text,
            usage=usage,
            timing=timing,
            memory=mem_snap,
            warnings=warnings,
        )

    async def infer_structured(
        self,
        request: InferenceRequest,
        schema: type | dict[str, Any],
        max_retries: int = 2,
    ) -> InferenceResponse:
        """Execute inference with JSON schema parsing, Pydantic validation, and controlled retry."""
        # Convert schema
        pydantic_cls = None
        schema_dict: dict[str, Any]
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            pydantic_cls = schema
            schema_dict = schema.model_json_schema()
        elif isinstance(schema, dict):
            schema_dict = schema
        else:
            schema_dict = {}

        req = request.model_copy()
        req.json_schema = schema_dict

        last_error: str | None = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                # Add controlled repair instruction to prompt
                req.prompt = f"{request.prompt}\n\nNOTE: Previous attempt failed validation: {last_error}. Please ensure strictly valid JSON matching the schema."

            response = await self.infer(req)
            raw_text = response.text.strip()

            # Attempt JSON parsing (strip markdown code blocks if wrapped)
            cleaned = raw_text
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            try:
                parsed_json = json.loads(cleaned)
                if pydantic_cls:
                    # Validate through Pydantic
                    validated_obj = pydantic_cls.model_validate(parsed_json)
                    response.structured_data = validated_obj.model_dump()
                else:
                    response.structured_data = parsed_json

                return response
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)
                logger.warning(
                    "Structured JSON validation failed",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=last_error,
                )

        raise InferenceOutputValidationError(
            f"Failed to obtain valid structured JSON after {max_retries + 1} attempts: {last_error}",
            details={"request_id": request.request_id, "raw_output": response.text},
        )

    async def shutdown(self) -> None:
        """Close HTTP client session."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
