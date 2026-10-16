"""Runtime profiles and runtime configuration data structures."""

from pydantic import BaseModel, Field


class RuntimeProfileConfig(BaseModel):
    """Template runtime profile loaded from runtime_profiles.yaml."""

    description: str = Field(description="Profile description")
    target_context: int = Field(default=8192, description="Target context size in tokens")
    target_concurrency: int = Field(default=1, description="Target concurrent request slots")
    target_batch_size: int = Field(default=512, description="Prompt batch size (n_batch)")
    max_image_pixels: int = Field(default=1048576, description="Max pixels for vision inputs (e.g. 1024x1024)")
    kv_cache_dtype: str = Field(default="f16", description="KV cache data type (f16, q8_0, q4_0)")
    prefer_full_gpu: bool = Field(default=True, description="Attempt full GPU offloading if memory permits")
    safety_margin_gb: float = Field(default=1.5, description="VRAM safety margin to reserve for activations and OS")
    gpu_layers_override: int | None = Field(default=None, description="Explicit GPU layer count override")


class RuntimeConfig(BaseModel):
    """Actual calibrated runtime configuration for the active model and hardware."""

    profile_name: str = Field(description="Name of runtime profile template")
    n_gpu_layers: int = Field(default=-1, description="GPU offload layers (-1 for all, 0 for CPU-only, N for partial)")
    n_ctx: int = Field(default=8192, description="Active context window size in tokens")
    n_batch: int = Field(default=512, description="Prompt evaluation batch size")
    n_ubatch: int = Field(default=512, description="Physical micro-batch size")
    n_threads: int = Field(default=8, description="Number of CPU worker threads (physical cores)")
    max_image_pixels: int = Field(default=1048576, description="Maximum image resolution cap in pixels")
    kv_cache_dtype: str = Field(default="f16", description="KV cache precision")
    host: str = Field(default="127.0.0.1", description="Server host (localhost only)")
    port: int = Field(default=8090, description="Server port")
    safety_margin_gb: float = Field(default=1.5, description="Reserved VRAM safety headroom")
    estimated_vram_gb: float = Field(default=0.0, description="Conservative estimated VRAM usage")
    estimated_ram_gb: float = Field(default=0.0, description="Conservative estimated RAM usage")
    is_hybrid_offload: bool = Field(default=False, description="Whether this is running in hybrid CPU/GPU mode")
    fallback_level: int = Field(default=0, description="Current fallback degradation level (0=optimal)")
