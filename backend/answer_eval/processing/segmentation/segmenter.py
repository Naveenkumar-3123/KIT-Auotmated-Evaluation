"""Module 6: Question Segmentation and layout block extractor."""

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from answer_eval.core.errors import SegmentationError
from answer_eval.core.hashing import calculate_bytes_hash
from answer_eval.core.logging import get_logger
from answer_eval.processing.image.schemas import PreprocessedPage
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    PageSegmentationResult,
    QuestionRegion,
    RegionType,
)

logger = get_logger("processing.segmentation")

# Minimum confidence score for a region to be classified as DIAGRAM.
# Regions scoring below this threshold are treated as ANSWER_TEXT.
DIAGRAM_CONFIDENCE_THRESHOLD = 0.70


def _estimate_red_ink_fraction(color_crop: np.ndarray) -> float:
    """
    Return the fraction of pixels that appear to be red ink (teacher annotations).
    """
    if color_crop is None or color_crop.size == 0:
        return 0.0

    crop_f = color_crop.astype(np.float32)
    r = crop_f[:, :, 0]
    g = crop_f[:, :, 1]
    b = crop_f[:, :, 2]

    red_mask = (
        (r >= 150)
        & (r > g + 40)
        & (r > b + 40)
        & (r < 250)
        & (g < 180)
        & (b < 180)
    )

    return float(np.mean(red_mask))


def _compute_structural_diagram_score(
    gray_crop: np.ndarray,
    color_crop: np.ndarray | None = None,
) -> tuple[float, dict]:
    """
    Compute a [0, 1] confidence score that a region contains a genuine visual diagram.
    """
    h, w = gray_crop.shape[:2]
    if h < 5 or w < 5:
        return 0.0, {}

    area = float(h * w)

    # 1. Ink density
    _, thresh = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink_ratio = float(np.mean(thresh == 255))

    if ink_ratio < 0.003:
        return 0.0, {"reason": "ink_too_sparse", "ink_ratio": ink_ratio}
    if ink_ratio > 0.55:
        return 0.05, {"reason": "ink_too_dense_for_diagram", "ink_ratio": ink_ratio}

    # 2. Red ink fraction
    red_fraction = 0.0
    if color_crop is not None and color_crop.ndim == 3 and color_crop.shape[2] >= 3:
        red_fraction = _estimate_red_ink_fraction(color_crop)

    # 3. Horizontal projection profile
    row_sums = np.sum(thresh == 255, axis=1) / float(w)
    active_rows = np.sum(row_sums > 0.02)
    text_row_density = active_rows / float(h)

    # 4. Connected component analysis excluding red ink
    analysis_mask = thresh.copy()
    if color_crop is not None and color_crop.ndim == 3 and color_crop.shape[2] >= 3:
        crop_f = color_crop.astype(np.float32)
        r, g, b = crop_f[:, :, 0], crop_f[:, :, 1], crop_f[:, :, 2]
        red_px_mask = (
            (r >= 150) & (r > g + 40) & (r > b + 40) & (r < 250) & (g < 180) & (b < 180)
        )
        analysis_mask[red_px_mask] = 0

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(analysis_mask)

    if num_labels <= 1:
        return 0.0, {"reason": "no_ink_components"}

    comp_areas = stats[1:, cv2.CC_STAT_AREA].astype(float)
    comp_ws = stats[1:, cv2.CC_STAT_WIDTH].astype(float)
    comp_hs = stats[1:, cv2.CC_STAT_HEIGHT].astype(float)
    comp_lefts = stats[1:, cv2.CC_STAT_LEFT].astype(float)
    comp_tops = stats[1:, cv2.CC_STAT_TOP].astype(float)

    n_comps = len(comp_areas)

    # 5. Large structural component detection
    large_enclosed_shapes = 0
    for cw, ch in zip(comp_ws, comp_hs, strict=False):
        if cw < 1 or ch < 1:
            continue
        aspect = cw / ch
        rel_w = cw / w
        rel_h = ch / h

        both_axes_significant = rel_w > 0.15 and rel_h > 0.08
        reasonable_aspect = 0.08 <= aspect <= 8.0

        if both_axes_significant and reasonable_aspect:
            large_enclosed_shapes += 1

    # 6. Spatial spread
    spatial_spread_score = 0.0
    if n_comps >= 3:
        cx = (comp_lefts + comp_ws / 2) / w
        cy = (comp_tops + comp_hs / 2) / h
        x_spread = float(np.std(cx)) if len(cx) > 1 else 0.0
        y_spread = float(np.std(cy)) if len(cy) > 1 else 0.0
        spatial_spread_score = min(1.0, (x_spread + y_spread) * 2.5)

    # 7. Contour detection
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    closed_shapes = 0
    for cnt in contours:
        cnt_area = cv2.contourArea(cnt)
        if cnt_area < area * 0.01:
            continue
        perimeter = cv2.arcLength(cnt, True)
        if perimeter < 1:
            continue
        circularity = 4 * np.pi * cnt_area / (perimeter ** 2)
        x, y, cw, ch = cv2.boundingRect(cnt)
        aspect = cw / max(ch, 1)
        if circularity > 0.2 and 0.1 <= aspect <= 6.0 and cw > w * 0.08 and ch > h * 0.06:
            closed_shapes += 1

    debug = {
        "ink_ratio": round(ink_ratio, 3),
        "red_fraction": round(red_fraction, 3),
        "text_row_density": float(round(text_row_density, 3)),
        "n_comps": int(n_comps),
        "large_enclosed_shapes": int(large_enclosed_shapes),
        "closed_shapes": int(closed_shapes),
        "spatial_spread_score": round(spatial_spread_score, 3),
    }

    score = 0.0
    if large_enclosed_shapes >= 2:
        score += 0.50
    elif large_enclosed_shapes == 1:
        score += 0.35

    if closed_shapes >= 2:
        score += 0.30
    elif closed_shapes == 1:
        score += 0.20

    score += spatial_spread_score * 0.20

    if text_row_density > 0.45:
        score -= 0.30
    elif text_row_density > 0.30:
        score -= 0.15

    if red_fraction > 0.15:
        score -= 0.25
    elif red_fraction > 0.05:
        score -= 0.10

    score = max(0.0, min(1.0, score))
    debug["final_score"] = round(score, 3)
    return score, debug


class QuestionSegmenter:
    """Segments preprocessed answer pages into distinct question answer and diagram regions."""

    def __init__(
        self,
        min_region_height_ratio: float = 0.01,
        whitespace_gap_threshold_px: int = 60,
        crops_output_dir: Path | str | None = None,
        diagram_confidence_threshold: float = DIAGRAM_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.min_region_height_ratio = min_region_height_ratio
        self.whitespace_gap_threshold_px = whitespace_gap_threshold_px
        self.crops_output_dir = Path(crops_output_dir or "data/region_crops")
        self.diagram_confidence_threshold = diagram_confidence_threshold

    def _find_horizontal_splits(
        self,
        gray: np.ndarray,
        min_gap_px: int = 60,
        energy_threshold: float = 0.0015,
    ) -> list[tuple[int, int]]:
        """
        Find vertical boundaries (y_start, y_end) of text blocks using horizontal projection profile.
        Preserves all genuine handwriting content (including single lines and bullet points).
        """
        h, w = gray.shape[:2]
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Scans carry full-height page borders / margin rules and speckle noise.
        # A vertical border puts ink on EVERY row, which previously fused the
        # whole page into ONE band (all answers merged into a single region).
        # Strip: edge columns -> long vertical structures -> isolated speckle.
        border_free = int(w * 0.02)
        cleaned = thresh.copy()
        cleaned[:, :border_free] = 0
        cleaned[:, w - border_free:] = 0
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, h // 40)))
        vertical = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, vertical_kernel)
        cleaned = cv2.subtract(cleaned, vertical)
        # Speckle removal via component area: a morphological opening would also
        # erase genuinely thin (1px) pen strokes, which must survive.
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned)
        for label in range(1, num_labels):
            if stats[label, cv2.CC_STAT_AREA] < 4:
                cleaned[labels == label] = 0

        # Horizontal projection: fraction of ink pixels per row
        row_sums = np.sum(cleaned == 255, axis=1) / float(w)

        # Detect active ink bands with sensitive energy threshold
        is_active = row_sums > energy_threshold
        raw_bands: list[tuple[int, int]] = []
        in_band = False
        start_y = 0

        for y, active in enumerate(is_active):
            if active and not in_band:
                in_band = True
                start_y = y
            elif not active and in_band:
                in_band = False
                # Verify band contains meaningful ink (ignore single isolated noise pixels)
                band_ink = np.sum(cleaned[start_y:y, :] == 255)
                if band_ink >= 50:
                    raw_bands.append((start_y, y))

        if in_band:
            band_ink = np.sum(cleaned[start_y:h, :] == 255)
            if band_ink >= 50:
                raw_bands.append((start_y, h))

        if not raw_bands:
            return [(0, h)]

        # Merge adjacent bands separated by small whitespace gaps (<= min_gap_px)
        merged_blocks: list[tuple[int, int]] = []
        curr_start, curr_end = raw_bands[0]

        for next_start, next_end in raw_bands[1:]:
            gap = next_start - curr_end
            if gap <= min_gap_px:
                curr_end = next_end
            else:
                merged_blocks.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end

        merged_blocks.append((curr_start, curr_end))

        # Filter out purely decorative 1D margin rules (e.g. thin header/footer divider < 12px at margins)
        filtered_blocks: list[tuple[int, int]] = []
        for sy, ey in merged_blocks:
            bh = ey - sy
            rel_sy = sy / float(h)
            rel_ey = ey / float(h)
            # If it's a 1-7px thin horizontal rule right at the top/bottom margin, skip it
            if bh < 12 and (rel_ey < 0.08 or rel_sy > 0.96):
                logger.debug("Filtered thin margin rule", y_start=sy, y_end=ey, height=bh)
                continue
            filtered_blocks.append((sy, ey))

        return filtered_blocks if filtered_blocks else [(0, h)]

    def _validate_ink_coverage(
        self,
        gray: np.ndarray,
        regions_y_ranges: list[tuple[int, int]],
    ) -> float:
        """Calculate the percentage of total page ink captured by the detected region bands."""
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        total_ink = np.sum(thresh == 255)
        if total_ink == 0:
            return 100.0

        covered_mask = np.zeros_like(thresh)
        for sy, ey in regions_y_ranges:
            covered_mask[sy:ey, :] = 255

        covered_ink = np.sum((thresh == 255) & (covered_mask == 255))
        coverage_pct = float(covered_ink / total_ink * 100.0)
        return coverage_pct

    def _classify_region_content(
        self,
        region_crop_gray: np.ndarray,
        region_crop_color: np.ndarray | None = None,
    ) -> tuple[RegionType, float]:
        """
        Multi-signal heuristic classifier for region type.
        """
        h, w = region_crop_gray.shape[:2]

        if h < 10 or w < 10:
            return RegionType.UNKNOWN, 0.0

        diagram_score, debug = _compute_structural_diagram_score(region_crop_gray, region_crop_color)

        if diagram_score >= self.diagram_confidence_threshold:
            region_type = RegionType.DIAGRAM
            confidence = diagram_score
        else:
            region_type = RegionType.ANSWER_TEXT
            confidence = 1.0 - diagram_score

        logger.debug(
            "Region classification",
            region_type=region_type.value,
            diagram_score=round(diagram_score, 3),
            confidence=round(confidence, 3),
            threshold=self.diagram_confidence_threshold,
            **{k: v for k, v in debug.items() if k != "final_score"},
        )

        return region_type, confidence

    def crop_and_save_region(
        self,
        full_img: Image.Image,
        bbox: BoundingBox,
        submission_id: str,
        page_number: int,
        region_idx: int,
        save_to_disk: bool = True,
    ) -> tuple[str, str]:
        """Crop region from full image, compute hash, and save PNG."""
        w, h = full_img.size
        left, top, right, bottom = bbox.to_pixel_coords(w, h)

        # Ensure minimal valid crop
        left = max(0, min(left, w - 1))
        top = max(0, min(top, h - 1))
        right = max(left + 1, min(right, w))
        bottom = max(top + 1, min(bottom, h))

        cropped = full_img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        crop_bytes = buf.getvalue()
        crop_hash = calculate_bytes_hash(crop_bytes)

        crop_path_str = ""
        if save_to_disk:
            self.crops_output_dir.mkdir(parents=True, exist_ok=True)
            dest = self.crops_output_dir / f"{submission_id}_p{page_number:02d}_r{region_idx:02d}_{crop_hash[:8]}.png"
            with open(dest, "wb") as f:
                f.write(crop_bytes)
            crop_path_str = str(dest)

        return crop_path_str, crop_hash

    def segment_page(
        self,
        preprocessed_page: PreprocessedPage,
        save_crops: bool = True,
        use_original_image: bool = True,
    ) -> PageSegmentationResult:
        """
        Segment a preprocessed page into distinct question/diagram regions.
        Preserves complete ink coverage without dropping single lines or continuation text.
        """
        img_path = Path(preprocessed_page.preprocessed_image_path)
        orig_img_path = Path(preprocessed_page.original_image_path)

        if not img_path.exists() and orig_img_path.exists():
            img_path = orig_img_path

        if not img_path.exists():
            raise SegmentationError(
                f"Source image for segmentation not found: {img_path}",
                details={"page_number": preprocessed_page.page_number},
            )

        try:
            # Use original high-quality image for crops if available, preprocessed for layout detection
            source_img = Image.open(orig_img_path if (use_original_image and orig_img_path.exists()) else img_path).convert("RGB")
            prep_img = Image.open(img_path).convert("RGB")
            w, h = prep_img.size
            color_np = np.array(prep_img)
            gray = cv2.cvtColor(color_np, cv2.COLOR_RGB2GRAY)

            # Find horizontal slice blocks with sensitive energy threshold and gap merging
            gap_px = max(40, int(h * 0.018))  # ~60-70px on high-DPI page
            splits = self._find_horizontal_splits(
                gray,
                min_gap_px=gap_px,
                energy_threshold=0.0015,
            )

            # Validate ink coverage
            coverage_pct = self._validate_ink_coverage(gray, splits)
            if coverage_pct < 98.0:
                logger.warning(
                    "Segmentation ink coverage below 98%",
                    page_number=preprocessed_page.page_number,
                    coverage_pct=round(coverage_pct, 2),
                )

            regions: list[QuestionRegion] = []
            has_diagrams = False
            prev_y_max_px = 0

            for idx, (y_start, y_end) in enumerate(splits, start=1):
                # Small vertical padding (1.5%) — but a padded region must never
                # bleed into the ink band of its neighbor, otherwise adjacent
                # crops duplicate the same lines at their shared boundary (which
                # makes OCR read continuation lines twice). Padding is therefore
                # clamped to the previous region's end and the next band's start,
                # and a forward monotonicity pass keeps the sequence non-overlapping.
                pad_y = int(h * 0.015)
                next_band_start = splits[idx][0] if idx < len(splits) else h
                y_min_px = max(prev_y_max_px, y_start - pad_y)
                y_max_px = min(next_band_start, y_end + pad_y)
                if y_max_px < y_min_px:
                    y_max_px = y_min_px  # degenerate sliver: collapse, never invert
                prev_y_max_px = y_max_px

                bbox = BoundingBox(
                    x_min=0.0,
                    y_min=round(y_min_px / float(h), 4),
                    x_max=1.0,
                    y_max=round(y_max_px / float(h), 4),
                )

                # Classify content
                region_crop_gray = gray[y_min_px:y_max_px, :]
                region_crop_color = color_np[y_min_px:y_max_px, :]
                region_type, classification_confidence = self._classify_region_content(
                    region_crop_gray, region_crop_color
                )

                if region_type == RegionType.DIAGRAM:
                    has_diagrams = True

                region_id = f"REG-P{preprocessed_page.page_number:02d}-{idx:02d}"

                # Save crop from original RGB source image
                crop_path, crop_hash = self.crop_and_save_region(
                    full_img=source_img,
                    bbox=bbox,
                    submission_id=preprocessed_page.submission_id,
                    page_number=preprocessed_page.page_number,
                    region_idx=idx,
                    save_to_disk=save_crops,
                )

                region = QuestionRegion(
                    region_id=region_id,
                    page_number=preprocessed_page.page_number,
                    submission_id=preprocessed_page.submission_id,
                    question_id=None,
                    bbox=bbox,
                    region_type=region_type,
                    classification_confidence=classification_confidence,
                    reading_order=idx,
                    continues_on_next_page=False,
                    crop_image_path=crop_path,
                    crop_image_hash=crop_hash,
                    segmentation_confidence=round(coverage_pct / 100.0, 3),
                )
                regions.append(region)

            logger.info(
                "Page segmentation complete",
                page_number=preprocessed_page.page_number,
                regions_found=len(regions),
                has_diagrams=has_diagrams,
                coverage_pct=round(coverage_pct, 2),
            )

            return PageSegmentationResult(
                submission_id=preprocessed_page.submission_id,
                page_number=preprocessed_page.page_number,
                regions=regions,
                source_page_hash=preprocessed_page.preprocessed_page_hash,
                has_diagrams=has_diagrams,
                layout_type="single_column",
            )

        except Exception as e:
            raise SegmentationError(
                f"Segmentation failed for page {preprocessed_page.page_number}: {e}",
                details={"page_number": preprocessed_page.page_number},
            ) from e
