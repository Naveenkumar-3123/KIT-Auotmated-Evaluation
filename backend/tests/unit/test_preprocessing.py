"""Unit tests for Module 5: Image Preprocessing and Quality Analysis."""

from pathlib import Path

from PIL import Image

from answer_eval.processing.image.preprocessing import ImagePreprocessor
from answer_eval.processing.image.quality import ImageQualityAnalyzer
from answer_eval.processing.image.schemas import PreprocessedPage, PreprocessingConfig
from answer_eval.processing.pdf.schemas import PageImage


def test_image_quality_analysis(sample_image: Image.Image) -> None:
    analyzer = ImageQualityAnalyzer()
    metrics = analyzer.analyze(sample_image)

    assert metrics.blur_score > 0
    assert 0 <= metrics.brightness_score <= 255
    assert metrics.contrast_score > 0
    assert isinstance(metrics.estimated_skew_degrees, float)


def test_image_preprocessing_pipeline(sample_image: Image.Image, temp_workspace: Path) -> None:
    # Save original sample image to temp file
    orig_path = temp_workspace / "orig_p1.png"
    sample_image.save(orig_path)

    page_img = PageImage(
        submission_id="SUB-TEST",
        page_number=1,
        width_px=sample_image.width,
        height_px=sample_image.height,
        dpi=300,
        pdf_path="test.pdf",
        image_path=str(orig_path),
        page_hash="orig_hash_123",
    )

    preprocessor = ImagePreprocessor(
        output_dir=temp_workspace / "preprocessed",
        config=PreprocessingConfig(
            deskew_enabled=True,
            border_removal_enabled=True,
            contrast_adjustment_enabled=True,
        ),
    )

    prep_page = preprocessor.preprocess_page(page_img)
    assert isinstance(prep_page, PreprocessedPage)
    assert prep_page.page_number == 1
    assert Path(prep_page.original_image_path).exists()
    assert Path(prep_page.preprocessed_image_path).exists()
    assert prep_page.original_image_path != prep_page.preprocessed_image_path
    assert len(prep_page.applied_operations) >= 1
    assert prep_page.quality_metrics.blur_score > 0
