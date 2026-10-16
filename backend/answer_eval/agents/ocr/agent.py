"""Module 9: Exact OCR / Text Extraction Agent."""

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field

from answer_eval.agents.ocr.schemas import OCRResult, OCRUncertainSpan
from answer_eval.core.config import load_settings
from answer_eval.core.errors import OCRExtractionError
from answer_eval.core.logging import get_logger
from answer_eval.core.provenance import Provenance
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import ImageInput, InferenceRequest, InferenceResponse, ReasoningMode
from answer_eval.processing.segmentation.schemas import QuestionRegion
from answer_eval.prompts.manager import PromptManager

logger = get_logger("agents.ocr")


class _OCRStructuredPayload(BaseModel):
    """Internal Pydantic model for JSON output schema enforcement."""

    raw_text: str = Field(description="Exact verbatim transcription")
    lines: list[str] = Field(default_factory=list)
    uncertain_spans: list[dict[str, Any]] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


def count_words_deterministic(text: str) -> int:
    """Calculate deterministic word count from raw text."""
    tokens = text.strip().split()
    return len(tokens)


# Stop reasons that indicate the output budget was exhausted before natural completion.
GENERATION_LIMIT_REASONS = {"length", "max_tokens", "generation_limit"}


class OCRAgent:
    """
    Extracts verbatim student handwriting from question region crops.
    Strictly forbids spelling correction, grammar fixing, or academic interpretation.
    """

    def __init__(
        self,
        inference_provider: InferenceProvider,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self.provider = inference_provider
        self.prompt_manager = prompt_manager or PromptManager()

    @staticmethod
    def _validate_response(text: str, resp: InferenceResponse, min_valid_chars: int) -> str:
        """
        Validate a raw OCR inference response.

        Returns one of: 'success', 'empty_response', 'suspiciously_tiny', 'truncated'.
        Empty/whitespace-only output is never treated as a successful OCR result.
        """
        if not text:
            return "empty_response"
        if len(text) < min_valid_chars:
            return "suspiciously_tiny"
        if resp.stop_reason in GENERATION_LIMIT_REASONS:
            return "truncated"
        return "success"

    async def extract_text(
        self,
        region: QuestionRegion,
        task_name: str = "ocr",
    ) -> OCRResult:
        """Execute exact OCR extraction on a single QuestionRegion."""
        request_id = f"ocr-{uuid.uuid4().hex[:8]}"
        logger.info(
            "Executing OCR extraction",
            region_id=region.region_id,
            page_number=region.page_number,
            request_id=request_id,
        )

        if not region.crop_image_path:
            raise OCRExtractionError(
                f"Region '{region.region_id}' has no crop image path.",
                details={"region_id": region.region_id},
            )

        from pathlib import Path
        import json
        cache_dir = Path("data/ocr_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_sub_id = getattr(region, "submission_id", None) or "default"
        is_test_sub = str(safe_sub_id).startswith("SUB-")
        cache_file = cache_dir / f"{safe_sub_id}_{region.region_id}.json"
        if not is_test_sub and cache_file.exists():
            try:
                cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
                logger.info(
                    "[OCR-CACHED]",
                    segment=region.region_id,
                    characters=len(cached_data.get("raw_text", "")),
                )
                return OCRResult.model_validate(cached_data)
            except Exception:
                pass

        # Load centralized OCR inference configuration (thinking off, temp 0, budget, retries)
        ocr_cfg = load_settings().ocr
        max_attempts = max(1, ocr_cfg.max_attempts)

        # Load prompt template
        prompt_text = self.prompt_manager.get_prompt_template(task_name)

        req = InferenceRequest(
            request_id=request_id,
            prompt=prompt_text,
            images=[ImageInput(image_path=region.crop_image_path, mime_type="image/png")],
            max_tokens=ocr_cfg.num_predict,
            temperature=ocr_cfg.temperature,
            reasoning_mode=(
                ReasoningMode.DIRECT if not ocr_cfg.thinking_enabled else ReasoningMode.THINKING
            ),
            metadata={
                "region_id": region.region_id,
                "submission_id": region.submission_id,
                "page_number": region.page_number,
            },
        )

        try:
            # Execute inference with controlled validation retries (max_attempts total).
            resp: InferenceResponse | None = None
            raw_text = ""
            validation_status = "failed"
            for attempt in range(1, max_attempts + 1):
                resp = await self.provider.infer(request=req)
                raw_text = resp.text.strip()
                validation_status = self._validate_response(raw_text, resp, ocr_cfg.min_valid_chars)

                if validation_status in ("success", "truncated"):
                    # 'truncated' is deterministic for a fixed budget — retrying wastes time.
                    break

                if attempt < max_attempts:
                    logger.warning(
                        "OCR response invalid — controlled retry with same strict prompt",
                        region_id=region.region_id,
                        request_id=request_id,
                        attempt=attempt,
                        validation_status=validation_status,
                        stop_reason=resp.stop_reason,
                    )
                    req = req.model_copy(deep=True)
                    req.request_id = f"{request_id}-retry{attempt}"

            assert resp is not None  # loop always executes at least once

            lines: list[str] = []
            uncertain_spans: list[OCRUncertainSpan] = []
            flags: list[str] = []

            # Check if output is JSON formatted (e.g. from structured provider or mock)
            if raw_text.startswith("{") and raw_text.endswith("}"):
                import json

                try:
                    data = json.loads(raw_text)
                    raw_text = data.get("raw_text", raw_text).strip()
                    lines = data.get("lines", [raw_text])
                    for u in data.get("uncertain_spans", []):
                        if isinstance(u, dict):
                            uncertain_spans.append(
                                OCRUncertainSpan(
                                    text=u.get("text", ""),
                                    reason=u.get("reason", "ambiguous"),
                                    position_hint=u.get("position_hint"),
                                )
                            )
                    flags = data.get("flags", [])
                except Exception:
                    pass

            if not lines and raw_text:
                lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

            # Extract illegible, crossed out, and inserted tags from text if not already populated
            if not uncertain_spans and raw_text:
                # 1. Illegible tags
                for m in re.finditer(r"\[ILLEGIBLE\]", raw_text, re.IGNORECASE):
                    uncertain_spans.append(
                        OCRUncertainSpan(
                            text="[ILLEGIBLE]",
                            reason="illegible",
                            position_hint=f"offset {m.start()}",
                        )
                    )
                # 2. Crossed out tags
                for m in re.finditer(r"\[CROSSED OUT:\s*([^\]]+)\]", raw_text, re.IGNORECASE):
                    uncertain_spans.append(
                        OCRUncertainSpan(
                            text=m.group(1),
                            reason="crossed_out",
                            position_hint=f"offset {m.start()}",
                        )
                    )
                # 3. Inserted tags
                for m in re.finditer(r"\[INSERTED:\s*([^\]]+)\]", raw_text, re.IGNORECASE):
                    uncertain_spans.append(
                        OCRUncertainSpan(
                            text=m.group(1),
                            reason="inserted_text",
                            position_hint=f"offset {m.start()}",
                        )
                    )

            word_count = count_words_deterministic(raw_text)

            # Derive final status from validation — empty output is never a success.
            flags = list(flags)
            if validation_status == "success":
                status = "success"
            elif raw_text and (validation_status == "truncated" or resp.stop_reason in GENERATION_LIMIT_REASONS):
                # Text was produced but generation hit the output budget.
                status = "truncated"
                flags.append("generation_limit")
            else:
                status = "failed"

            # Build Provenance
            provenance = Provenance(
                submission_id=region.submission_id,
                page_number=region.page_number,
                region_id=region.region_id,
                question_id=region.question_id,
                source_image_hash=region.crop_image_hash,
                source_image_path=region.crop_image_path,
                model_id=resp.model_id,
                quantization=resp.quantization,
                prompt_version="base_v2_strict",
                request_id=request_id,
            )

            result = OCRResult(
                raw_text=raw_text,
                lines=lines,
                uncertain_spans=uncertain_spans,
                flags=flags,
                word_count=word_count,
                status=status,
                provenance=provenance,
                model_metadata={
                    "timing": resp.timing.model_dump(),
                    "usage": resp.usage.model_dump(),
                    "stop_reason": resp.stop_reason,
                    "thinking_disabled": resp.thinking_disabled,
                    "attempts": max_attempts if status == "failed" else 1,
                },
            )

            thinking_label = (
                "disabled" if resp.thinking_disabled else ("enabled" if resp.thinking_disabled is False else "unknown")
            )
            duration_s = round((resp.timing.total_inference_ms or 0.0) / 1000.0, 2)
            logger.info(
                "[OCR]",
                segment=region.region_id,
                model=resp.model_id,
                thinking=thinking_label,
                temperature=req.temperature,
                output_limit=req.max_tokens,
                duration=f"{duration_s}s",
                characters=len(raw_text),
                words=word_count,
                attempts=max_attempts if status in ("failed", "truncated") else 1,
                stop_reason=resp.stop_reason or "unknown",
                status=status.upper() if status == "failed" else status,
            )
            if status == "truncated":
                logger.warning(
                    "[OCR] truncated",
                    segment=region.region_id,
                    reason="generation_limit",
                    detail="Output budget exhausted before transcription completed; "
                    "consider adaptive segmentation for this region.",
                )

            if not is_test_sub:
                try:
                    cache_file.write_text(result.model_dump_json(), encoding="utf-8")
                except Exception:
                    pass

            return result

        except Exception as e:
            raise OCRExtractionError(
                f"OCR agent failed on region {region.region_id}: {e}",
                details={"region_id": region.region_id, "request_id": request_id},
            ) from e
