"""Provenance and traceability data structures."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """Full provenance tracking metadata for auditability and teacher navigation."""

    submission_id: str = Field(description="Unique submission identifier")
    page_number: int = Field(description="1-based page number")
    region_id: str | None = Field(default=None, description="Region ID within the page")
    question_id: str | None = Field(default=None, description="Associated question ID")
    source_image_hash: str = Field(description="SHA-256 hash of the exact source image crop")
    source_image_path: str | None = Field(default=None, description="Path to source image artifact")
    model_id: str = Field(description="Model identifier used for inference")
    model_family: str = Field(default="qwen3_vl", description="Model family")
    quantization: str | None = Field(default=None, description="Quantization used (e.g. Q8_0, Q4_K_M)")
    prompt_version: str = Field(default="v1", description="Prompt template version / hash")
    request_id: str = Field(description="Inference request tracking ID")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO-8601 UTC timestamp of creation",
    )
    extra_metadata: dict[str, Any] = Field(default_factory=dict, description="Additional context")
