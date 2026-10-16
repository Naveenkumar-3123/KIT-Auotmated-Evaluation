"""Model Registry loader and active profile resolver."""

import os
from pathlib import Path

import yaml

from answer_eval.core.config import Settings, load_settings
from answer_eval.core.errors import ModelNotAvailableError, ModelProfileError
from answer_eval.core.logging import get_logger
from answer_eval.models.profiles import ModelProfile

logger = get_logger("models.registry")


class ModelRegistry:
    """Manages available model profiles and resolves active profile."""

    def __init__(self, config_path: Path | str | None = None, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or Path(os.getcwd())
        if config_path is None:
            self.config_path = self.workspace_root / "config" / "models.yaml"
        else:
            self.config_path = Path(config_path)

        self._profiles: dict[str, ModelProfile] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Parse models.yaml and load ModelProfile instances."""
        if not self.config_path.exists():
            raise ModelProfileError(f"Model registry configuration file not found at: {self.config_path}")

        try:
            with open(self.config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except Exception as e:
            raise ModelProfileError(f"Failed to parse models.yaml: {e}") from e

        raw_models = raw.get("models", {})
        if not isinstance(raw_models, dict) or not raw_models:
            raise ModelProfileError("No models found in models.yaml")

        self._profiles.clear()
        for model_id, model_data in raw_models.items():
            if not isinstance(model_data, dict):
                continue
            data = dict(model_data)
            data["model_id"] = model_id
            if "provider" in data and "provider_type" not in data:
                data["provider_type"] = data.pop("provider")
            try:
                profile = ModelProfile(**data)
                self._profiles[model_id] = profile
            except Exception as e:
                logger.warning(
                    "Skipping invalid model profile",
                    model_id=model_id,
                    error=str(e),
                )

        logger.info(
            "Model registry loaded",
            profile_count=len(self._profiles),
            profiles=list(self._profiles.keys()),
        )

    def get_profile(self, model_id: str) -> ModelProfile:
        """Retrieve a profile by model_id."""
        if model_id not in self._profiles:
            available = list(self._profiles.keys())
            raise ModelNotAvailableError(
                f"Model profile '{model_id}' is not registered.",
                details={"model_id": model_id, "available_profiles": available},
            )
        profile = self._profiles[model_id]
        if not profile.enabled:
            raise ModelNotAvailableError(
                f"Model profile '{model_id}' is disabled.",
                details={"model_id": model_id},
            )
        return profile

    def list_profiles(self, enabled_only: bool = True) -> list[ModelProfile]:
        """List all registered profiles."""
        if enabled_only:
            return [p for p in self._profiles.values() if p.enabled]
        return list(self._profiles.values())

    def get_active_profile(self, settings: Settings | None = None) -> ModelProfile:
        """Resolve active model profile using settings and environment variables."""
        if settings is None:
            settings = load_settings()

        active_id = os.getenv("MODEL_PROFILE", settings.active_model_profile)
        profile = self.get_profile(active_id)
        logger.info(
            "Active model profile resolved",
            model_id=profile.model_id,
            display_name=profile.display_name,
            provider=profile.provider_type.value,
            quantization=profile.quantization,
            family=profile.family,
        )
        return profile


# Module-level convenience function
_global_registry: ModelRegistry | None = None


def get_model_registry(config_path: Path | str | None = None) -> ModelRegistry:
    """Get or instantiate singleton model registry."""
    global _global_registry
    if _global_registry is None or config_path is not None:
        _global_registry = ModelRegistry(config_path=config_path)
    return _global_registry
