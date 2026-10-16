"""Unit tests for Module 4: PDF Processor."""

from pathlib import Path

from answer_eval.processing.pdf.processor import PDFProcessor
from answer_eval.processing.pdf.schemas import PDFDocument


def test_pdf_validation_valid(sample_pdf: Path, temp_workspace: Path) -> None:
    processor = PDFProcessor(output_dir=temp_workspace / "rendered")
    val = processor.validate_pdf(sample_pdf)
    assert val.is_valid is True
    assert val.page_count == 2
    assert val.is_encrypted is False
    assert val.file_size_mb >= 0


def test_pdf_validation_nonexistent(temp_workspace: Path) -> None:
    processor = PDFProcessor(output_dir=temp_workspace / "rendered")
    val = processor.validate_pdf(temp_workspace / "nonexistent.pdf")
    assert val.is_valid is False
    assert "does not exist" in (val.error_message or "")


def test_pdf_validation_corrupt(temp_workspace: Path) -> None:
    corrupt_path = temp_workspace / "corrupt.pdf"
    with open(corrupt_path, "wb") as f:
        f.write(b"%PDF-1.5 this is completely corrupt binary data without xref or trailer")

    processor = PDFProcessor(output_dir=temp_workspace / "rendered")
    val = processor.validate_pdf(corrupt_path)
    assert val.is_valid is False


def test_pdf_render_pages(sample_pdf: Path, temp_workspace: Path) -> None:
    rendered_dir = temp_workspace / "rendered"
    processor = PDFProcessor(default_dpi=150, output_dir=rendered_dir)

    pdf_doc = processor.process_pdf(sample_pdf, submission_id="SUB-TEST-001")
    assert isinstance(pdf_doc, PDFDocument)
    assert pdf_doc.submission_id == "SUB-TEST-001"
    assert pdf_doc.page_count == 2
    assert len(pdf_doc.pages) == 2

    # Check page 1 properties
    p1 = pdf_doc.pages[0]
    assert p1.page_number == 1
    assert p1.dpi == 150
    assert p1.width_px > 0
    assert p1.height_px > 0
    assert len(p1.page_hash) == 64
    assert Path(p1.image_path).exists()

    # Check page 2 properties
    p2 = pdf_doc.pages[1]
    assert p2.page_number == 2
    assert p2.page_hash != p1.page_hash
    assert Path(p2.image_path).exists()
