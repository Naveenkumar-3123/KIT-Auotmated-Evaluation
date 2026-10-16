"""Image quality analysis module using OpenCV and NumPy."""

import cv2
import numpy as np
from PIL import Image

from answer_eval.core.logging import get_logger
from answer_eval.processing.image.schemas import ImageQualityMetrics

logger = get_logger("processing.image.quality")


class ImageQualityAnalyzer:
    """Measures blur, brightness, contrast, and skew angle of document page images."""

    def __init__(
        self,
        blur_threshold: float = 80.0,
        low_contrast_threshold: float = 30.0,
        low_brightness_threshold: float = 90.0,
        high_brightness_threshold: float = 245.0,
        high_skew_threshold: float = 5.0,
    ) -> None:
        self.blur_threshold = blur_threshold
        self.low_contrast_threshold = low_contrast_threshold
        self.low_brightness_threshold = low_brightness_threshold
        self.high_brightness_threshold = high_brightness_threshold
        self.high_skew_threshold = high_skew_threshold

    def analyze(self, image: Image.Image | np.ndarray) -> ImageQualityMetrics:
        """Calculate quality metrics and return ImageQualityMetrics with warning flags."""
        np_img = np.array(image) if isinstance(image, Image.Image) else image

        # Ensure grayscale
        gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY) if len(np_img.shape) == 3 else np_img

        # 1. Blur score: Laplacian variance
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        blur_score = round(float(laplacian.var()), 2)

        # 2. Brightness score: Mean pixel intensity
        brightness_score = round(float(np.mean(gray)), 2)

        # 3. Contrast score: Standard deviation of pixel intensities
        contrast_score = round(float(np.std(gray)), 2)

        # 4. Estimated skew angle
        skew_angle = self.estimate_skew_angle(gray)

        # 5. Quality warning flags
        flags: list[str] = []
        if blur_score < self.blur_threshold:
            flags.append(f"BLURRY (variance {blur_score} < {self.blur_threshold})")
        if contrast_score < self.low_contrast_threshold:
            flags.append(f"LOW_CONTRAST (std {contrast_score} < {self.low_contrast_threshold})")
        if brightness_score < self.low_brightness_threshold:
            flags.append(f"TOO_DARK (mean {brightness_score} < {self.low_brightness_threshold})")
        elif brightness_score > self.high_brightness_threshold:
            flags.append(f"WASHED_OUT (mean {brightness_score} > {self.high_brightness_threshold})")
        if abs(skew_angle) > self.high_skew_threshold:
            flags.append(f"HIGH_SKEW ({skew_angle:.1f}° > {self.high_skew_threshold}°)")

        return ImageQualityMetrics(
            blur_score=blur_score,
            brightness_score=brightness_score,
            contrast_score=contrast_score,
            estimated_skew_degrees=skew_angle,
            quality_flags=flags,
        )

    def estimate_skew_angle(self, gray: np.ndarray) -> float:
        """Estimate document skew angle in degrees using thresholding and Hough lines."""
        try:
            # Invert threshold so text is white on black
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            # Detect lines using Probabilistic Hough Transform
            lines = cv2.HoughLinesP(
                thresh,
                rho=1,
                theta=np.pi / 180,
                threshold=100,
                minLineLength=gray.shape[1] // 8,
                maxLineGap=20,
            )

            if lines is None or len(lines) == 0:
                return 0.0

            angles: list[float] = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                if x2 == x1:
                    continue
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                # Only consider near-horizontal lines (-30 to +30 degrees)
                if -30.0 <= angle <= 30.0:
                    angles.append(angle)

            if not angles:
                return 0.0

            median_angle = float(np.median(angles))
            return round(median_angle, 2)

        except Exception as e:
            logger.debug("Skew estimation failed", error=str(e))
            return 0.0
