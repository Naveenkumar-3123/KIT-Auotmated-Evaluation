"""Module 11: Answer Reconstruction Service."""

import uuid

from answer_eval.agents.diagram.schemas import DiagramResult
from answer_eval.agents.ocr.agent import count_words_deterministic
from answer_eval.agents.ocr.schemas import OCRResult, OCRUncertainSpan
from answer_eval.agents.reconstruction.schemas import (
    AnswerSegment,
    CanonicalStructuredAnswer,
)
from answer_eval.core.errors import ReconstructionError
from answer_eval.core.logging import get_logger
from answer_eval.core.provenance import Provenance
from answer_eval.processing.segmentation.schemas import QuestionRegion

logger = get_logger("agents.reconstruction")


class ReconstructionService:
    """Reconstructs multi-page continuous answers while preserving exact immutable raw OCR and provenance."""

    def reconstruct_answer(
        self,
        submission_id: str,
        question_id: str,
        ocr_results: list[tuple[QuestionRegion, OCRResult]],
        diagram_results: list[tuple[QuestionRegion, DiagramResult]] | None = None,
    ) -> CanonicalStructuredAnswer:
        """
        Reconstruct a single complete answer from ordered OCR segments and diagrams.
        """
        if not ocr_results and not diagram_results:
            raise ReconstructionError(
                f"Cannot reconstruct answer '{question_id}' without OCR or diagram results.",
                details={"submission_id": submission_id, "question_id": question_id},
            )

        logger.info(
            "Reconstructing canonical answer",
            submission_id=submission_id,
            question_id=question_id,
            ocr_segment_count=len(ocr_results),
            diagram_count=len(diagram_results or []),
        )

        # Sort OCR results by (page_number, reading_order)
        sorted_ocr = sorted(
            ocr_results,
            key=lambda item: (item[0].page_number, item[0].reading_order),
        )

        segments: list[AnswerSegment] = []
        raw_text_parts: list[str] = []
        source_pages_set: set[int] = set()
        uncertainties: list[OCRUncertainSpan] = []
        flags: list[str] = []
        primary_model_id = "unknown"
        primary_quant = None
        source_image_hashes: list[str] = []

        for idx, (region, ocr) in enumerate(sorted_ocr, start=1):
            source_pages_set.add(region.page_number)
            if ocr.raw_text.strip():
                raw_text_parts.append(ocr.raw_text.strip())

            segments.append(
                AnswerSegment(
                    page_number=region.page_number,
                    region_id=region.region_id,
                    reading_order=idx,
                    raw_text=ocr.raw_text,
                    crop_image_path=region.crop_image_path,
                )
            )

            uncertainties.extend(ocr.uncertain_spans)
            flags.extend(ocr.flags)
            primary_model_id = ocr.provenance.model_id
            primary_quant = ocr.provenance.quantization
            source_image_hashes.append(ocr.provenance.source_image_hash)

        # Process associated diagrams
        diagram_objs: list[DiagramResult] = []
        if diagram_results:
            for region, diag in diagram_results:
                source_pages_set.add(region.page_number)
                diagram_objs.append(diag)
                source_image_hashes.append(diag.provenance.source_image_hash)
                if not primary_model_id or primary_model_id == "unknown":
                    primary_model_id = diag.provenance.model_id
                    primary_quant = diag.provenance.quantization

        # Concatenate raw text with newline preservation
        complete_raw_text = "\n\n".join(raw_text_parts)
        word_count = count_words_deterministic(complete_raw_text)
        sorted_pages = sorted(list(source_pages_set))

        # Build comprehensive provenance
        provenance = Provenance(
            submission_id=submission_id,
            page_number=sorted_pages[0] if sorted_pages else 1,
            question_id=question_id,
            source_image_hash=",".join(source_image_hashes),
            model_id=primary_model_id,
            quantization=primary_quant,
            prompt_version="reconstruct_v1",
            request_id=f"reconstruct-{uuid.uuid4().hex[:8]}",
            extra_metadata={"source_pages": sorted_pages},
        )

        canonical = CanonicalStructuredAnswer(
            submission_id=submission_id,
            question_id=question_id,
            source_pages=sorted_pages,
            raw_text=complete_raw_text,
            normalized_text=None,  # Preserved as None initially
            word_count=word_count,
            segments=segments,
            diagrams=diagram_objs,
            uncertainties=uncertainties,
            flags=list(set(flags)),
            provenance=provenance,
        )

        logger.info(
            "Canonical answer reconstructed successfully",
            question_id=question_id,
            word_count=word_count,
            pages=sorted_pages,
            segments=len(segments),
            diagrams=len(diagram_objs),
        )

        return canonical
