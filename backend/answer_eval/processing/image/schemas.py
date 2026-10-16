"""Image preprocessing and quality metrics data structures."""

from pydantic import BaseModel, Field


class ImageQualityMetrics(BaseModel):
    """Objective visual quality measurements of a page image."""

    blur_score: float = Field(description="Laplacian variance (>100 is sharp, <50 is blurry)")
    brightness_score: float = Field(description="Mean pixel brightness (0-255, 180-220 is optimal for paper)")
    contrast_score: float = Field(description="Pixel standard deviation (>40 indicates good contrast)")
    estimated_skew_degrees: float = Field(default=0.0, description="Estimated scan skew angle in degrees (-15 to +15)")
    quality_flags: list[str] = Field(
        default_factory=list, description="Quality warnings (e.g. BLURRY, LOW_CONTRAST, HIGH_SKEW)"
    )


class PreprocessingConfig(BaseModel):
    """Configuration switches for image preprocessing operations."""

    orientation_correction_enabled: bool = Field(default=True)
    deskew_enabled: bool = Field(default=True)
    max_deskew_angle: float = Field(default=15.0)
    border_removal_enabled: bool = Field(default=True)
    noise_reduction_enabled: bool = Field(default=True)
    noise_reduction_kernel: int = Field(default=3)
    contrast_adjustment_enabled: bool = Field(default=True)
    clahe_clip_limit: float = Field(default=2.0)
    brightness_normalization_enabled: bool = Field(default=True)
    target_brightness: float = Field(default=200.0)
    resolution_normalization_enabled: bool = Field(default=True)
    max_dimension_px: int = Field(default=2400)
    grayscale_enabled: bool = Field(default=False)


class PreprocessedPage(BaseModel):
    """Processed page container preserving both original and preprocessed references."""

    submission_id: str = Field(description="Submission tracking ID")
    page_number: int = Field(description="1-based page number")
    original_image_path: str = Field(description="Path to original rendered page PNG")
    original_page_hash: str = Field(description="Hash of original image")
    preprocessed_image_path: str = Field(description="Path to preprocessed page PNG")
    preprocessed_page_hash: str = Field(description="Hash of preprocessed image")
    width_px: int = Field(description="Final image width in pixels")
    height_px: int = Field(description="Final image height in pixels")
    applied_operations: list[str] = Field(default_factory=list, description="List of preprocessing steps applied")
    quality_metrics: ImageQualityMetrics = Field(description="Image quality measurements")
