"""Canonical structured answer data structures."""

from pydantic import BaseModel, Field

from answer_eval.agents.diagram.schemas import DiagramResult
from answer_eval.agents.ocr.schemas import OCRUncertainSpan
from answer_eval.core.provenance import Provenance


class AnswerSegment(BaseModel):
    """Specific page region segment belonging to an answer."""

    page_number: int = Field(description="1-based page number")
    region_id: str = Field(description="Segment region identifier")
    reading_order: int = Field(description="Order of this segment within the answer")
    raw_text: str = Field(description="Verbatim raw text for this specific segment")
    crop_image_path: str | None = Field(default=None, description="Path to region crop image")


class CanonicalStructuredAnswer(BaseModel):
    """Canonical reconstructed answer preserving immutable raw text, diagrams, and full provenance."""

    submission_id: str = Field(description="Submission tracking ID")
    question_id: str = Field(description="Unique question identifier (e.g. Q1, Q2a)")
    source_pages: list[int] = Field(description="List of 1-based page numbers this answer spans")
    raw_text: str = Field(description="Complete concatenated immutable raw OCR text")
    normalized_text: str | None = Field(
        default=None, description="Optional normalized text (raw_text is never overwritten)"
    )
    word_count: int = Field(description="Deterministic word count of raw_text")
    segments: list[AnswerSegment] = Field(default_factory=list, description="Ordered constituent segments")
    diagrams: list[DiagramResult] = Field(default_factory=list, description="Associated diagram extraction results")
    uncertainties: list[OCRUncertainSpan] = Field(default_factory=list, description="Aggregated uncertainty spans")
    flags: list[str] = Field(default_factory=list, description="Aggregated transcription and quality flags")
    provenance: Provenance = Field(description="Comprehensive provenance metadata for the reconstructed answer")
