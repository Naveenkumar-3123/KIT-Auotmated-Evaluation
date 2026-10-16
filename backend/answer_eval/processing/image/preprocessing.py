"""Module 5: Conservative image preprocessing pipeline for student handwriting answer sheets."""

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from answer_eval.core.errors import ImageProcessingError
from answer_eval.core.hashing import calculate_bytes_hash
from answer_eval.core.logging import get_logger
from answer_eval.processing.image.quality import ImageQualityAnalyzer
from answer_eval.processing.image.schemas import (
    PreprocessedPage,
    PreprocessingConfig,
)
from answer_eval.processing.pdf.schemas import PageImage

logger = get_logger("processing.image.preprocessor")


class ImagePreprocessor:
    """Performs conservative, testable image preprocessing on answer sheet pages."""

    def __init__(
        self,
        config: PreprocessingConfig | None = None,
        output_dir: Path | str | None = None,
    ) -> None:
        self.config = config or PreprocessingConfig()
        self.output_dir = Path(output_dir or "data/preprocessed_pages")
        self.quality_analyzer = ImageQualityAnalyzer()

    def deskew_image(self, img_np: np.ndarray, angle: float) -> np.ndarray:
        """Rotate image by negative skew angle with white border padding."""
        if abs(angle) < 0.2 or abs(angle) > self.config.max_deskew_angle:
            return img_np

        h, w = img_np.shape[:2]
        center = (w // 2, h // 2)
        rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        # Warp with white background (255)
        rotated = cv2.warpAffine(
            img_np,
            rot_mat,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255) if len(img_np.shape) == 3 else 255,
        )
        return rotated

    def remove_scanner_borders(self, img_np: np.ndarray, threshold: int = 30) -> np.ndarray:
        """Conservatively crop solid black/dark scanner border bands from outer 5% margins."""
        h, w = img_np.shape[:2]
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY) if len(img_np.shape) == 3 else img_np

        max_crop_y = int(h * 0.05)
        max_crop_x = int(w * 0.05)

        top = 0
        while top < max_crop_y and np.mean(gray[top, :]) < threshold:
            top += 1

        bottom = h
        while bottom > (h - max_crop_y) and np.mean(gray[bottom - 1, :]) < threshold:
            bottom -= 1

        left = 0
        while left < max_crop_x and np.mean(gray[:, left]) < threshold:
            left += 1

        right = w
        while right > (w - max_crop_x) and np.mean(gray[:, right - 1]) < threshold:
            right -= 1

        if top > 0 or bottom < h or left > 0 or right < w:
            return img_np[top:bottom, left:right]
        return img_np

    def apply_contrast_clahe(self, img_np: np.ndarray) -> np.ndarray:
        """Apply Contrast Limited Adaptive Histogram Equalization to enhance faint pencil/pen ink."""
        if len(img_np.shape) == 3:
            # Convert RGB to LAB, apply CLAHE to L channel only
            lab = cv2.cvtColor(img_np, cv2.COLOR_RGB2LAB)
            l_chan, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(
                clipLimit=self.config.clahe_clip_limit,
                tileGridSize=(8, 8),
            )
            cl = clahe.apply(l_chan)
            merged_lab = cv2.merge((cl, a, b))
            return cv2.cvtColor(merged_lab, cv2.COLOR_LAB2RGB)
        else:
            clahe = cv2.createCLAHE(
                clipLimit=self.config.clahe_clip_limit,
                tileGridSize=(8, 8),
            )
            return clahe.apply(img_np)

    def normalize_resolution(self, img_np: np.ndarray) -> np.ndarray:
        """Downscale oversized page images to max_dimension_px while preserving aspect ratio."""
        h, w = img_np.shape[:2]
        max_dim = self.config.max_dimension_px
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            new_w = int(w * scale)
            new_h = int(h * scale)
            return cv2.resize(img_np, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return img_np

    def preprocess_page(
        self,
        page_image: PageImage,
        save_to_disk: bool = True,
    ) -> PreprocessedPage:
        """
        Execute full conservative preprocessing pipeline on a PageImage.
        Preserves original image file and writes preprocessed image.
        """
        original_path = Path(page_image.image_path)
        if not original_path.exists():
            raise ImageProcessingError(
                f"Source page image not found at: {original_path}",
                details={"page_number": page_image.page_number},
            )

        try:
            pil_img = Image.open(original_path).convert("RGB")
            img_np = np.array(pil_img)
            applied_ops: list[str] = []

            # 1. Initial quality assessment
            quality_metrics = self.quality_analyzer.analyze(img_np)

            # 2. Deskew if enabled and needed
            if self.config.deskew_enabled and abs(quality_metrics.estimated_skew_degrees) > 0.3:
                img_np = self.deskew_image(img_np, quality_metrics.estimated_skew_degrees)
                applied_ops.append(f"deskew({quality_metrics.estimated_skew_degrees:.1f}°)")

            # 3. Border removal if enabled
            if self.config.border_removal_enabled:
                prev_shape = img_np.shape
                img_np = self.remove_scanner_borders(img_np)
                if img_np.shape != prev_shape:
                    applied_ops.append("border_removal")

            # 4. Light noise reduction (Gaussian blur)
            if self.config.noise_reduction_enabled:
                k = self.config.noise_reduction_kernel
                if k > 1:
                    img_np = cv2.GaussianBlur(img_np, (k, k), 0)
                    applied_ops.append(f"noise_reduction_k{k}")

            # 5. Contrast enhancement (CLAHE)
            if self.config.contrast_adjustment_enabled:
                img_np = self.apply_contrast_clahe(img_np)
                applied_ops.append("clahe_contrast")

            # 6. Resolution normalization
            if self.config.resolution_normalization_enabled:
                prev_dim = max(img_np.shape[:2])
                img_np = self.normalize_resolution(img_np)
                if max(img_np.shape[:2]) != prev_dim:
                    applied_ops.append(f"rescale_to_{max(img_np.shape[:2])}px")

            # 7. Grayscale conversion if requested
            if self.config.grayscale_enabled and len(img_np.shape) == 3:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                applied_ops.append("grayscale")

            # Re-analyze quality post-processing
            post_quality = self.quality_analyzer.analyze(img_np)

            # Convert to PIL & compute hash
            final_pil = Image.fromarray(img_np)
            buf = io.BytesIO()
            final_pil.save(buf, format="PNG")
            preprocessed_bytes = buf.getvalue()
            preprocessed_hash = calculate_bytes_hash(preprocessed_bytes)

            # Save to disk
            preprocessed_path_str = ""
            if save_to_disk:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                dest_file = (
                    self.output_dir
                    / f"{page_image.submission_id}_prep_p{page_image.page_number:03d}_{preprocessed_hash[:8]}.png"
                )
                with open(dest_file, "wb") as f:
                    f.write(preprocessed_bytes)
                preprocessed_path_str = str(dest_file)

            final_h, final_w = img_np.shape[:2]

            logger.info(
                "Page preprocessing complete",
                page_number=page_image.page_number,
                operations=applied_ops,
                final_resolution=f"{final_w}x{final_h}",
            )

            return PreprocessedPage(
                submission_id=page_image.submission_id,
                page_number=page_image.page_number,
                original_image_path=str(original_path),
                original_page_hash=page_image.page_hash,
                preprocessed_image_path=preprocessed_path_str,
                preprocessed_page_hash=preprocessed_hash,
                width_px=final_w,
                height_px=final_h,
                applied_operations=applied_ops,
                quality_metrics=post_quality,
            )

        except Exception as e:
            raise ImageProcessingError(
                f"Failed to preprocess page image {original_path}: {e}",
                details={"page_number": page_image.page_number},
            ) from e
