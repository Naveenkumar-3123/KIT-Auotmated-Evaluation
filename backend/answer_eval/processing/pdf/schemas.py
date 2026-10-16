"""PDF processing data structures."""

from pydantic import BaseModel, Field


class PDFMetadata(BaseModel):
    """Metadata extracted from PDF file."""

    page_count: int = Field(description="Total number of pages")
    title: str | None = None
    author: str | None = None
    file_size_bytes: int = Field(description="File size on disk in bytes")
    is_encrypted: bool = Field(default=False, description="Whether the PDF is password-protected")
    pdf_hash: str = Field(description="SHA-256 hash of entire PDF document")


class PDFValidationResult(BaseModel):
    """Result of security and integrity validation on a PDF."""

    is_valid: bool
    error_message: str | None = None
    file_size_mb: float = 0.0
    page_count: int = 0
    is_encrypted: bool = False
    details: dict[str, str] = Field(default_factory=dict)


class PageImage(BaseModel):
    """Rendered page image and associated metadata."""

    submission_id: str = Field(description="Submission tracking identifier")
    page_number: int = Field(description="1-based page index")
    width_px: int = Field(description="Rendered image width in pixels")
    height_px: int = Field(description="Rendered image height in pixels")
    dpi: int = Field(default=300, description="DPI used during rendering")
    pdf_path: str = Field(description="Path to source PDF file")
    image_path: str = Field(description="Path to rendered PNG file on disk")
    page_hash: str = Field(description="SHA-256 hash of the rendered page image")
    file_size_bytes: int = Field(default=0, description="Rendered image file size in bytes")


class PDFDocument(BaseModel):
    """Complete container for a validated and processed answer sheet PDF."""

    submission_id: str = Field(description="Unique submission identifier")
    pdf_path: str = Field(description="Original PDF file path")
    pdf_hash: str = Field(description="Document SHA-256 hash")
    page_count: int = Field(description="Total pages")
    pages: list[PageImage] = Field(default_factory=list, description="Rendered page images")
    metadata: PDFMetadata
