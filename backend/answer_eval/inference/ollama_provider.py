"""OllamaProvider: communicates with Ollama via OpenAI-compatible /v1 API."""

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from answer_eval.core.config import load_settings
from answer_eval.core.errors import (
    ConfigurationError,
    InferenceError,
    InferenceOutputValidationError,
    InferenceTimeoutError,
    ModelNotFoundError,
    OllamaNotAvailableError,
    VisionRequestError,
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
    ReasoningMode,
    TokenUsage,
)
from answer_eval.models.profiles import ModelCapabilities, ModelProfile
from answer_eval.runtime.profiles import RuntimeConfig

logger = get_logger("inference.ollama")


def _repair_json_invalid_escapes(text: str) -> str:
    """
    Fix invalid backslash escapes inside JSON string literals.

    Small models frequently emit hand-written escapes like ``\\d`` (regex),
    ``\\c`` (fractions) or ``\\0`` inside answers. ``json.loads`` rejects those
    with ``Invalid \\\\escape`` and a repair re-inference is wasted GPU time
    (often reproducing the same output verbatim at temperature 0). Instead,
    rewrite any ``\\x`` where x is not a valid JSON escape char into ``\\\\x``.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        # inside a string literal
        if ch == "\\":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt and nxt not in '"\\/bfnrtu':
                out.append("\\\\")  # escape the stray backslash
                i += 1
                continue
            out.append(ch)
            if nxt:
                out.append(nxt)
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            in_string = False
        out.append(ch)
        i += 1
    return "".join(out)


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


def _load_image_raw(img: ImageInput) -> tuple[bytes, str]:
    """Load raw image bytes and normalized mime type from an ImageInput."""
    raw_bytes: bytes | None = img.image_bytes
    if raw_bytes is None and img.image_path:
        p = Path(img.image_path)
        if p.exists() and p.is_file():
            with open(p, "rb") as f:
                raw_bytes = f.read()

    if not raw_bytes:
        raise VisionRequestError(
            "ImageInput has neither valid bytes nor an accessible file path.",
            details={"image_path": img.image_path},
        )

    # Normalize mime type
    mime = img.mime_type or "image/png"
    if img.image_path:
        ext = Path(img.image_path).suffix.lower()
        if ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".webp":
            mime = "image/webp"
        elif ext == ".png":
            mime = "image/png"

    return raw_bytes, mime


def _encode_image_to_data_uri(img: ImageInput) -> str:
    """Encode ImageInput to data URI string for OpenAI-compatible vision payload."""
    raw_bytes, mime = _load_image_raw(img)
    encoded = base64.b64encode(raw_bytes).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


class OllamaProvider(InferenceProvider):
    """
    Inference provider communicating with Ollama via standard OpenAI-compatible API.
    Supports vision, strict OCR, structured JSON output, configurable timeouts and retries.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str | None = None,
        api_key: str = "ollama",
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        settings = load_settings()
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or settings.ollama.base_url).rstrip("/")
        self.model_name = model_name or os.getenv("VISION_MODEL") or settings.ollama.model
        # Centralized OCR inference policy (model / num_ctx / num_predict / temperature).
        self._ocr_cfg = settings.ocr

        # Native (non OpenAI-compatible) API root, used for explicit think=False control.
        native_root = self.base_url
        if native_root.endswith("/v1"):
            native_root = native_root[: -len("/v1")]
        self._native_base_url = native_root.rstrip("/")
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY") or settings.ollama.api_key
        self.timeout_seconds = float(
            os.getenv("OLLAMA_TIMEOUT", str(timeout_seconds or settings.ollama.timeout_seconds))
        )
        self.max_retries = int(os.getenv("OLLAMA_MAX_RETRIES", str(max_retries or settings.ollama.max_retries)))
        # How long Ollama keeps the model in VRAM between calls. The default
        # (5m) unloads the 3GB+ vision model during short idle gaps and every
        # reload costs 15-20s of wall time mid-parse.
        self.keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

        self.model_profile: ModelProfile | None = None
        self.runtime_config: RuntimeConfig | None = None
        self.hardware_profile: HardwareProfile | None = None
        self._client: httpx.AsyncClient | None = None
        self._client_loop: Any | None = None

        self._log_ocr_config(level="debug")

    def _resolve_ocr_model(self) -> str:
        """
        Effective model for OCR/DIRECT-mode requests.

        An empty ocr.model setting means "inherit" the global Ollama model
        (VISION_MODEL env var / settings.ollama.model).
        """
        resolved = self._ocr_cfg.model or self.model_name
        if not resolved or not resolved.strip():
            raise ConfigurationError(
                "No Ollama model configured for OCR inference. "
                "Set VISION_MODEL or OLLAMA_OCR_MODEL to a non-empty value."
            )
        return resolved

    def _log_ocr_config(self, level: str = "info") -> None:
        """Log the effective OCR inference configuration (no secrets)."""
        getattr(logger, level)(
            "[OCR CONFIG]",
            provider="ollama",
            model=self._ocr_cfg.model or self.model_name,
            base_url=self.base_url,
            num_ctx=self._ocr_cfg.num_ctx,
            num_predict=self._ocr_cfg.num_predict,
            temperature=self._ocr_cfg.temperature,
            thinking_enabled=self._ocr_cfg.thinking_enabled,
            timeout_seconds=self.timeout_seconds,
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Create or reuse httpx.AsyncClient.

        An AsyncClient is bound to the event loop that created it. The grading
        worker runs the graph via asyncio.run() in a worker thread, so a fresh
        loop exists for every call — a client built on an earlier (closed) loop
        fails with 'Event loop is closed'. Recreate the client whenever the
        running loop differs from the one it was created on.
        """
        import asyncio

        stale_loop = False
        if self._client is not None and not self._client.is_closed:
            try:
                current = asyncio.get_running_loop()
                stale_loop = current is not self._client_loop
            except RuntimeError:
                stale_loop = False
        if self._client is None or self._client.is_closed or stale_loop:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
            )
            try:
                self._client_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._client_loop = None
        return self._client

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
        if model.display_name and ":" in model.model_id:
            self.model_name = model.model_id

        logger.info(
            "Initialized OllamaProvider",
            base_url=self.base_url,
            model_name=self.model_name,
            timeout_seconds=self.timeout_seconds,
        )
        self._log_ocr_config(level="info")

    async def health_check(self) -> bool:
        """Verify Ollama is reachable and ready."""
        status = await self.check_detailed_health()
        return status.get("available", False)

    async def check_detailed_health(self) -> dict[str, Any]:
        """
        Perform a comprehensive health and model availability check.
        Returns a structured result dict.
        """
        client = self._get_client()
        result: dict[str, Any] = {
            "available": False,
            "provider": "ollama",
            "model": self.model_name,
            "base_url": self.base_url,
            "installed_models": [],
            "error": None,
            "help_message": None,
        }

        try:
            # Query /models endpoint (OpenAI compatible)
            resp = await client.get("/models")
            if resp.status_code == 200:
                data = resp.json()
                models_list = [m.get("id", "") for m in data.get("data", [])]
                result["installed_models"] = models_list

                # Check if configured model exists (exact match or latest alias)
                matched = any(
                    self.model_name == m or self.model_name == f"{m}:latest" or m == f"{self.model_name}:latest"
                    for m in models_list
                )

                if matched or not models_list:
                    # If models list returned the model or if list is empty (direct forward)
                    result["available"] = True
                else:
                    result["available"] = False
                    result["error"] = f"Configured model '{self.model_name}' is not installed in Ollama."
                    result["help_message"] = f"Install it using: ollama pull {self.model_name}"
            else:
                result["error"] = f"Ollama returned HTTP {resp.status_code}: {resp.text}"
                result["help_message"] = "Ensure Ollama is running using: ollama serve"

        except httpx.ConnectError:
            result["error"] = f"Ollama is not reachable at {self.base_url}."
            result["help_message"] = "Ollama is not running. Start it using: ollama serve"
        except httpx.TimeoutException:
            result["error"] = f"Connection to Ollama at {self.base_url} timed out."
            result["help_message"] = "Check server load or verify base_url."
        except Exception as e:
            result["error"] = f"Unexpected health check failure: {e}"

        return result

    async def verify_model_available(self) -> None:
        """Verify model presence, raising clean descriptive exceptions if missing."""
        health = await self.check_detailed_health()
        if not health["available"]:
            if (
                "not running" in (health.get("help_message") or "").lower()
                or "not reachable" in (health.get("error") or "").lower()
            ):
                raise OllamaNotAvailableError(
                    f"Ollama is not running at {self.base_url}.\nStart it using: ollama serve",
                    details=health,
                )
            raise ModelNotFoundError(
                f"Configured vision model '{self.model_name}' was not found in Ollama.\nInstall it using: ollama pull {self.model_name}",
                details=health,
            )

    def get_capabilities(self) -> ModelCapabilities:
        """Return capabilities for active Ollama model."""
        if self.model_profile:
            return self.model_profile.to_capabilities()
        return ModelCapabilities(
            vision=True,
            structured_output=True,
            thinking=False,
            max_context=8192,
        )

    def get_memory_usage(self) -> MemorySnapshot:
        """Return memory utilization snapshot."""
        return _get_current_memory()

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute text or vision inference request against Ollama.

        ReasoningMode.DIRECT (used for OCR / deterministic extraction) routes to the
        native /api/chat endpoint with ``think: false`` so reasoning models such as
        qwen3-vl do not spend the generation budget on internal thinking.
        All other modes use the standard OpenAI-compatible /v1/chat/completions API.
        Includes automatic transient retries and timing/memory metadata.
        """
        client = self._get_client()
        t_start = time.perf_counter()

        direct_mode = request.reasoning_mode == ReasoningMode.DIRECT
        if direct_mode:
            url = f"{self._native_base_url}/api/chat"
            payload = self._build_native_payload(request)
        else:
            url = "/chat/completions"
            messages = self._build_chat_messages(request)
            payload = {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": request.max_tokens or self._ocr_cfg.num_predict,
                "temperature": request.temperature,
                "stream": False,
                "options": {
                    "num_ctx": self._ocr_cfg.num_ctx,
                    "num_predict": request.max_tokens or self._ocr_cfg.num_predict,
                    "temperature": request.temperature,
                },
            }
        model_to_use = payload["model"]

        # Safe logging without private image data
        image_count = len(request.images)
        logger.info(
            "Executing Ollama inference request",
            request_id=request.request_id,
            model=model_to_use,
            images_count=image_count,
            prompt_preview=request.prompt[:60] if request.prompt else "",
            endpoint=url,
            thinking_disabled=direct_mode,
            num_ctx=payload.get("options", {}).get("num_ctx"),
            num_predict=payload.get("options", {}).get("num_predict"),
            temperature=payload.get("options", {}).get("temperature"),
        )

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                resp = await client.post(url, json=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    t_end = time.perf_counter()
                    dur_ms = round((t_end - t_start) * 1000, 2)

                    if direct_mode:
                        # Native /api/chat response format
                        message = data.get("message") or {}
                        text_content = message.get("content") or ""
                        prompt_tokens = int(data.get("prompt_eval_count") or 0)
                        completion_tokens = int(data.get("eval_count") or 0)
                        stop_reason = data.get("done_reason")
                        thinking_disabled_flag: bool | None = True
                    else:
                        choices = data.get("choices", [])
                        if not choices:
                            raise InferenceError("Ollama response contained no completion choices.")

                        text_content = choices[0].get("message", {}).get("content", "")
                        usage_data = data.get("usage", {})
                        prompt_tokens = usage_data.get("prompt_tokens", 0)
                        completion_tokens = usage_data.get("completion_tokens", 0)
                        stop_reason = choices[0].get("finish_reason")
                        thinking_disabled_flag = None

                    total_tokens = prompt_tokens + completion_tokens
                    tps = round(completion_tokens / (dur_ms / 1000), 2) if dur_ms > 0 else 0.0

                    logger.info(
                        "Ollama inference completed",
                        request_id=request.request_id,
                        duration_ms=dur_ms,
                        completion_tokens=completion_tokens,
                        tokens_per_second=tps,
                        stop_reason=stop_reason,
                        thinking_disabled=thinking_disabled_flag,
                    )

                    return InferenceResponse(
                        request_id=request.request_id,
                        provider="ollama",
                        model_id=model_to_use,
                        quantization=self.model_profile.quantization if self.model_profile else "auto",
                        text=text_content,
                        usage=TokenUsage(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens,
                        ),
                        timing=InferenceTiming(
                            total_inference_ms=dur_ms,
                            tokens_per_second=tps,
                        ),
                        memory=self.get_memory_usage(),
                        stop_reason=stop_reason,
                        thinking_disabled=thinking_disabled_flag,
                    )

                elif resp.status_code == 404:
                    raise ModelNotFoundError(
                        f"Model '{model_to_use}' not found on Ollama server. Pull it using: ollama pull {model_to_use}",
                        details={"status_code": 404, "response": resp.text},
                    )
                elif resp.status_code in (500, 502, 503, 504):
                    logger.warning(
                        "Transient Ollama server error",
                        attempt=attempt,
                        status_code=resp.status_code,
                        response=resp.text,
                    )
                    last_err = InferenceError(f"Ollama server error HTTP {resp.status_code}: {resp.text}")
                else:
                    raise InferenceError(
                        f"Ollama request failed with HTTP {resp.status_code}: {resp.text}",
                        details={"status_code": resp.status_code},
                    )

            except httpx.ConnectError as e:
                logger.warning("Connection error reaching Ollama", attempt=attempt, error=str(e))
                last_err = OllamaNotAvailableError(
                    f"Ollama server is not reachable at {self.base_url}. Start it with: ollama serve",
                    details={"base_url": self.base_url},
                )
            except httpx.TimeoutException:
                logger.warning("Ollama request timed out", attempt=attempt, timeout=self.timeout_seconds)
                last_err = InferenceTimeoutError(
                    f"Ollama inference timed out after {self.timeout_seconds}s.",
                    details={"timeout_seconds": self.timeout_seconds},
                )
            except Exception as e:
                if isinstance(e, (ModelNotFoundError, OllamaNotAvailableError, InferenceError)):
                    raise
                logger.warning("Unexpected error during Ollama inference", attempt=attempt, error=str(e))
                last_err = e

            if attempt <= self.max_retries:
                backoff = 1.0 * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

        if last_err:
            raise last_err
        raise InferenceError("Ollama inference failed after maximum retries.")

    def _salvage_structured(self, cleaned: str, schema: type | dict[str, Any]):
        """Recover structured data from a failed response without re-inferring.

        Scans every top-level ``{...}`` object in the raw text and returns the
        first one that validates against *schema*. This transparently fixes the
        two common small-model failure shapes:
          - schema echo: the model emits the JSON-schema JSON, then the answer
          - "Extra data": multiple concatenated JSON objects
        Returns None when nothing validates (caller falls back to repair).
        """
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            return None
        decoder = json.JSONDecoder()
        text = cleaned.strip()
        index = 0
        while 0 <= index < len(text):
            brace = text.find("{", index)
            if brace == -1:
                return None
            try:
                obj, end = decoder.raw_decode(text[brace:])
            except json.JSONDecodeError:
                index = brace + 1
                continue
            index = brace + max(end, 1)
            if not isinstance(obj, dict):
                continue
            # Skip obvious schema echoes (the model repeating the schema JSON).
            if "$defs" in obj or ("properties" in obj and "questions" not in obj):
                continue
            try:
                return schema.model_validate(obj).model_dump()
            except ValidationError:
                continue
        return None

    async def infer_structured(
        self,
        request: InferenceRequest,
        schema: type | dict[str, Any],
        max_retries: int = 2,
    ) -> InferenceResponse:
        """
        Execute inference and validate JSON output schema with controlled repair retries.

        Attempt 0: Full schema-constrained prompt, try to parse output.
        Attempt 1+: Feed validation error back to the model with explicit repair instructions.

        Handles:
          - Raw JSON responses
          - Markdown-fenced responses (```json ... ```)
          - JSON embedded inside surrounding prose (extracted via brace matching)
        """
        req_copy = request.model_copy(deep=True)
        schema_desc = (
            schema
            if isinstance(schema, dict)
            else schema.model_json_schema()
            if hasattr(schema, "model_json_schema")
            else str(schema)
        )

        # Build initial prompt with schema instruction appended
        schema_instruction = (
            f"\n\nYou MUST respond with ONLY a valid JSON object matching this schema "
            f"(no markdown fences, no explanation):\n{json.dumps(schema_desc, indent=2)}"
        )
        req_copy.prompt = request.prompt + schema_instruction

        last_error_text = ""
        last_raw: str = ""

        for attempt in range(max_retries + 1):
            if attempt > 0:
                # Repair prompt: show model exactly what went wrong
                repair_note = (
                    f"\n\nYour previous response did not contain valid JSON.\n"
                    f"Validation error: {last_error_text[:300]}\n\n"
                    f"Rules:\n"
                    f"- Return ONLY the JSON object.\n"
                    f"- No markdown code fences (no ```json).\n"
                    f"- No explanation before or after the JSON.\n"
                    f"- Must match this schema exactly:\n"
                    f"{json.dumps(schema_desc, indent=2)}"
                )
                req_copy.prompt = request.prompt + repair_note
                logger.info(
                    "Structured JSON repair retry",
                    attempt=attempt,
                    max_retries=max_retries,
                    validation_error=last_error_text[:200],
                    request_id=request.request_id,
                )

            resp = await self.infer(req_copy)
            raw = resp.text.strip()
            last_raw = raw

            cleaned = self._extract_json_from_response(raw)

            try:
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError as escape_err:
                    if "Invalid" in str(escape_err) and "escape" in str(escape_err):
                        repaired = _repair_json_invalid_escapes(cleaned)
                        data = json.loads(repaired)
                        logger.info(
                            "Structured JSON invalid-escape repaired locally",
                            request_id=request.request_id,
                        )
                    else:
                        raise
                if isinstance(schema, type) and issubclass(schema, BaseModel):
                    validated = schema.model_validate(data)
                    resp.structured_data = validated.model_dump()
                else:
                    resp.structured_data = data
                return resp
            except (json.JSONDecodeError, ValidationError) as e:
                # Cheap local recovery first: small models commonly emit the
                # JSON *schema* itself followed by the real object, or several
                # concatenated objects ("Extra data"). A repair retry costs a
                # full extra inference (40-130s); scanning the objects we
                # already have costs milliseconds.
                salvaged = self._salvage_structured(cleaned, schema)
                if salvaged is not None:
                    logger.info(
                        "Structured JSON salvaged without repair retry",
                        request_id=request.request_id,
                    )
                    resp.structured_data = salvaged
                    return resp
                last_error_text = str(e)
                logger.warning(
                    "Structured JSON validation failed",
                    attempt=attempt,
                    raw_response_length=len(raw),
                    raw_preview=raw[:120],
                    validation_error=last_error_text[:200],
                    request_id=request.request_id,
                )

        raise InferenceOutputValidationError(
            f"Failed to obtain valid structured JSON from Ollama after {max_retries} retries.",
            details={
                "last_error": last_error_text,
                "raw_response_length": len(last_raw),
                "raw_response_preview": last_raw[:300],
                # Full text so callers with domain-specific salvage logic
                # (e.g. the answer-key parser's truncated-JSON recovery) can
                # still extract value without another inference round-trip.
                "raw_response": last_raw,
            },
        )

    def _extract_json_from_response(self, text: str) -> str:
        """
        Extract clean JSON string from raw model response.
        Handles markdown fences, leading/trailing whitespace, and embedded JSON in prose.
        """
        cleaned = text.strip()

        # 1. Strip markdown fences if present
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # 2. If it already parses or starts with { / [, return it
        if cleaned.startswith("{") or cleaned.startswith("["):
            return cleaned

        # 3. Search for first { and matching last }
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return cleaned[first_brace : last_brace + 1]

        # 4. Search for first [ and matching last ]
        first_bracket = cleaned.find("[")
        last_bracket = cleaned.rfind("]")
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            return cleaned[first_bracket : last_bracket + 1]

        return cleaned

    def _build_native_payload(self, request: InferenceRequest) -> dict[str, Any]:
        """
        Construct native /api/chat payload with thinking explicitly disabled.

        Two complementary mechanisms are used:
        1. ``think: false`` — honored by Ollama >= 0.9 for models whose chat
           template supports a thinking toggle.
        2. An assistant message pre-filled with an already-closed empty
           ``<think></think>`` block — this works even when the runtime ignores
           ``think`` (verified on Ollama 0.32.15 + qwen3-vl:4b, whose bundled
           template has no thinking toggle). Generation resumes *after* the
           closed block, so no reasoning tokens are produced.
        """
        message: dict[str, Any] = {"role": "user", "content": request.prompt}
        if request.system_prompt:
            message["content"] = f"{request.system_prompt}\n\n{request.prompt}"

        if request.images:
            message["images"] = [
                base64.b64encode(raw).decode("utf-8")
                for raw, _mime in (_load_image_raw(img) for img in request.images)
            ]

        messages: list[dict[str, Any]] = [message]
        messages.append({"role": "assistant", "content": "<think>\n\n</think>\n\n"})

        return {
            "model": self._resolve_ocr_model(),
            "messages": messages,
            "think": False,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "num_ctx": self._ocr_cfg.num_ctx,
                "num_predict": request.max_tokens or self._ocr_cfg.num_predict,
                "temperature": request.temperature,
            },
        }

    def _build_chat_messages(self, request: InferenceRequest) -> list[dict[str, Any]]:
        """Construct OpenAI-compatible chat messages array for vision/text."""
        if not request.images:
            return [{"role": "user", "content": request.prompt}]

        content_parts: list[dict[str, Any]] = []

        # Add image parts
        for img in request.images:
            data_uri = _encode_image_to_data_uri(img)
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_uri},
                }
            )

        # Add text prompt
        content_parts.append(
            {
                "type": "text",
                "text": request.prompt,
            }
        )

        return [{"role": "user", "content": content_parts}]

    async def shutdown(self) -> None:
        """Close HTTP client connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("OllamaProvider client connection closed.")
