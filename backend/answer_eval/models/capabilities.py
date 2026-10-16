"""Capability validation and error handling for perception agents."""

from answer_eval.core.errors import UnsupportedCapabilityError
from answer_eval.models.profiles import ModelProfile


def check_capability(profile: ModelProfile, capability_name: str) -> bool:
    """Check whether a model profile supports a specific capability."""
    caps = profile.to_capabilities()
    return getattr(caps, capability_name, False)


def require_capability(profile: ModelProfile, capability_name: str, agent_name: str = "Agent") -> None:
    """Enforce that a capability is supported, or raise UnsupportedCapabilityError with context."""
    if not check_capability(profile, capability_name):
        raise UnsupportedCapabilityError(
            f"Agent '{agent_name}' requires capability '{capability_name}' which is not supported by active model '{profile.model_id}'.",
            details={
                "model_id": profile.model_id,
                "model_family": profile.family,
                "required_capability": capability_name,
                "agent_name": agent_name,
            },
        )


def resolve_reasoning_mode(requested_mode: str, profile: ModelProfile) -> tuple[str, str | None]:
    """
    Resolve requested reasoning mode (direct, normal, thinking).
    If thinking requested on a non-thinking model, downgrade to direct/normal with a warning.
    """
    requested_lower = requested_mode.lower()
    if requested_lower == "thinking":
        if not profile.supports_thinking:
            return (
                "direct",
                f"Model '{profile.model_id}' does not support thinking mode; downgraded to direct reasoning.",
            )
        return "thinking", None
    return requested_lower, None
