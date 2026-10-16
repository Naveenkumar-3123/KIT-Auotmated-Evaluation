"""Question segmentation and layout region data structures."""

from enum import StrEnum

from pydantic import BaseModel, Field


class RegionType(StrEnum):
    """Classification of content inside a segmented page region."""

    ANSWER_TEXT = "answer_text"
    DIAGRAM = "diagram"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class BoundingBox(BaseModel):
    """Normalized bounding box coordinates (0.0 to 1.0) relative to image dimensions."""

    x_min: float = Field(ge=0.0, le=1.0, description="Normalized left coordinate")
    y_min: float = Field(ge=0.0, le=1.0, description="Normalized top coordinate")
    x_max: float = Field(ge=0.0, le=1.0, description="Normalized right coordinate")
    y_max: float = Field(ge=0.0, le=1.0, description="Normalized bottom coordinate")

    def to_pixel_coords(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Convert normalized coords to absolute pixel coordinates (left, top, right, bottom)."""
        left = max(0, int(self.x_min * width))
        top = max(0, int(self.y_min * height))
        right = min(width, int(self.x_max * width))
        bottom = min(height, int(self.y_max * height))
        return left, top, right, bottom


class QuestionRegion(BaseModel):
    """Segmented region representing a question answer or diagram block."""

    region_id: str = Field(description="Unique region identifier (e.g. REG-P01-01)")
    page_number: int = Field(description="1-based page number")
    submission_id: str = Field(description="Submission tracking ID")
    question_id: str | None = Field(default=None, description="Identified question label (e.g. Q1, Q2a, or None)")
    bbox: BoundingBox = Field(description="Normalized bounding box")
    region_type: RegionType = Field(default=RegionType.ANSWER_TEXT, description="Detected region content type")
    classification_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Classifier confidence for the detected region_type (0.0–1.0)",
    )
    reading_order: int = Field(default=1, description="Sequence order of reading on the page")
    continues_on_next_page: bool = Field(default=False, description="Whether answer flows to subsequent page")
    crop_image_path: str | None = Field(default=None, description="Path to cropped region PNG on disk")
    crop_image_hash: str = Field(default="", description="SHA-256 hash of cropped region image")
    segmentation_confidence: float = Field(default=1.0, description="Confidence in segmentation boundaries")
    is_human_corrected: bool = Field(default=False, description="Whether this region was manually adjusted")
    notes: str | None = Field(default=None, description="Segmentation notes / reason for unknown type")


class PageSegmentationResult(BaseModel):
    """Container for all segmented regions within a preprocessed page."""

    submission_id: str = Field(description="Submission tracking ID")
    page_number: int = Field(description="1-based page number")
    regions: list[QuestionRegion] = Field(default_factory=list, description="Extracted regions in reading order")
    source_page_hash: str = Field(description="Hash of preprocessed page")
    has_diagrams: bool = Field(default=False, description="Whether page contains at least one diagram region")
    layout_type: str = Field(default="single_column", description="Detected page layout")
