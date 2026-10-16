"""Inference request and response data structures."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ReasoningMode(StrEnum):
    """Requested model reasoning behavior."""

    DIRECT = "direct"  # Fast, direct extraction (ideal for OCR)
    NORMAL = "normal"  # Standard instruction following
    THINKING = "thinking"  # Deep reasoning (if model supports thinking)


class ImageInput(BaseModel):
    """Container for input image to vision models."""

    image_bytes: bytes | None = None
    image_path: str | None = None
    mime_type: str = "image/png"
    max_pixels: int | None = None


class InferenceRequest(BaseModel):
    """Standard model-agnostic inference request."""

    request_id: str = Field(description="Unique tracking ID for this request")
    prompt: str = Field(description="User prompt text")
    system_prompt: str | None = Field(default=None, description="System instructions")
    images: list[ImageInput] = Field(default_factory=list, description="Input images for multimodal inference")
    max_tokens: int | None = Field(
        default=None,
        description="Maximum completion tokens. None = use the provider's configured "
        "OCR generation budget (settings: ocr.num_predict).",
    )
    temperature: float = Field(default=0.1, description="Sampling temperature")
    reasoning_mode: ReasoningMode = Field(default=ReasoningMode.DIRECT, description="Requested reasoning mode")
    json_schema: dict[str, Any] | None = Field(
        default=None, description="Pydantic or JSON schema for structured output"
    )
    grammar: str | None = Field(default=None, description="GBNF grammar string for llama.cpp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Contextual tracking metadata")


class TokenUsage(BaseModel):
    """Token consumption statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class InferenceTiming(BaseModel):
    """Execution timing measurements in milliseconds."""

    time_to_first_token_ms: float | None = None
    prompt_eval_ms: float | None = None
    eval_ms: float | None = None
    total_inference_ms: float = 0.0
    tokens_per_second: float | None = None


class MemorySnapshot(BaseModel):
    """VRAM and RAM usage snapshot around an inference call."""

    vram_used_gb: float = 0.0
    vram_free_gb: float = 0.0
    ram_used_gb: float = 0.0
    ram_available_gb: float = 0.0


class InferenceResponse(BaseModel):
    """Standard model-agnostic inference response."""

    request_id: str = Field(description="Matching request tracking ID")
    provider: str = Field(description="Inference provider used (e.g. llama_server, vllm)")
    model_id: str = Field(description="Model profile identifier used")
    quantization: str | None = Field(default=None, description="Quantization of the model")
    text: str = Field(description="Raw generated text output")
    structured_data: dict[str, Any] | None = Field(default=None, description="Parsed structured JSON if requested")
    usage: TokenUsage = Field(default_factory=TokenUsage, description="Token usage metrics")
    timing: InferenceTiming = Field(default_factory=InferenceTiming, description="Latency breakdown")
    memory: MemorySnapshot | None = Field(default=None, description="Memory snapshot")
    warnings: list[str] = Field(
        default_factory=list,
        description="Any runtime warnings (e.g. downgraded thinking, fallback)",
    )
    stop_reason: str | None = Field(
        default=None,
        description="Finish/stop reason from backend (e.g. 'stop', 'length', 'load'). "
        "'length' indicates generation-limit truncation.",
    )
    thinking_disabled: bool | None = Field(
        default=None,
        description="Whether reasoning/thinking was explicitly disabled for this request (if known).",
    )
