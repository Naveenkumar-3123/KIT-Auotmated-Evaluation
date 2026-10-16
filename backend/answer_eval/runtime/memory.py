"""Conservative memory estimation, GPU offload calculation, and known-good cache."""

import json
from pathlib import Path
from typing import Any

from answer_eval.core.hashing import calculate_dict_hash
from answer_eval.core.logging import get_logger
from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.models.profiles import ModelProfile
from answer_eval.runtime.profiles import RuntimeConfig

logger = get_logger("runtime.memory")


def estimate_gguf_file_size_gb(file_path: Path | str | None) -> float:
    """Get exact size of GGUF file on disk in GB if file exists, else return conservative fallback."""
    if not file_path:
        return 0.0
    p = Path(file_path)
    if p.exists() and p.is_file():
        return round(p.stat().st_size / (1024**3), 2)
    return 0.0


def estimate_model_weights_gb(model: ModelProfile, base_dir: Path) -> tuple[float, float]:
    """
    Estimate base model GGUF size and mmproj GGUF size in GB.
    If files exist on disk, uses actual file sizes; otherwise uses size_class heuristic.
    """
    ckpt_path, mmproj_path = model.resolve_paths(base_dir)

    # 1. Base checkpoint size
    ckpt_size = estimate_gguf_file_size_gb(ckpt_path)
    if ckpt_size == 0.0:
        # Fallback heuristic based on size_class & quantization
        size_heuristic = {
            ("4b", "Q8_0"): 4.4,
            ("4b", "Q4_K_M"): 2.6,
            ("4b", "Q5_K_M"): 3.0,
            ("8b", "Q4_K_M"): 5.2,
            ("30b_moe", "Q4_K_M"): 17.5,
            ("large", "Q4_K_M"): 18.0,
        }
        ckpt_size = size_heuristic.get((model.size_class, model.quantization or ""), 4.5)

    # 2. Multimodal projector size
    mmproj_size = estimate_gguf_file_size_gb(mmproj_path)
    if mmproj_size == 0.0 and model.supports_vision:
        mmproj_size = 0.8  # Standard SigLIP2 / Qwen3-VL projector size

    return ckpt_size, mmproj_size


def estimate_kv_cache_gb(
    context_tokens: int,
    kv_dtype: str = "f16",
    estimated_layers: int = 32,
    hidden_size: int = 2560,
    kv_heads: int = 8,
    head_dim: int = 128,
) -> float:
    """
    Conservatively estimate KV cache memory footprint in GB.
    KV bytes = 2 (keys+values) * layers * kv_heads * head_dim * context_tokens * bytes_per_elem
    """
    bytes_per_elem = 2.0 if kv_dtype.lower() in ("f16", "bf16") else (1.0 if kv_dtype.lower() == "q8_0" else 0.5)
    total_bytes = 2 * estimated_layers * kv_heads * head_dim * context_tokens * bytes_per_elem
    return round(total_bytes / (1024**3), 3)


def estimate_activation_headroom_gb(max_pixels: int) -> float:
    """
    Estimate memory needed for vision patch token activations and compute buffers.
    For standard ~1024x1024 images, reserve ~1.0 - 1.5 GB.
    """
    pixels_ratio = max_pixels / (1024 * 1024)
    return round(max(0.8, 1.2 * pixels_ratio), 2)


# ---------------------------------------------------------------------------
# Known-Good Runtime Profile Cache
# ---------------------------------------------------------------------------


class KnownGoodRuntimeCache:
    """Persists and retrieves validated runtime configurations across application restarts."""

    def __init__(self, cache_file: Path | str | None = None) -> None:
        self.cache_file = Path(cache_file or "cache/.known_good_runtime.json")

    def _generate_cache_key(self, hardware: HardwareProfile, model: ModelProfile) -> str:
        """Generate fingerprint of hardware + model profile."""
        fp = {
            "gpu_name": hardware.gpu.name if hardware.gpu else "NO_GPU",
            "vram_total": hardware.gpu.vram_total_gb if hardware.gpu else 0.0,
            "ram_total": hardware.system_ram_total_gb,
            "model_id": model.model_id,
            "quantization": model.quantization,
            "family": model.family,
        }
        return calculate_dict_hash(fp)

    def load_known_good(self, hardware: HardwareProfile, model: ModelProfile) -> dict[str, Any] | None:
        """Retrieve cached known-good runtime config if available."""
        if not self.cache_file.exists():
            return None
        try:
            with open(self.cache_file, encoding="utf-8") as f:
                data = json.load(f)
            key = self._generate_cache_key(hardware, model)
            return data.get(key)
        except Exception as e:
            logger.debug("Failed to read known-good runtime cache", error=str(e))
            return None

    def save_known_good(self, hardware: HardwareProfile, model: ModelProfile, config: RuntimeConfig) -> None:
        """Save a validated, working runtime config."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            if self.cache_file.exists():
                try:
                    with open(self.cache_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}

            key = self._generate_cache_key(hardware, model)
            data[key] = config.model_dump()

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.info("Saved known-good runtime configuration to cache", model_id=model.model_id)
        except Exception as e:
            logger.warning("Failed to save known-good runtime config", error=str(e))
