"""Module 4: PDF Processor for student answer sheets using PyMuPDF and Pillow."""

import io
import uuid
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from answer_eval.core.errors import (
    PDFCorruptError,
    PDFEncryptedError,
    PDFRenderError,
    PDFValidationError,
)
from answer_eval.core.hashing import calculate_bytes_hash, calculate_file_hash
from answer_eval.core.logging import get_logger
from answer_eval.processing.pdf.schemas import (
    PageImage,
    PDFDocument,
    PDFMetadata,
    PDFValidationResult,
)

logger = get_logger("processing.pdf")


class PDFProcessor:
    """Validates, inspects, and renders student answer sheet PDFs into high-resolution page images."""

    def __init__(
        self,
        default_dpi: int = 300,
        max_file_size_mb: float = 150.0,
        max_pages: int = 200,
        output_dir: Path | str | None = None,
    ) -> None:
        self.default_dpi = default_dpi
        self.max_file_size_mb = max_file_size_mb
        self.max_pages = max_pages
        self.output_dir = Path(output_dir or "data/rendered_pages")

    def validate_pdf(self, pdf_path: str | Path) -> PDFValidationResult:
        """
        Perform security and integrity validation on untrusted uploaded PDF.
        Checks: file exists, header magic bytes, encryption, size, readable structure.
        """
        p = Path(pdf_path)
        if not p.exists() or not p.is_file():
            return PDFValidationResult(
                is_valid=False,
                error_message=f"PDF file does not exist at: {p}",
            )

        file_size_bytes = p.stat().st_size
        file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

        if file_size_bytes == 0:
            return PDFValidationResult(
                is_valid=False,
                error_message="PDF file is 0 bytes (empty file).",
                file_size_mb=0.0,
            )

        if file_size_mb > self.max_file_size_mb:
            return PDFValidationResult(
                is_valid=False,
                error_message=f"PDF file exceeds maximum allowed size ({file_size_mb} MB > {self.max_file_size_mb} MB).",
                file_size_mb=file_size_mb,
            )

        # Check PDF header magic bytes
        try:
            with open(p, "rb") as f:
                header = f.read(5)
                if not header.startswith(b"%PDF-"):
                    return PDFValidationResult(
                        is_valid=False,
                        error_message="Invalid file header: not a valid PDF document.",
                        file_size_mb=file_size_mb,
                    )
        except Exception as e:
            return PDFValidationResult(
                is_valid=False,
                error_message=f"Failed to read file header: {e}",
                file_size_mb=file_size_mb,
            )

        # Inspect using PyMuPDF
        doc = None
        try:
            doc = fitz.open(str(p))
            if doc.is_encrypted:
                return PDFValidationResult(
                    is_valid=False,
                    error_message="PDF is encrypted / password protected.",
                    file_size_mb=file_size_mb,
                    is_encrypted=True,
                )

            page_count = len(doc)
            if page_count == 0:
                return PDFValidationResult(
                    is_valid=False,
                    error_message="PDF contains 0 pages.",
                    file_size_mb=file_size_mb,
                    page_count=0,
                )

            if page_count > self.max_pages:
                return PDFValidationResult(
                    is_valid=False,
                    error_message=f"PDF page count ({page_count}) exceeds limit of {self.max_pages}.",
                    file_size_mb=file_size_mb,
                    page_count=page_count,
                )

            return PDFValidationResult(
                is_valid=True,
                file_size_mb=file_size_mb,
                page_count=page_count,
                is_encrypted=False,
            )

        except Exception as e:
            return PDFValidationResult(
                is_valid=False,
                error_message=f"Corrupt or unreadable PDF document: {e}",
                file_size_mb=file_size_mb,
            )
        finally:
            if doc is not None:
                doc.close()

    def inspect_pdf(self, pdf_path: str | Path) -> PDFMetadata:
        """Inspect and return metadata for a validated PDF."""
        val = self.validate_pdf(pdf_path)
        if not val.is_valid:
            if val.is_encrypted:
                raise PDFEncryptedError(val.error_message or "PDF is encrypted")
            elif "corrupt" in (val.error_message or "").lower():
                raise PDFCorruptError(val.error_message or "PDF is corrupt")
            else:
                raise PDFValidationError(val.error_message or "PDF validation failed")

        p = Path(pdf_path)
        pdf_hash = calculate_file_hash(p)
        doc = fitz.open(str(p))
        try:
            meta = doc.metadata or {}
            return PDFMetadata(
                page_count=len(doc),
                title=meta.get("title"),
                author=meta.get("author"),
                file_size_bytes=p.stat().st_size,
                is_encrypted=doc.is_encrypted,
                pdf_hash=pdf_hash,
            )
        finally:
            doc.close()

    def render_page(
        self,
        doc: fitz.Document,
        page_number: int,
        submission_id: str,
        pdf_path: str,
        dpi: int | None = None,
        save_to_disk: bool = True,
    ) -> tuple[PageImage, Image.Image]:
        """
        Render a single 1-based page number to high-resolution Pillow Image and save as PNG.
        """
        active_dpi = dpi or self.default_dpi
        page_idx = page_number - 1
        if page_idx < 0 or page_idx >= len(doc):
            raise PDFRenderError(f"Page number {page_number} is out of bounds (1..{len(doc)}).")

        try:
            page = doc[page_idx]
            # Standard PDF is 72 points per inch. Matrix zoom factor = dpi / 72
            zoom = active_dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            # Convert pixmap to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Calculate deterministic page hash
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            img_bytes = buffer.getvalue()
            page_hash = calculate_bytes_hash(img_bytes)

            img_path_str = ""
            file_size = len(img_bytes)
            if save_to_disk:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                dest_file = self.output_dir / f"{submission_id}_page_{page_number:03d}_{page_hash[:8]}.png"
                with open(dest_file, "wb") as f:
                    f.write(img_bytes)
                img_path_str = str(dest_file)

            page_info = PageImage(
                submission_id=submission_id,
                page_number=page_number,
                width_px=pix.width,
                height_px=pix.height,
                dpi=active_dpi,
                pdf_path=str(pdf_path),
                image_path=img_path_str,
                page_hash=page_hash,
                file_size_bytes=file_size,
            )

            return page_info, img

        except Exception as e:
            raise PDFRenderError(
                f"Failed to render page {page_number} of {pdf_path}: {e}",
                details={"page_number": page_number, "pdf_path": str(pdf_path)},
            ) from e

    def process_pdf(
        self,
        pdf_path: str | Path,
        submission_id: str | None = None,
        dpi: int | None = None,
    ) -> PDFDocument:
        """
        Process entire PDF: validate, inspect, render every page, and return PDFDocument.
        """
        sub_id = submission_id or f"SUB-{uuid.uuid4().hex[:8].upper()}"
        p = Path(pdf_path)
        logger.info("Processing PDF document", pdf_path=str(p), submission_id=sub_id)

        metadata = self.inspect_pdf(p)
        doc = fitz.open(str(p))
        rendered_pages: list[PageImage] = []

        try:
            for page_num in range(1, metadata.page_count + 1):
                page_image, _ = self.render_page(
                    doc=doc,
                    page_number=page_num,
                    submission_id=sub_id,
                    pdf_path=str(p),
                    dpi=dpi,
                    save_to_disk=True,
                )
                rendered_pages.append(page_image)
        finally:
            doc.close()

        logger.info(
            "PDF processing complete",
            submission_id=sub_id,
            pages_rendered=len(rendered_pages),
            pdf_hash=metadata.pdf_hash[:12],
        )

        return PDFDocument(
            submission_id=sub_id,
            pdf_path=str(p),
            pdf_hash=metadata.pdf_hash,
            page_count=metadata.page_count,
            pages=rendered_pages,
            metadata=metadata,
        )
