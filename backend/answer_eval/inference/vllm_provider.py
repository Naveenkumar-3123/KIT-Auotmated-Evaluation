"""VLLMProvider: remote client stub for future cloud GPU vLLM deployment."""

from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.inference.llama_server_provider import LlamaServerProvider
from answer_eval.models.profiles import ModelProfile
from answer_eval.runtime.profiles import RuntimeConfig


class VLLMProvider(LlamaServerProvider):
    """
    Client for remote vLLM OpenAI-compatible endpoint.
    Inherits standard OpenAI-compatible protocol handling from LlamaServerProvider.
    """

    async def initialize(
        self,
        model: ModelProfile,
        config: RuntimeConfig,
        hardware: HardwareProfile | None = None,
    ) -> None:
        """Initialize remote vLLM client pointing to endpoint."""
        await super().initialize(model, config, hardware)
        if model.endpoint:
            self.base_url = model.endpoint
