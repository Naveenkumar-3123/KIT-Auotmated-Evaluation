"""Runtime planner: generates and calibrates safe configurations for active hardware and model."""

import os
from pathlib import Path

import yaml

from answer_eval.core.config import Settings
from answer_eval.core.logging import get_logger
from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.models.profiles import ModelProfile
from answer_eval.runtime.memory import (
    KnownGoodRuntimeCache,
    estimate_activation_headroom_gb,
    estimate_kv_cache_gb,
    estimate_model_weights_gb,
)
from answer_eval.runtime.profiles import RuntimeConfig, RuntimeProfileConfig

logger = get_logger("runtime.planner")


class RuntimePlanner:
    """Plans and adapts runtime settings according to actual detected hardware and model requirements."""

    def __init__(
        self,
        profiles_config_path: Path | str | None = None,
        workspace_root: Path | None = None,
        cache_file: Path | str | None = None,
    ) -> None:
        self.workspace_root = workspace_root or Path(os.getcwd())
        if profiles_config_path is None:
            self.profiles_config_path = self.workspace_root / "config" / "runtime_profiles.yaml"
        else:
            self.profiles_config_path = Path(profiles_config_path)

        self._profile_templates: dict[str, RuntimeProfileConfig] = {}
        self._load_templates()
        self.cache = KnownGoodRuntimeCache(cache_file)

    def _load_templates(self) -> None:
        """Load profile templates from runtime_profiles.yaml."""
        if not self.profiles_config_path.exists():
            # Fallback default template
            self._profile_templates["fast_local"] = RuntimeProfileConfig(
                description="Default fast local profile",
                target_context=8192,
            )
            return

        try:
            with open(self.profiles_config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            raw_profiles = raw.get("profiles", {})
            for name, data in raw_profiles.items():
                if isinstance(data, dict):
                    self._profile_templates[name] = RuntimeProfileConfig(**data)
        except Exception as e:
            logger.warning("Failed to load runtime_profiles.yaml, using defaults", error=str(e))

    def plan_candidate(
        self,
        hardware: HardwareProfile,
        model: ModelProfile,
        settings: Settings,
        fallback_level: int = 0,
        use_cached_known_good: bool = True,
    ) -> RuntimeConfig:
        """
        Generate a conservative candidate RuntimeConfig.
        If fallback_level > 0, degrades parameters (lower context, reduced GPU layers, smaller resolution).
        """
        # 1. Check known-good cache if no fallback requested
        if fallback_level == 0 and use_cached_known_good:
            cached_dict = self.cache.load_known_good(hardware, model)
            if cached_dict:
                try:
                    cached_config = RuntimeConfig(**cached_dict)
                    logger.info("Using cached known-good runtime config", model_id=model.model_id)
                    return cached_config
                except Exception:
                    pass

        # 2. Select profile template hint
        template_name = model.runtime_profile_hint
        template = self._profile_templates.get(
            template_name,
            self._profile_templates.get(
                "fast_local",
                RuntimeProfileConfig(description="Fallback template"),
            ),
        )

        # 3. CPU threads = physical cores (optimal for llama.cpp without hyperthreading overhead)
        n_threads = max(1, hardware.cpu.physical_cores)

        # 4. Context size and batch sizes
        target_ctx = template.target_context
        max_pixels = template.max_image_pixels
        n_batch = template.target_batch_size
        safety_margin = template.safety_margin_gb or settings.vram_safety_margin_gb

        # Apply fallback degradation if retrying after failure/OOM
        if fallback_level == 1:
            logger.warn("Applying Fallback Level 1: Reducing image resolution and context size")
            max_pixels = min(max_pixels, 589824)  # ~768x768
            target_ctx = max(2048, target_ctx // 2)
            n_batch = min(n_batch, 256)
        elif fallback_level == 2:
            logger.warn("Applying Fallback Level 2: Strict memory conservation")
            max_pixels = min(max_pixels, 262144)  # ~512x512
            target_ctx = max(2048, target_ctx // 2)
            n_batch = 128
        elif fallback_level >= 3:
            logger.warn("Applying Fallback Level 3: Extreme fallback")
            max_pixels = min(max_pixels, 147456)  # ~384x384
            target_ctx = 2048
            n_batch = 64

        # 5. Calculate GPU offload strategy
        ckpt_size_gb, mmproj_size_gb = estimate_model_weights_gb(model, self.workspace_root)
        kv_cache_gb = estimate_kv_cache_gb(target_ctx, kv_dtype=template.kv_cache_dtype)
        activation_gb = estimate_activation_headroom_gb(max_pixels)

        has_gpu = hardware.has_nvidia_gpu and (hardware.gpu is not None)
        available_vram = hardware.gpu.vram_free_gb if (has_gpu and hardware.gpu) else 0.0

        n_gpu_layers = 0
        is_hybrid = False
        est_vram = 0.0
        est_ram = ckpt_size_gb + 0.5  # Base RAM footprint

        if has_gpu and available_vram > 2.0:
            usable_vram = max(0.0, available_vram - safety_margin)
            needed_full_gpu = ckpt_size_gb + mmproj_size_gb + kv_cache_gb + activation_gb

            if template.gpu_layers_override is not None:
                n_gpu_layers = template.gpu_layers_override
                est_vram = min(available_vram, needed_full_gpu)
            elif needed_full_gpu <= usable_vram and template.prefer_full_gpu and fallback_level < 2:
                # Full GPU residency (e.g. 4B on RTX 3060 12GB)
                n_gpu_layers = -1  # Offload all layers to GPU
                est_vram = round(needed_full_gpu, 2)
                est_ram = 1.0  # Minimal system RAM for process state
                is_hybrid = False
            else:
                # Hybrid CPU/GPU offload (e.g. 30B MoE on RTX 4060 8GB or fallback)
                # Conservative partial layer calculation
                # Estimate ~32 layers default for 4B/8B or ~48 layers for 30B
                approx_layers = 48 if "30b" in model.size_class or "large" in model.size_class else 32
                weight_per_layer = ckpt_size_gb / max(1, approx_layers)
                vram_for_weights = max(0.0, usable_vram - mmproj_size_gb - kv_cache_gb - activation_gb)
                layers_that_fit = int(vram_for_weights // max(0.05, weight_per_layer))
                n_gpu_layers = max(0, min(approx_layers - 2, layers_that_fit))

                est_vram = round(
                    min(
                        available_vram,
                        mmproj_size_gb + kv_cache_gb + activation_gb + (n_gpu_layers * weight_per_layer),
                    ),
                    2,
                )
                est_ram = round(ckpt_size_gb + 2.0, 2)
                is_hybrid = n_gpu_layers > 0 and n_gpu_layers < approx_layers
        else:
            # CPU only
            n_gpu_layers = 0
            est_vram = 0.0
            est_ram = round(ckpt_size_gb + kv_cache_gb + 2.0, 2)
            is_hybrid = False

        config = RuntimeConfig(
            profile_name=template_name,
            n_gpu_layers=n_gpu_layers,
            n_ctx=target_ctx,
            n_batch=n_batch,
            n_ubatch=min(n_batch, 512),
            n_threads=n_threads,
            max_image_pixels=max_pixels,
            kv_cache_dtype=template.kv_cache_dtype,
            host=settings.llama_server.host,
            port=settings.llama_server.port,
            safety_margin_gb=safety_margin,
            estimated_vram_gb=est_vram,
            estimated_ram_gb=est_ram,
            is_hybrid_offload=is_hybrid,
            fallback_level=fallback_level,
        )

        logger.info(
            "Runtime candidate planned",
            profile=template_name,
            n_gpu_layers=n_gpu_layers,
            n_ctx=target_ctx,
            n_threads=n_threads,
            max_pixels=max_pixels,
            est_vram_gb=est_vram,
            est_ram_gb=est_ram,
            is_hybrid=is_hybrid,
            fallback_level=fallback_level,
        )

        return config
