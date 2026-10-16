"""Model profile and capability data structures."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class ProviderType(StrEnum):
    """Supported inference provider types."""

    GEMINI = "gemini"
    OLLAMA = "ollama"
    LLAMA_SERVER = "llama_server"
    VLLM = "vllm"
    LOCAL_TRANSFORMERS = "local_transformers"


class ModelCapabilities(BaseModel):
    """Detailed model capability declarations."""

    vision: bool = Field(default=True, description="Supports multimodal image inputs")
    structured_output: bool = Field(default=True, description="Supports constrained JSON output")
    thinking: bool = Field(default=False, description="Supports internal reasoning mode")
    max_context: int = Field(default=8192, description="Maximum supported context size in tokens")
    image_limit: int = Field(default=5, description="Maximum images per single prompt")
    tool_support: bool = Field(default=False, description="Supports tool/function calling")
    logprobs: bool = Field(default=False, description="Supports token log probabilities")
    prefix_cache: bool = Field(default=True, description="Supports prompt prefix caching")


class ModelProfile(BaseModel):
    """Configuration-driven model profile definition."""

    model_id: str = Field(description="Unique profile identifier (e.g. qwen3_vl_4b)")
    display_name: str = Field(description="Human readable name")
    family: str = Field(default="qwen_vl", description="Model family architecture")
    size_class: str = Field(default="4b", description="Parameter size class (e.g. 4b, 30b_moe, large)")
    provider_type: ProviderType = Field(default=ProviderType.OLLAMA, description="Inference provider")
    quantization: str | None = Field(default=None, description="Quantization format (e.g. Q8_0, Q4_K_M, bf16)")
    checkpoint_path: str | None = Field(default=None, description="Local path to GGUF model file or HF model ID")
    mmproj_path: str | None = Field(default=None, description="Path to multimodal projector GGUF")
    context_size: int = Field(default=8192, description="Configured context size in tokens")
    max_output_tokens: int = Field(default=2048, description="Maximum output tokens per generation")
    supports_vision: bool = Field(default=True, description="Whether this model profile supports vision")
    supports_structured_output: bool = Field(
        default=True, description="Whether this model profile supports structured JSON"
    )
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    enabled: bool = Field(default=True, description="Whether this profile is currently enabled")
    runtime_profile_hint: str = Field(default="fast_local", description="Suggested runtime profile")
    endpoint: str | None = Field(
        default=None, description="Remote API endpoint if provider is remote (e.g. vLLM or Ollama)"
    )
    notes: str | None = Field(default=None, description="Human notes regarding this profile")

    def to_capabilities(self) -> ModelCapabilities:
        """Derive ModelCapabilities from profile."""
        return ModelCapabilities(
            vision=self.supports_vision,
            structured_output=self.supports_structured_output,
            thinking=self.supports_thinking,
            max_context=self.context_size,
        )

    def resolve_paths(self, workspace_root: Path) -> tuple[Path | None, Path | None]:
        """Resolve checkpoint and mmproj paths relative to workspace root if present."""
        ckpt = None
        if self.checkpoint_path:
            p = Path(self.checkpoint_path)
            ckpt = p if p.is_absolute() else workspace_root / p

        mmproj = None
        if self.mmproj_path:
            p_mm = Path(self.mmproj_path)
            mmproj = p_mm if p_mm.is_absolute() else workspace_root / p_mm

        return ckpt, mmproj
