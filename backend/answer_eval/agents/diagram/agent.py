"""Module 10: Diagram Extraction Agent."""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from answer_eval.agents.diagram.schemas import (
    DiagramComponent,
    DiagramLabel,
    DiagramRelationship,
    DiagramResult,
    DiagramVisualQuality,
)
from answer_eval.agents.ocr.agent import OCRAgent
from answer_eval.core.errors import DiagramExtractionError, InferenceOutputValidationError
from answer_eval.core.logging import get_logger
from answer_eval.core.provenance import Provenance
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import ImageInput, InferenceRequest, ReasoningMode
from answer_eval.processing.segmentation.schemas import QuestionRegion, RegionType
from answer_eval.prompts.manager import PromptManager

logger = get_logger("agents.diagram")


class _DiagramStructuredPayload(BaseModel):
    """
    Internal Pydantic schema for diagram extraction JSON validation.

    diagram_present=False is the canonical signal that the supplied image
    does NOT contain a genuine visual diagram (e.g. it is handwriting with
    teacher correction marks).  The agent will automatically fall back to
    OCR extraction in this case.
    """

    diagram_present: bool = Field(
        default=False,
        description="True if a genuine visual diagram is visible; False for handwriting/text only",
    )
    diagram_type_guess: str = "unknown"
    labels: list[dict[str, Any]] = Field(default_factory=list)
    components: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    visual_quality: dict[str, Any] = Field(default_factory=dict)
    uncertain_elements: list[dict[str, str]] = Field(default_factory=list)


class DiagramAgent:
    """
    Extracts structural components, labels, and connections from diagram regions.

    If the model reports diagram_present=False, the agent falls back to OCR
    and returns a DiagramResult with diagram_present=False and the OCR text
    stored in fallback_ocr_text.  This prevents hallucination of diagram
    structure for handwriting-only regions.

    Does NOT evaluate academic correctness or assign marks.
    """

    def __init__(
        self,
        inference_provider: InferenceProvider,
        prompt_manager: PromptManager | None = None,
        ocr_agent: OCRAgent | None = None,
    ) -> None:
        self.provider = inference_provider
        self.prompt_manager = prompt_manager or PromptManager()
        # Optional OCR agent for fallback; created lazily if not supplied
        self._ocr_agent = ocr_agent

    def _get_ocr_agent(self) -> OCRAgent:
        if self._ocr_agent is None:
            self._ocr_agent = OCRAgent(
                inference_provider=self.provider,
                prompt_manager=self.prompt_manager,
            )
        return self._ocr_agent

    async def extract_diagram(
        self,
        region: QuestionRegion,
        task_name: str = "diagram",
    ) -> DiagramResult:
        """
        Execute diagram observation and structural extraction on a QuestionRegion.

        Returns DiagramResult in all non-fatal cases:
          - diagram_present=True  → full structured diagram data
          - diagram_present=False → fallback OCR text in fallback_ocr_text field

        Only raises DiagramExtractionError for unrecoverable failures (e.g. missing crop file).
        """
        request_id = f"diag-{uuid.uuid4().hex[:8]}"
        logger.info(
            "Executing diagram extraction",
            region_id=region.region_id,
            page_number=region.page_number,
            request_id=request_id,
            classification_confidence=region.classification_confidence,
        )

        if not region.crop_image_path:
            raise DiagramExtractionError(
                f"Region '{region.region_id}' has no crop image path.",
                details={"region_id": region.region_id},
            )

        prompt_text = self.prompt_manager.get_prompt_template(task_name)

        req = InferenceRequest(
            request_id=request_id,
            prompt=prompt_text,
            images=[ImageInput(image_path=region.crop_image_path, mime_type="image/png")],
            max_tokens=2048,
            temperature=0.1,
            reasoning_mode=ReasoningMode.NORMAL,
            metadata={
                "region_id": region.region_id,
                "submission_id": region.submission_id,
                "page_number": region.page_number,
            },
        )

        # -----------------------------------------------------------------------
        # Attempt structured diagram extraction
        # -----------------------------------------------------------------------
        structured_data: dict[str, Any] | None = None
        structured_failed = False
        last_error: str = ""

        try:
            resp = await self.provider.infer_structured(
                request=req,
                schema=_DiagramStructuredPayload,
                max_retries=2,
            )
            structured_data = resp.structured_data or {}

        except InferenceOutputValidationError as e:
            structured_failed = True
            last_error = str(e)
            logger.warning(
                "Diagram structured JSON validation failed — will attempt OCR fallback",
                region_id=region.region_id,
                request_id=request_id,
                error=last_error[:200],
            )

        except Exception as e:
            # Other inference errors (connectivity, timeout) — don't suppress
            raise DiagramExtractionError(
                f"Diagram agent failed on region {region.region_id}: {e}",
                details={"region_id": region.region_id, "request_id": request_id},
            ) from e

        # -----------------------------------------------------------------------
        # Check if model explicitly said "not a diagram" or if structured failed
        # -----------------------------------------------------------------------
        diagram_not_present = (
            structured_data is not None and not structured_data.get("diagram_present", True)
        )
        needs_ocr_fallback = structured_failed or diagram_not_present

        if diagram_not_present:
            logger.info(
                "Diagram agent: model reports no diagram present — routing to OCR fallback",
                region_id=region.region_id,
                request_id=request_id,
            )
        elif structured_failed:
            logger.warning(
                "Diagram agent: structured JSON failed after retries — routing to OCR fallback",
                region_id=region.region_id,
                request_id=request_id,
                last_error=last_error[:200],
            )

        # -----------------------------------------------------------------------
        # OCR fallback for non-diagram regions
        # -----------------------------------------------------------------------
        fallback_ocr_text: str | None = None
        if needs_ocr_fallback:
            try:
                ocr_agent = self._get_ocr_agent()
                # Build a temporary region reclassified as answer_text for OCR
                ocr_region = region.model_copy(update={"region_type": RegionType.ANSWER_TEXT})
                ocr_result = await ocr_agent.extract_text(ocr_region)
                fallback_ocr_text = ocr_result.raw_text.strip()
                logger.info(
                    "Diagram fallback OCR completed",
                    region_id=region.region_id,
                    word_count=ocr_result.word_count,
                )
            except Exception as ocr_err:
                logger.warning(
                    "Diagram fallback OCR also failed — region will be empty",
                    region_id=region.region_id,
                    error=str(ocr_err)[:200],
                )

            # Build a minimal provenance for the fallback result
            # (model_id not available from failed structured call — use empty)
            model_id = "unknown"
            quantization = None
            if structured_data is not None and resp is not None:
                model_id = resp.model_id
                quantization = resp.quantization

            provenance = Provenance(
                submission_id=region.submission_id,
                page_number=region.page_number,
                region_id=region.region_id,
                question_id=region.question_id,
                source_image_hash=region.crop_image_hash,
                source_image_path=region.crop_image_path,
                model_id=model_id,
                quantization=quantization,
                prompt_version="base_v1",
                request_id=request_id,
            )

            return DiagramResult(
                diagram_present=False,
                diagram_type_guess="none",
                labels=[],
                components=[],
                relationships=[],
                visual_quality=DiagramVisualQuality(),
                uncertain_elements=[],
                fallback_ocr_text=fallback_ocr_text,
                provenance=provenance,
                model_metadata={"fallback_reason": "not_a_diagram" if diagram_not_present else "structured_json_failed"},
            )

        # -----------------------------------------------------------------------
        # Normal path: structured diagram data is valid and diagram_present=True
        # -----------------------------------------------------------------------
        data = structured_data or {}
        type_guess = data.get("diagram_type_guess", "unknown")

        labels = [
            DiagramLabel(
                text=lbl.get("text", ""),
                uncertain=lbl.get("uncertain", False),
                location_hint=lbl.get("location_hint"),
            )
            for lbl in data.get("labels", [])
            if isinstance(lbl, dict)
        ]

        components = [
            DiagramComponent(
                type=c.get("type", "box"),
                label=c.get("label"),
                description=c.get("description", ""),
            )
            for c in data.get("components", [])
            if isinstance(c, dict)
        ]

        relationships = [
            DiagramRelationship(
                from_component=r.get("from_component", ""),
                to_component=r.get("to_component", ""),
                relationship_type=r.get("relationship_type", "arrow"),
                label=r.get("label"),
            )
            for r in data.get("relationships", [])
            if isinstance(r, dict)
        ]

        vq_raw = data.get("visual_quality", {})
        visual_quality = DiagramVisualQuality(
            legibility=vq_raw.get("legibility", "good"),
            label_clarity=vq_raw.get("label_clarity", "good"),
            completeness_appearance=vq_raw.get("completeness_appearance", "complete"),
        )

        uncertain_elements = data.get("uncertain_elements", [])

        provenance = Provenance(
            submission_id=region.submission_id,
            page_number=region.page_number,
            region_id=region.region_id,
            question_id=region.question_id,
            source_image_hash=region.crop_image_hash,
            source_image_path=region.crop_image_path,
            model_id=resp.model_id,
            quantization=resp.quantization,
            prompt_version="base_v1",
            request_id=request_id,
        )

        result = DiagramResult(
            diagram_present=True,
            diagram_type_guess=type_guess,
            labels=labels,
            components=components,
            relationships=relationships,
            visual_quality=visual_quality,
            uncertain_elements=uncertain_elements,
            fallback_ocr_text=None,
            provenance=provenance,
            model_metadata={
                "timing": resp.timing.model_dump(),
                "usage": resp.usage.model_dump(),
            },
        )

        logger.info(
            "Diagram extraction completed",
            region_id=region.region_id,
            labels_count=len(labels),
            components_count=len(components),
            relationships_count=len(relationships),
        )

        return result
