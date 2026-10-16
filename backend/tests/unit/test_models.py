"""Unit tests for Model Registry, Model Profiles, and Capability Checking."""

import pytest

from answer_eval.core.errors import UnsupportedCapabilityError
from answer_eval.models.capabilities import (
    check_capability,
    require_capability,
    resolve_reasoning_mode,
)
from answer_eval.models.profiles import ModelProfile, ProviderType
from answer_eval.models.registry import get_model_registry


def test_model_registry_loading() -> None:
    registry = get_model_registry()
    profiles = registry.list_profiles(enabled_only=False)
    assert len(profiles) >= 3

    # Check 4B Q8 profile
    q8_profile = registry.get_profile("qwen_vl_4b_q8")
    assert q8_profile.size_class == "4b"
    assert q8_profile.quantization == "Q8_0"
    assert q8_profile.provider_type == ProviderType.LLAMA_SERVER
    assert q8_profile.supports_vision is True
    assert q8_profile.supports_structured_output is True


def test_model_switching_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = get_model_registry()

    monkeypatch.setenv("MODEL_PROFILE", "qwen_vl_4b_q4")
    active_q4 = registry.get_active_profile()
    assert active_q4.model_id == "qwen_vl_4b_q4"
    assert active_q4.quantization == "Q4_K_M"

    monkeypatch.setenv("MODEL_PROFILE", "qwen_vl_large_local")
    active_large = registry.get_active_profile()
    assert active_large.model_id == "qwen_vl_large_local"
    assert active_large.size_class == "large"


def test_capabilities_and_fallbacks() -> None:
    instruct_model = ModelProfile(
        model_id="test_instruct",
        display_name="Test Instruct",
        family="qwen3_vl",
        size_class="4b",
        checkpoint_path="test.gguf",
        supports_vision=True,
        supports_thinking=False,
    )

    assert check_capability(instruct_model, "vision") is True
    assert check_capability(instruct_model, "thinking") is False

    require_capability(instruct_model, "vision", agent_name="OCRAgent")

    with pytest.raises(UnsupportedCapabilityError):
        require_capability(instruct_model, "thinking", agent_name="ReasoningAgent")

    # Reasoning mode fallback test
    mode, warn = resolve_reasoning_mode("thinking", instruct_model)
    assert mode == "direct"
    assert warn is not None
