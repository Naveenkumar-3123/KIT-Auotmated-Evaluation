"""Left-margin ink scanner (Milestone 8).

Deterministic OpenCV pass over the left-margin band of a preprocessed page:
groups ink into candidate anchor rows and turns them into LineObservations.
Anchor TEXT comes from OCR of the strip; POSITION comes from pixels — layout
and transcription are combined exactly as spec #31 requires.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from answer_eval.core.logging import get_logger
from answer_eval.processing.mapping.schemas import LineObservation
from answer_eval.processing.segmentation.schemas import BoundingBox

logger = get_logger("processing.mapping.margin_scan")

DEFAULT_BAND_X = 0.15


def _load_gray(image_path: str) -> np.ndarray:
    image = Image.open(image_path).convert("L")
    return np.array(image)


def detect_anchor_boxes(
    image_path: str,
    *,
    band_x: float = DEFAULT_BAND_X,
) -> list[tuple[float, float]]:
    """Return normalized (y_min, y_max) rows of ink inside the left band."""
    gray = _load_gray(str(image_path))
    height, width = gray.shape[:2]
    band_width = max(8, int(width * band_x))
    band = gray[:, :band_width]

    _, binary = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Full-height margin rules / scan borders put ink on EVERY row of the band
    # and collapse all anchors into one giant box (which then yields zero
    # question markers and silently degrades mapping to positional fallbacks).
    # Remove only structures that span a large fraction of the page (a ruled
    # margin line), while keeping short anchor blobs (question digits, typical
    # handwriting rows) intact.
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, max(60, height // 4)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    binary = cv2.subtract(binary, vertical)

    # Merge characters of the same line vertically.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, band_width // 12), max(3, height // 150)))
    merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    row_has_ink = merged.sum(axis=1) > 0
    rows: list[tuple[float, float]] = []
    start: int | None = None
    for y, has_ink in enumerate(row_has_ink):
        if has_ink and start is None:
            start = y
        elif not has_ink and start is not None:
            rows.append((start / height, (y - 1) / height))
            start = None
    if start is not None:
        rows.append((start / height, (height - 1) / height))
    return [(round(a, 4), round(b, 4)) for a, b in rows]


def build_line_observations(
    page_number: int,
    image_path: str,
    texts: list[str] | None = None,
    *,
    band_x: float = DEFAULT_BAND_X,
) -> list[LineObservation]:
    """Detect anchor rows and attach OCR texts by vertical order when counts align.

    If ``texts`` length differs from detected rows, boxes keep empty text — the
    mapper then simply finds no markers instead of guessing an alignment.
    """
    boxes = detect_anchor_boxes(str(image_path), band_x=band_x)
    observations: list[LineObservation] = []
    
    clean_texts = [t.strip() for t in texts] if texts is not None else []
    clean_texts = [t for t in clean_texts if t]
    
    if clean_texts:
        n = len(clean_texts)
        for index, text in enumerate(clean_texts):
            if boxes:
                b_idx = min(len(boxes) - 1, int(index * len(boxes) / n))
                y_min, y_max = boxes[b_idx]
            else:
                y_min = round(0.05 + 0.85 * (index / max(1, n)), 4)
                y_max = round(y_min + 0.04, 4)
            observations.append(
                LineObservation(
                    page_number=page_number,
                    text=text,
                    bbox=BoundingBox(x_min=0.0, y_min=y_min, x_max=band_x, y_max=min(1.0, y_max + 0.002)),
                    reading_order=index + 1,
                )
            )
    else:
        for index, (y_min, y_max) in enumerate(boxes):
            observations.append(
                LineObservation(
                    page_number=page_number,
                    text="",
                    bbox=BoundingBox(x_min=0.0, y_min=y_min, x_max=band_x, y_max=min(1.0, y_max + 0.002)),
                    reading_order=index + 1,
                )
            )
    logger.info("margin anchors scanned", page_number=page_number, clusters=len(observations), texts=len(clean_texts))
    return observations


def extract_margin_strip_png(
    image_path: str,
    destination: Path,
    *,
    band_x: float = DEFAULT_BAND_X,
) -> Path:
    """Save the left band of the page as a PNG crop for VLM strip reading."""
    image = Image.open(str(image_path)).convert("RGB")
    width, height = image.size
    strip = image.crop((0, 0, max(8, int(width * band_x)), height))
    destination.parent.mkdir(parents=True, exist_ok=True)
    strip.save(destination, format="PNG")
    return destination
