"""OCR agent output schemas."""

from typing import Any

from pydantic import BaseModel, Field

from answer_eval.core.provenance import Provenance


class OCRUncertainSpan(BaseModel):
    """Specific span of text with transcription uncertainty."""

    text: str = Field(description="Transcribed text as best read")
    reason: str = Field(default="ambiguous", description="Reason: smudged, crossed_out, faint, ambiguous_character")
    position_hint: str | None = Field(default=None, description="Line or word index hint")


class OCRResult(BaseModel):
    """Output of OCR agent for a single region crop."""

    raw_text: str = Field(description="Exact verbatim transcription preserving all original misspellings and grammar")
    lines: list[str] = Field(default_factory=list, description="Text broken down line-by-line")
    uncertain_spans: list[OCRUncertainSpan] = Field(default_factory=list, description="Any uncertain handwriting spans")
    flags: list[str] = Field(
        default_factory=list,
        description="Visual/transcription flags: very_faint, crossed_out_text, etc.",
    )
    word_count: int = Field(default=0, description="Deterministic token count of raw_text")
    status: str = Field(
        default="success",
        description="OCR status: 'success', 'truncated', 'empty_response', 'failed'",
    )
    provenance: Provenance = Field(description="Full traceability metadata")
    model_metadata: dict[str, Any] = Field(default_factory=dict, description="Inference timing and token usage")
