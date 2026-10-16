"""Abstract base class for all inference providers."""

from abc import ABC, abstractmethod
from typing import Any

from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.inference.types import InferenceRequest, InferenceResponse, MemorySnapshot
from answer_eval.models.profiles import ModelCapabilities, ModelProfile
from answer_eval.runtime.profiles import RuntimeConfig


class InferenceProvider(ABC):
    """Abstract interface defining standard inference execution across backends."""

    @abstractmethod
    async def initialize(
        self,
        model: ModelProfile,
        config: RuntimeConfig,
        hardware: HardwareProfile | None = None,
    ) -> None:
        """Initialize provider with model and runtime configuration."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the backend is reachable, healthy, and ready for requests."""

    @abstractmethod
    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Execute text or vision inference and return standard InferenceResponse."""

    @abstractmethod
    async def infer_structured(
        self,
        request: InferenceRequest,
        schema: type | dict[str, Any],
        max_retries: int = 2,
    ) -> InferenceResponse:
        """Execute inference with JSON schema validation and controlled repair retries."""

    @abstractmethod
    def get_capabilities(self) -> ModelCapabilities:
        """Return active model capabilities."""

    @abstractmethod
    def get_memory_usage(self) -> MemorySnapshot:
        """Return current VRAM / RAM memory utilization snapshot."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanly terminate provider resources and background processes."""
