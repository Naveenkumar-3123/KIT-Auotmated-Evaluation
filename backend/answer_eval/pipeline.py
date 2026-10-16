"""End-to-End Evaluation Pipeline: PDF -> Preprocessing -> Segmentation -> OCR/Diagram -> Reconstruction -> Canonical JSON."""

import uuid
from pathlib import Path
from typing import Any

from answer_eval.agents.diagram.agent import DiagramAgent
from answer_eval.agents.ocr.agent import OCRAgent
from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.agents.reconstruction.service import ReconstructionService
from answer_eval.core.logging import bind_context, clear_context, get_logger
from answer_eval.inference.provider import InferenceProvider
from answer_eval.processing.image.preprocessing import ImagePreprocessor
from answer_eval.processing.pdf.processor import PDFProcessor
from answer_eval.processing.segmentation.schemas import RegionType
from answer_eval.processing.segmentation.segmenter import QuestionSegmenter

logger = get_logger("pipeline")


class EvaluationPipeline:
    """Complete perception pipeline converting answer sheet PDFs to Canonical Structured JSON."""

    def __init__(
        self,
        inference_provider: InferenceProvider,
        pdf_processor: PDFProcessor | None = None,
        image_preprocessor: ImagePreprocessor | None = None,
        question_segmenter: QuestionSegmenter | None = None,
        reconstruction_service: ReconstructionService | None = None,
    ) -> None:
        self.provider = inference_provider
        self.pdf_processor = pdf_processor or PDFProcessor()
        self.image_preprocessor = image_preprocessor or ImagePreprocessor()
        self.question_segmenter = question_segmenter or QuestionSegmenter()
        self.ocr_agent = OCRAgent(inference_provider=self.provider)
        self.diagram_agent = DiagramAgent(inference_provider=self.provider)
        self.reconstruction_service = reconstruction_service or ReconstructionService()

    async def process_submission(
        self,
        pdf_path: str | Path,
        submission_id: str | None = None,
    ) -> list[CanonicalStructuredAnswer]:
        """
        Execute full perception pipeline on an answer sheet PDF document:
        1. PDF Processing -> PageImages
        2. Image Preprocessing -> PreprocessedPages
        3. Question Segmentation -> QuestionRegions
        4. OCR / Diagram Perception Agents -> OCRResults & DiagramResults
        5. Answer Reconstruction -> CanonicalStructuredAnswers
        """
        sub_id = submission_id or f"SUB-{uuid.uuid4().hex[:8].upper()}"
        bind_context(submission_id=sub_id)
        logger.info("Starting submission evaluation pipeline", pdf_path=str(pdf_path), submission_id=sub_id)

        try:
            # Step 1: PDF Processing
            pdf_doc = self.pdf_processor.process_pdf(pdf_path, submission_id=sub_id)

            # Step 2 & 3: Preprocess and segment each page
            all_ocr_results: list[tuple[Any, Any]] = []
            all_diagram_results: list[tuple[Any, Any]] = []

            for page_img in pdf_doc.pages:
                bind_context(page_number=page_img.page_number)

                # Preprocessing
                prep_page = self.image_preprocessor.preprocess_page(page_img)

                # Segmentation
                seg_result = self.question_segmenter.segment_page(prep_page)

                # Step 4: Run perception agents on each region
                for region in seg_result.regions:
                    bind_context(region_id=region.region_id)

                    if region.region_type == RegionType.DIAGRAM:
                        diag_res = await self.diagram_agent.extract_diagram(region)
                        all_diagram_results.append((region, diag_res))
                    elif region.region_type == RegionType.MIXED:
                        # Process both OCR and diagram on mixed region
                        ocr_res = await self.ocr_agent.extract_text(region)
                        diag_res = await self.diagram_agent.extract_diagram(region)
                        all_ocr_results.append((region, ocr_res))
                        all_diagram_results.append((region, diag_res))
                    else:  # ANSWER_TEXT or UNKNOWN
                        ocr_res = await self.ocr_agent.extract_text(region)
                        all_ocr_results.append((region, ocr_res))

            # Step 5: Group and Reconstruct Answers
            # If regions had explicit question_id, group by that; otherwise reconstruct sequential answer
            reconstructed_answers: list[CanonicalStructuredAnswer] = []

            if all_ocr_results or all_diagram_results:
                # Group by question_id or treat as primary answer Q1
                q_groups: dict[str, list[tuple[Any, Any]]] = {}
                d_groups: dict[str, list[tuple[Any, Any]]] = {}

                for r, o in all_ocr_results:
                    qid = r.question_id or "Q1"
                    q_groups.setdefault(qid, []).append((r, o))

                for r, d in all_diagram_results:
                    qid = r.question_id or "Q1"
                    d_groups.setdefault(qid, []).append((r, d))

                all_qids = sorted(list(set(list(q_groups.keys()) + list(d_groups.keys()))))

                for qid in all_qids:
                    ans = self.reconstruction_service.reconstruct_answer(
                        submission_id=sub_id,
                        question_id=qid,
                        ocr_results=q_groups.get(qid, []),
                        diagram_results=d_groups.get(qid, []),
                    )
                    reconstructed_answers.append(ans)

            logger.info(
                "Evaluation pipeline completed successfully",
                submission_id=sub_id,
                total_reconstructed_answers=len(reconstructed_answers),
            )

            return reconstructed_answers

        finally:
            clear_context()
