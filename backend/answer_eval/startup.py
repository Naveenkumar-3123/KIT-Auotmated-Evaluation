"""Startup orchestrator: detects hardware, plans runtime, validates configuration, and prepares pipeline."""

import os
from dataclasses import dataclass
from pathlib import Path

from answer_eval.core.config import Settings, load_settings
from answer_eval.core.logging import configure_logging, get_logger
from answer_eval.hardware.detector import detect_hardware
from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.inference.factory import create_inference_provider
from answer_eval.inference.provider import InferenceProvider
from answer_eval.models.profiles import ModelProfile
from answer_eval.models.registry import ModelRegistry, get_model_registry
from answer_eval.runtime.planner import RuntimePlanner
from answer_eval.runtime.profiles import RuntimeConfig

logger = get_logger("startup")


@dataclass
class StartupEnvironment:
    """Complete initialized runtime environment."""

    settings: Settings
    hardware: HardwareProfile
    active_model: ModelProfile
    runtime_config: RuntimeConfig
    inference_provider: InferenceProvider
    model_registry: ModelRegistry


async def run_startup_sequence(
    config_path: Path | str | None = None,
    workspace_root: Path | None = None,
) -> StartupEnvironment:
    """
    Execute full startup sequence:
    1. Load settings & configure structured logging
    2. Detect CPU, RAM, and GPU hardware
    3. Load ModelRegistry & resolve active profile
    4. Plan conservative runtime configuration
    5. Create InferenceProvider
    6. Return ready StartupEnvironment
    """
    root = workspace_root or Path(os.getcwd())
    settings = load_settings(config_path)
    configure_logging(log_level=settings.log_level)

    logger.info("Initializing Answer Paper Evaluation System", version="0.1.0")

    # 1. Detect hardware
    hardware = detect_hardware()

    # 2. Model registry
    registry = get_model_registry()
    active_model = registry.get_active_profile(settings)

    # 3. Plan runtime
    planner = RuntimePlanner(workspace_root=root)
    runtime_config = planner.plan_candidate(
        hardware=hardware,
        model=active_model,
        settings=settings,
    )

    # 4. Create provider
    provider = create_inference_provider(active_model)
    await provider.initialize(
        model=active_model,
        config=runtime_config,
        hardware=hardware,
    )

    logger.info(
        "Startup sequence complete. System is ready.",
        model_id=active_model.model_id,
        provider=active_model.provider_type.value,
        n_gpu_layers=runtime_config.n_gpu_layers,
        context_size=runtime_config.n_ctx,
        is_hybrid=runtime_config.is_hybrid_offload,
    )

    return StartupEnvironment(
        settings=settings,
        hardware=hardware,
        active_model=active_model,
        runtime_config=runtime_config,
        inference_provider=provider,
        model_registry=registry,
    )
