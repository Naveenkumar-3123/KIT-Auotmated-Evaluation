"""Question mapping schemas (Milestone 7).

Line-level observations feed the deterministic QuestionSpanMapper; its output
is the cross-page QuestionSpan structure used to group segmented regions into
per-question evaluation packets.
"""

from pydantic import BaseModel, Field

from answer_eval.processing.segmentation.schemas import BoundingBox


class LineObservation(BaseModel):
    """One transcribed/layout line on a page with its position.

    Produced by OCR/VLM transcription plus layout analysis; the left-margin
    x-coordinate is the strong structural signal for question anchors.
    """

    page_number: int = Field(description="1-based page number")
    text: str = Field(description="Transcribed line text")
    bbox: BoundingBox = Field(description="Normalized line bounding box")
    reading_order: int = Field(default=1, ge=1, description="Reading order on the page")


class MarkerPosition(BaseModel):
    """Where a detected question anchor sits in the document."""

    question_number: int = Field(ge=1)
    raw_text: str = Field(description="Original marker text, e.g. 'Q11.' or '12(a)'")
    page_number: int
    y_center: float = Field(ge=0.0, le=1.0, description="Normalized vertical center of the marker line")
    line_index: int = Field(ge=0, description="Reading-order index of the marker line on its page")
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    warnings: list[str] = Field(default_factory=list)


class QuestionSpan(BaseModel):
    """All content belonging to ONE question, possibly across many pages."""

    question_id: str = Field(description="Canonical id, e.g. 'Q11'")
    question_number: int = Field(ge=1)
    start_page: int
    end_page: int
    markers: list[MarkerPosition] = Field(default_factory=list)
    region_ids: list[str] = Field(default_factory=list, description="Assigned answer-region ids")
    diagram_region_ids: list[str] = Field(default_factory=list, description="Assigned diagram-region ids")
    mapping_uncertain: bool = Field(default=False)
    uncertainty_reasons: list[str] = Field(default_factory=list)

    def add_uncertainty(self, reason: str) -> None:
        self.mapping_uncertain = True
        if reason not in self.uncertainty_reasons:
            self.uncertainty_reasons.append(reason)


class UnassignedContent(BaseModel):
    """Content that could not be attributed to any question without guessing."""

    region_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class QuestionMappingResult(BaseModel):
    """Complete mapping outcome for one submission."""

    submission_id: str
    spans: list[QuestionSpan] = Field(default_factory=list)
    unassigned: UnassignedContent = Field(default_factory=UnassignedContent)
