"""Unit tests for Module 6: Question Segmentation and Layout Region Classification."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from answer_eval.processing.image.schemas import ImageQualityMetrics, PreprocessedPage
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    PageSegmentationResult,
    RegionType,
)
from answer_eval.processing.segmentation.segmenter import QuestionSegmenter


def test_bounding_box_coordinates() -> None:
    bbox = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.9, y_max=0.8)
    left, top, right, bottom = bbox.to_pixel_coords(width=1000, height=2000)
    assert left == 100
    assert top == 400
    assert right == 900
    assert bottom == 1600


def test_question_segmentation(sample_image: Image.Image, temp_workspace: Path) -> None:
    img_path = temp_workspace / "prep_page.png"
    sample_image.save(img_path)

    prep_page = PreprocessedPage(
        submission_id="SUB-01",
        page_number=1,
        original_image_path=str(img_path),
        original_page_hash="orig_hash",
        preprocessed_image_path=str(img_path),
        preprocessed_page_hash="prep_hash",
        width_px=sample_image.width,
        height_px=sample_image.height,
        quality_metrics=ImageQualityMetrics(
            blur_score=150.0,
            brightness_score=200.0,
            contrast_score=50.0,
        ),
    )

    segmenter = QuestionSegmenter(crops_output_dir=temp_workspace / "crops")
    result = segmenter.segment_page(prep_page)

    assert isinstance(result, PageSegmentationResult)
    assert result.submission_id == "SUB-01"
    assert result.page_number == 1
    assert len(result.regions) >= 1

    for reg in result.regions:
        assert reg.region_id.startswith("REG-P01-")
        assert reg.reading_order >= 1
        assert reg.bbox.x_min >= 0.0 and reg.bbox.x_max <= 1.0
        assert reg.bbox.y_min >= 0.0 and reg.bbox.y_max <= 1.0
        assert 0.0 <= reg.classification_confidence <= 1.0
        assert Path(reg.crop_image_path).exists()
        assert len(reg.crop_image_hash) == 64


def test_classify_handwritten_text_alone(temp_workspace: Path) -> None:
    """Test A: Handwritten text lines alone are classified as ANSWER_TEXT."""
    img = Image.new("RGB", (600, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Simulate horizontal lines of handwriting text
    for y in range(40, 260, 40):
        draw.text((50, y), f"This is line of student handwritten answer text at y={y}", fill=(20, 20, 20))

    img_np = np.array(img)
    gray = np.array(img.convert("L"))

    segmenter = QuestionSegmenter(crops_output_dir=temp_workspace / "crops")
    region_type, conf = segmenter._classify_region_content(gray, img_np)

    assert region_type == RegionType.ANSWER_TEXT
    assert conf >= 0.5


def test_classify_handwritten_text_with_red_teacher_marks(temp_workspace: Path) -> None:
    """Test B: Handwritten text with red teacher check marks/underlines is NOT a diagram."""
    img = Image.new("RGB", (600, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Handwriting text
    draw.text((50, 50), "are combined to improve accuracy and", fill=(10, 10, 10))
    draw.text((50, 90), "reduce overfitting.", fill=(10, 10, 10))
    draw.text((50, 150), "Example: Random Forest combining Decision Trees", fill=(10, 10, 10))

    # Red teacher check marks (✓) and red underline
    draw.line([(400, 60), (415, 80), (445, 45)], fill=(220, 30, 30), width=4)
    draw.line([(50, 115), (200, 115)], fill=(220, 30, 30), width=3)
    draw.line([(480, 160), (495, 180), (525, 145)], fill=(220, 30, 30), width=4)

    img_np = np.array(img)
    gray = np.array(img.convert("L"))

    segmenter = QuestionSegmenter(crops_output_dir=temp_workspace / "crops")
    region_type, conf = segmenter._classify_region_content(gray, img_np)

    assert region_type == RegionType.ANSWER_TEXT, (
        f"Expected ANSWER_TEXT but got {region_type} with conf {conf}"
    )


def test_classify_arrow_bullet_points(temp_workspace: Path) -> None:
    """Test C: Arrow bullets in handwriting (-> or =>) are NOT classified as diagrams."""
    img = Image.new("RGB", (600, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((50, 40), "-> Point 1: Supervised learning requires labeled data", fill=(15, 15, 15))
    draw.text((50, 90), "-> Point 2: Unsupervised learning finds hidden patterns", fill=(15, 15, 15))
    draw.text((50, 140), "=> Point 3: Reinforcement learning uses rewards", fill=(15, 15, 15))

    img_np = np.array(img)
    gray = np.array(img.convert("L"))

    segmenter = QuestionSegmenter(crops_output_dir=temp_workspace / "crops")
    region_type, conf = segmenter._classify_region_content(gray, img_np)

    assert region_type == RegionType.ANSWER_TEXT


def test_classify_genuine_diagram(temp_workspace: Path) -> None:
    """Test D: Genuine drawn diagram with boxes and arrows is classified as DIAGRAM."""
    img = Image.new("RGB", (600, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Box 1: Client
    draw.rectangle([50, 100, 200, 250], outline=(0, 0, 0), width=3)
    draw.text((90, 160), "Client", fill=(0, 0, 0))

    # Box 2: Server
    draw.rectangle([400, 100, 550, 250], outline=(0, 0, 0), width=3)
    draw.text((440, 160), "Server", fill=(0, 0, 0))

    # Connecting arrow / line
    draw.line([(200, 150), (400, 150)], fill=(0, 0, 0), width=3)
    draw.line([(385, 140), (400, 150), (385, 160)], fill=(0, 0, 0), width=3)
    draw.text((270, 130), "SYN", fill=(0, 0, 0))

    # Box 3: Router
    draw.rectangle([250, 280, 350, 360], outline=(0, 0, 0), width=3)
    draw.text((270, 310), "Router", fill=(0, 0, 0))

    img_np = np.array(img)
    gray = np.array(img.convert("L"))

    segmenter = QuestionSegmenter(crops_output_dir=temp_workspace / "crops")
    region_type, conf = segmenter._classify_region_content(gray, img_np)

    assert region_type == RegionType.DIAGRAM
    assert conf >= 0.70


def _prep_page_from_image(img: Image.Image, temp_workspace: Path, *, page_number: int = 1) -> PreprocessedPage:
    """Build a PreprocessedPage around a raw image for segmentation tests."""
    img_path = temp_workspace / f"prep_p{page_number}.png"
    img.save(img_path)
    return PreprocessedPage(
        submission_id="SUB-01",
        page_number=page_number,
        original_image_path=str(img_path),
        original_page_hash=f"orig_hash_p{page_number}",
        preprocessed_image_path=str(img_path),
        preprocessed_page_hash=f"prep_hash_p{page_number}",
        width_px=img.width,
        height_px=img.height,
        quality_metrics=ImageQualityMetrics(
            blur_score=150.0,
            brightness_score=200.0,
            contrast_score=50.0,
        ),
    )


def test_regions_never_overlap_adjacent_bands(temp_workspace: Path) -> None:
    """Adjacent region crops must not overlap at their shared boundary.

    The old per-band padding (1.5% on BOTH edges, independently) made regions
    that are separated by a narrow whitespace gap bleed into each other, so OCR
    read the same lines at the boundary twice. Boundaries must stay contiguous
    even when content bands are close together.
    """
    img = Image.new("RGB", (800, 1600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Four content clusters: two tight multi-line groups with small gaps.
    bands = [(300, 420), (470, 590), (900, 1010), (1090, 1300)]
    for _group_idx, (y0, y1) in enumerate(bands, start=1):
        y = y0
        while y <= y1:
            draw.line([(150, y), (650, y)], fill=(10, 10, 10), width=8)
            y += 50

    prep_page = _prep_page_from_image(img, temp_workspace)
    segmenter = QuestionSegmenter(crops_output_dir=temp_workspace / "crops")
    result = segmenter.segment_page(prep_page)

    assert len(result.regions) >= 2
    ordered = sorted(result.regions, key=lambda r: (r.bbox.y_min, r.reading_order))
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        assert nxt.bbox.y_min >= prev.bbox.y_max, (
            f"{prev.region_id} ({prev.bbox.y_min:.3f}-{prev.bbox.y_max:.3f}) overlaps "
            f"{nxt.region_id} ({nxt.bbox.y_min:.3f}-{nxt.bbox.y_max:.3f})"
        )
        assert nxt.bbox.y_max > nxt.bbox.y_min  # never a degenerate/inverted band


def test_page_borders_do_not_fuse_answers_into_one_region(temp_workspace: Path) -> None:
    """Regression: scanned page borders / margin rules put ink on EVERY row.

    The horizontal-projection split previously treated those rows as active
    ink, fusing the entire page into ONE region (real failure: 6 answers on a
    scanned page collapsed into a single full-page region, so half the
    questions were never graded). Borders and long vertical structures must be
    stripped before the row profile.
    """
    img = Image.new("RGB", (1000, 2000), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Full-height vertical page borders (like a scanned sheet edge).
    draw.rectangle([4, 0, 10, 1999], fill=(40, 40, 40))
    draw.rectangle([988, 0, 994, 1999], fill=(40, 40, 40))
    # Two answer blocks separated by a wide whitespace gap.
    for y in range(200, 700, 40):
        draw.text((80, y), f"answer block one line at y={y}", fill=(20, 20, 20))
    for y in range(1200, 1700, 40):
        draw.text((80, y), f"answer block two line at y={y}", fill=(20, 20, 20))

    prep_page = _prep_page_from_image(img, temp_workspace)
    segmenter = QuestionSegmenter(crops_output_dir=temp_workspace / "crops")

    # Debug: inspect the cleaned row profile inside the whitespace gap.
    import cv2
    import numpy as np

    gray = np.array(img.convert("L"))
    h, w = gray.shape[:2]
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    border_free = int(w * 0.02)
    cleaned = thresh.copy()
    cleaned[:, :border_free] = 0
    cleaned[:, w - border_free:] = 0
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, h // 40)))
    vertical = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, vertical_kernel)
    cleaned = cv2.subtract(cleaned, vertical)
    speckle_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, speckle_kernel)
    row_sums = np.sum(cleaned == 255, axis=1) / float(w)
    gap = row_sums[750:1150]
    print(f"gap row_sums max={gap.max():.5f} mean={gap.mean():.5f} threshold=0.0015")
    ys = np.where(row_sums > 0.0015)[0]
    print(f"active rows: {len(ys)} first={ys[:3]} last={ys[-3:] if len(ys) else []}")

    result = segmenter.segment_page(prep_page)

    assert len(result.regions) >= 2, (
        f"page borders fused the answer blocks: got {len(result.regions)} region(s)"
    )

