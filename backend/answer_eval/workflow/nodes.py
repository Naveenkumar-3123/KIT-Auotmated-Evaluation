"""LangGraph workflow nodes (Module 17).

Nodes are synchronous so the graph works with the durable SqliteSaver
checkpointer. Perception nodes reuse Modules 4-11 components unchanged; async
perception calls are bridged with asyncio. Every node is idempotent (skips work
already present in state) and failures are captured as normalized error records.
"""

import asyncio
import concurrent.futures
import hashlib
from typing import Any

from answer_eval.agents.diagram.agent import DiagramAgent
from answer_eval.agents.ocr.agent import OCRAgent
from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.core.errors import AnswerEvalError
from answer_eval.core.logging import get_logger
from answer_eval.grading.rubric import QuestionRubric
from answer_eval.grading.service import GradingService
from answer_eval.inference.provider import InferenceProvider
from answer_eval.workflow.state import EvaluationWorkflowState

logger = get_logger("workflow.nodes")

TOTAL_STAGES = 12


def _run_async(coro):
    """Bridge async perception/grading calls into sync nodes."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _error(state: dict, node: str, exc: Exception, permanent: bool) -> dict:
    record = {
        "node": node,
        "error_type": type(exc).__name__,
        "message": str(exc)[:500],
        "retryable": not permanent,
    }
    return {
        "errors": [*state.get("errors", []), record],
        "status": "failed_permanent" if permanent else "failed_retryable",
    }


def _advance(state: dict, stage: str, completed: int | None = None) -> dict:
    return {
        "current_stage": stage,
        "progress_completed": completed if completed is not None else state.get("progress_completed", 0),
        "status": "running",
    }


def compute_input_hash(pdf_path: str, rubrics: dict) -> str:
    """Content hash for idempotency / duplicate-execution detection."""
    h = hashlib.sha256()
    try:
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        pass
    import json

    h.update(json.dumps(rubrics, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def validate_submission(state: EvaluationWorkflowState) -> dict:
    """Permanent-input validation: missing PDF or invalid rubric never reaches the LLM."""
    import os

    pdf_path = state.get("pdf_path") or ""
    if not pdf_path:
        return _error(dict(state), "validate_submission", ValueError("No PDF path supplied"), permanent=True)
    if not os.path.isfile(pdf_path):
        return _error(
            dict(state),
            "validate_submission",
            FileNotFoundError(
                f"PDF not found: {pdf_path} (worker cwd: {os.getcwd()})"
            ),
            permanent=True,
        )
    for qid, r in (state.get("rubrics") or {}).items():
        try:
            QuestionRubric.model_validate(r)
        except Exception as e:
            return _error(
                dict(state), "validate_submission", ValueError(f"Invalid rubric for {qid}: {e}"), permanent=True
            )
    updates = _advance(dict(state), "validating", 1)
    updates["input_hash"] = compute_input_hash(pdf_path, state.get("rubrics") or {})
    return updates


def process_pdf(state: EvaluationWorkflowState) -> dict:
    if state.get("pdf_pages"):
        return {"current_stage": "rendering_pdf"}
    from answer_eval.processing.pdf.processor import PDFProcessor

    try:
        doc = PDFProcessor().process_pdf(state["pdf_path"], submission_id=state["submission_id"])
        return {**_advance(dict(state), "rendering_pdf", 2), "pdf_pages": len(doc.pages)}
    except Exception as e:
        return _error(dict(state), "process_pdf", e, permanent=isinstance(e, (ValueError, FileNotFoundError)))


def preprocess_and_segment(state: EvaluationWorkflowState) -> dict:
    """Modules 5 & 6 â€” existing preprocessor + segmenter, unchanged."""
    if state.get("regions_count"):
        return {"current_stage": "segmenting"}
    from answer_eval.processing.image.preprocessing import ImagePreprocessor
    from answer_eval.processing.pdf.processor import PDFProcessor
    from answer_eval.processing.segmentation.segmenter import QuestionSegmenter

    regions: list[Any] = []
    page_dumps: list[Any] = []
    try:
        doc = PDFProcessor().process_pdf(state["pdf_path"], submission_id=state["submission_id"])
        preprocessor = ImagePreprocessor()
        segmenter = QuestionSegmenter()
        for page_img in doc.pages:
            prep_page = preprocessor.preprocess_page(page_img)
            seg_result = segmenter.segment_page(prep_page)
            regions.extend(seg_result.regions)
            page_dumps.append(prep_page.model_dump())
    except Exception as e:
        return _error(dict(state), "preprocess_segment", e, permanent=False)

    return {
        **_advance(dict(state), "segmenting", 3),
        "regions_count": len(regions),
        "region_records": [r.model_dump() for r in regions],
        "page_records": page_dumps,
    }


def map_questions(state: EvaluationWorkflowState, provider: InferenceProvider) -> dict:
    """Milestone 7/8: cross-page question mapping before region OCR.

    Deterministic margin scan gives anchor POSITIONS; a narrow strip OCR per
    page gives anchor TEXT; the QuestionSpanMapper combines both with the
    rubric's valid question numbers. Ambiguous mappings are flagged, never
    silently assigned (spec #33).
    """
    if state.get("question_spans"):
        return {"current_stage": "mapping_questions"}
    page_records = state.get("page_records") or []
    region_records = state.get("region_records") or []
    if not page_records or not region_records:
        # Legacy/short-circuit flows: leave existing region question_ids alone.
        return {"current_stage": "mapping_questions"}

    import re
    import tempfile
    from pathlib import Path

    from answer_eval.agents.ocr.agent import OCRAgent
    from answer_eval.processing.image.schemas import PreprocessedPage
    from answer_eval.processing.mapping import QuestionSpanMapper, assign_regions
    from answer_eval.processing.mapping.margin_scan import build_line_observations, extract_margin_strip_png
    from answer_eval.processing.segmentation.schemas import PageSegmentationResult, QuestionRegion

    def _number_of(qid: str) -> int | None:
        match = re.fullmatch(r"[Qq](\d{1,3})", str(qid).strip())
        return int(match.group(1)) if match else None

    valid_numbers = sorted(
        {n for n in (_number_of(k) for k in (state.get("rubrics") or {})) if n is not None}
    )
    ocr_agent = OCRAgent(inference_provider=provider)
    lines_by_page: dict[int, list] = {}
    with tempfile.TemporaryDirectory(prefix="evalai-margin-") as tmp:
        for page_dump in page_records:
            page = PreprocessedPage.model_validate(page_dump)
            try:
                strip_path = extract_margin_strip_png(
                    page.preprocessed_image_path, Path(tmp) / f"margin-p{page.page_number}.png"
                )
                from answer_eval.processing.segmentation.schemas import (
                    BoundingBox as _BB,
                )
                from answer_eval.processing.segmentation.schemas import (
                    QuestionRegion as _QR,
                )

                strip_region = _QR(
                    region_id=f"MARGIN-P{page.page_number:02d}",
                    page_number=page.page_number,
                    submission_id=page.submission_id,
                    bbox=_BB(x_min=0.0, y_min=0.0, x_max=0.15, y_max=1.0),
                    crop_image_path=str(strip_path),
                )
                ocr = _run_async(ocr_agent.extract_text(strip_region))
                lines_by_page[page.page_number] = build_line_observations(
                    page.page_number,
                    page.preprocessed_image_path,
                    texts=[line for line in ocr.lines if line.strip()],
                )
            except Exception as e:  # noqa: BLE001 - one unreadable strip must not kill the job
                logger.warning("Margin strip OCR failed; anchors unconfirmed", page=page.page_number, error=str(e))
                lines_by_page[page.page_number] = build_line_observations(
                    page.page_number, page.preprocessed_image_path
                )

    mapping = QuestionSpanMapper().map(lines_by_page, valid_numbers, submission_id=state.get("submission_id", ""))

    regions = [QuestionRegion.model_validate(r) for r in region_records]
    page_results = [
        PageSegmentationResult(
            submission_id=state.get("submission_id", ""),
            page_number=page,
            regions=[r for r in regions if r.page_number == page],
            source_page_hash="mapping-only",
        )
        for page in sorted({r.page_number for r in regions})
    ]
    mapping = assign_regions(mapping, page_results)

    # Robustness step 1: when margin anchors found nothing (typical for scanned
    # sheets), harvest question numbers from each region's header band instead
    # — students repeat "Q3" above their answer even when the margin is lost.
    # Falls through to the sequential fallback when too few headers resolve.
    if not mapping.spans and valid_numbers and regions:
        import tempfile as _tempfile

        from answer_eval.processing.mapping.header_anchors import harvest_header_mapping

        with _tempfile.TemporaryDirectory(prefix="evalai-header-") as header_tmp:
            harvested = harvest_header_mapping(
                submission_id=state.get("submission_id", ""),
                page_records=page_records,
                regions=regions,
                valid_question_numbers=valid_numbers,
                ocr_region=lambda region: _run_async(ocr_agent.extract_text(region)),
                work_dir=Path(header_tmp),
            )
        if harvested is not None:
            logger.warning(
                "No margin anchors detected; region-header anchors used for mapping",
                submission_id=state.get("submission_id", ""),
                spans=len(harvested.spans),
            )
            mapping = harvested

    # Remaining unanswered questions: deterministic tail repair first (cheap,
    # guard-limited), then LLM semantic mapping BY CONTENT — the student often
    # answered correctly but forgot to write the question number.
    from answer_eval.processing.mapping.header_anchors import repair_missing_tail

    covered = {s.question_number for s in mapping.spans}
    missing = [n for n in valid_numbers if n not in covered]
    if missing and regions:
        repair_missing_tail(mapping, regions, missing)
        covered = {s.question_number for s in mapping.spans}
        missing = [n for n in valid_numbers if n not in covered]
    if missing and regions:
        semantic = _semantic_mapping_stage(state, mapping, regions, missing, ocr_agent, provider)
        if semantic is not None:
            mapping = semantic

    # Fallback (spec #31/#33): scanned sheets whose question numbers are not
    # detectable in the far-left margin yield ZERO spans, which previously left
    # every region UNMAPPED and graded nothing. Assign regions to rubric
    # questions in reading order instead, with every span flagged uncertain so
    # the teacher-review routing still applies — graded, but never silent.
    if not mapping.spans and valid_numbers and regions:
        answer_regions = sorted(
            (r for r in regions if r.region_type.value != "diagram"),
            key=lambda r: (r.page_number, r.reading_order),
        )
        if answer_regions:
            from answer_eval.processing.mapping.schemas import QuestionSpan as _QS
            from answer_eval.processing.mapping.schemas import UnassignedContent as _UC

            first_page = min(r.page_number for r in regions)
            logger.warning(
                "No margin anchors detected; sequential mapping fallback (flagged uncertain)",
                submission_id=state.get("submission_id", ""),
                regions=len(answer_regions),
                questions=len(valid_numbers),
            )
            for idx, number in enumerate(valid_numbers):
                span = _QS(
                    question_id=f"Q{number}",
                    question_number=number,
                    start_page=first_page,
                    end_page=first_page,
                )
                span.add_uncertainty("fallback_no_margin_anchors")
                if idx < len(answer_regions):
                    region = answer_regions[idx]
                    span.region_ids.append(region.region_id)
                    span.start_page = span.end_page = region.page_number
                mapping.spans.append(span)
            extra = answer_regions[len(valid_numbers):]
            mapping.unassigned = _UC(
                region_ids=[r.region_id for r in extra],
                reasons=["fallback_more_regions_than_questions"] if extra else [],
            )

    span_by_region: dict[str, Any] = {}
    for span in mapping.spans:
        for rid in (*span.region_ids, *span.diagram_region_ids):
            span_by_region[rid] = span
    updated_regions: list[Any] = []
    for region in regions:
        dump = region.model_dump()
        span = span_by_region.get(region.region_id)
        if span is not None:
            # Uncertainty lives on the span; canonical answers pick it up below.
            dump["question_id"] = span.question_id
        updated_regions.append(dump)

    uncertain_qids = [s["question_id"] for s in mapping.model_dump()["spans"] if s["mapping_uncertain"]]
    return {
        **_advance(dict(state), "mapping_questions", 4),
        "question_spans": [s.model_dump() for s in mapping.spans],
        "unassigned_regions": mapping.unassigned.region_ids,
        "mapping_uncertain_questions": uncertain_qids,
        "region_records": updated_regions,
    }


def run_ocr_diagram(state: EvaluationWorkflowState, provider: InferenceProvider) -> dict:
    """Modules 9 & 10 â€” perception only. No grading logic touches these outputs."""
    if state.get("canonical_answers"):
        return {"current_stage": "ocr"}
    from answer_eval.processing.segmentation.schemas import QuestionRegion, RegionType

    regions = [QuestionRegion.model_validate(r) for r in (state.get("region_records") or [])]
    ocr_agent = OCRAgent(inference_provider=provider)
    diagram_agent = DiagramAgent(inference_provider=provider)

    ocr_results, diagram_results = [], []
    try:
        for region in regions:
            qid = region.question_id or "UNMAPPED"
            if region.region_type == RegionType.DIAGRAM:
                diagram_results.append((qid, _run_async(diagram_agent.extract_diagram(region))))
            elif region.region_type == RegionType.MIXED:
                ocr_results.append((qid, _run_async(ocr_agent.extract_text(region))))
                diagram_results.append((qid, _run_async(diagram_agent.extract_diagram(region))))
            else:
                ocr_results.append((qid, _run_async(ocr_agent.extract_text(region))))
    except AnswerEvalError as e:
        # Inference failures are retryable; the job system decides about backoff.
        return _error(dict(state), "ocr_diagram", e, permanent=False)

    return {
        **_advance(dict(state), "ocr", 5),
        "ocr_records": [[region_id, r.model_dump()] for (region_id, r) in _key_by_region(ocr_results)],
        "diagram_records": [[region_id, d.model_dump()] for (region_id, d) in _key_by_region(diagram_results)],
    }


def _semantic_mapping_stage(
    state: dict,
    mapping: Any,
    regions: list[Any],
    missing: list[int],
    ocr_agent: Any,
    provider: InferenceProvider,
) -> Any:
    """OCR the candidate regions and let the VLM assign them by content.

    Best-effort by design: any failure (OCR, inference, parse) returns ``None``
    so the mapping stays unchanged and later fallbacks still run.
    """
    import tempfile
    import uuid
    from pathlib import Path

    from PIL import Image

    from answer_eval.processing.mapping.semantic_mapper import (
        candidate_regions_for_missing,
        semantic_mapping_fallback,
    )

    def _complete(prompt: str) -> str:
        from answer_eval.inference.types import InferenceRequest

        async def _infer() -> str:
            resp = await provider.infer(
                InferenceRequest(
                    request_id=f"semantic-map-{uuid.uuid4().hex[:8]}",
                    prompt=prompt,
                    max_tokens=1024,
                    temperature=0.0,
                    metadata={
                        "task": "semantic_mapping",
                        "submission_id": state.get("submission_id", ""),
                    },
                )
            )
            return resp.text if resp is not None else ""

        return _run_async(_infer())

    with tempfile.TemporaryDirectory(prefix="evalai-semantic-") as tmp:
        page_images = {
            dump.get("page_number"): dump.get("preprocessed_image_path")
            for dump in (state.get("page_records") or [])
            if isinstance(dump, dict)
        }
        region_texts: dict[str, str] = {}
        for region in candidate_regions_for_missing(mapping, regions):
            try:
                crop_path = region.crop_image_path
                if not crop_path:
                    image_path = page_images.get(region.page_number)
                    if not image_path:
                        continue
                    image = Image.open(str(image_path)).convert("RGB")
                    width, height = image.size
                    bbox = region.bbox
                    crop = image.crop(
                        (
                            max(0, int(width * bbox.x_min)),
                            max(0, int(height * bbox.y_min)),
                            min(width, int(width * bbox.x_max)),
                            min(height, int(height * bbox.y_max)),
                        )
                    )
                    crop_path = str(Path(tmp) / f"{region.region_id}.png")
                    crop.save(crop_path, format="PNG")
                ocr = _run_async(
                    ocr_agent.extract_text(region.model_copy(update={"crop_image_path": crop_path}))
                )
                region_texts[region.region_id] = ocr.raw_text or ""
            except Exception as exc:  # noqa: BLE001 - one bad region must not abort mapping
                logger.warning("semantic candidate OCR failed", region_id=region.region_id, error=str(exc))

        try:
            return semantic_mapping_fallback(
                submission_id=state.get("submission_id", ""),
                mapping=mapping,
                regions=regions,
                missing_numbers=missing,
                rubrics=state.get("rubrics") or {},
                region_texts=region_texts,
                complete=_complete,
            )
        except Exception as exc:  # noqa: BLE001 - semantic mapping is best-effort
            logger.warning("semantic mapping stage failed", error=str(exc))
            return None


def _key_by_region(pairs: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Key perception results by their stable region id (from provenance)."""
    keyed: list[tuple[str, Any]] = []
    for _qid, result in pairs:
        provenance = getattr(result, "provenance", None)
        region_id = getattr(provenance, "region_id", None)
        keyed.append((str(region_id) if region_id else f"__order_{len(keyed)}__", result))
    return keyed


def reconstruct_answers(state: EvaluationWorkflowState) -> dict:
    """Module 11 â€” rebuild immutable canonical answers from perception results."""
    if state.get("canonical_answers"):
        return {"current_stage": "reconstructing"}

    from answer_eval.agents.diagram.schemas import DiagramResult
    from answer_eval.agents.ocr.schemas import OCRResult
    from answer_eval.agents.reconstruction.service import ReconstructionService
    from answer_eval.processing.segmentation.schemas import QuestionRegion

    regions = {r["region_id"]: QuestionRegion.model_validate(r) for r in (state.get("region_records") or [])}
    service = ReconstructionService()

    # Region id -> mapped question id (Milestone 7/8); falls back to the
    # region's own question_id when the mapper did not run.
    uncertain_qids = set(state.get("mapping_uncertain_questions") or [])
    region_question: dict[str, str | None] = {
        rid: (region.question_id or None) for rid, region in regions.items()
    }

    ocr_groups: dict[str, list[tuple[Any, Any]]] = {}
    diagram_groups: dict[str, list[tuple[Any, Any]]] = {}

    def _region_of(dump: dict):
        region_id = (dump.get("provenance") or {}).get("region_id")
        return regions.get(region_id)

    def _question_of(dump: dict) -> str:
        region_id = (dump.get("provenance") or {}).get("region_id")
        qid = region_question.get(region_id or "")
        if qid:
            return qid
        region = regions.get(region_id or "")
        return (region.question_id if region and region.question_id else "UNMAPPED")

    for _rid, dump in state.get("ocr_records") or []:
        result = OCRResult.model_validate(dump)
        ocr_groups.setdefault(_question_of(dump), []).append((_region_of(dump), result))
    for _rid, dump in state.get("diagram_records") or []:
        result = DiagramResult.model_validate(dump)
        diagram_groups.setdefault(_question_of(dump), []).append((_region_of(dump), result))

    all_ids = sorted({*ocr_groups.keys(), *diagram_groups.keys()})
    canonical: list[dict] = []
    try:
        for qid in all_ids:
            ans = service.reconstruct_answer(
                submission_id=state["submission_id"],
                question_id=qid,
                ocr_results=ocr_groups.get(qid, []),
                diagram_results=diagram_groups.get(qid, []),
            )
            if qid in uncertain_qids and "mapping_uncertain" not in ans.flags:
                ans.flags.append("mapping_uncertain")
            canonical.append(ans.model_dump())
    except Exception as e:
        return _error(dict(state), "reconstruct", e, permanent=False)

    return {**_advance(dict(state), "reconstructing", 5), "canonical_answers": canonical}


def grade_answers(state: EvaluationWorkflowState, provider: InferenceProvider) -> dict:
    """Modules 12-16 for every canonical answer with a matching rubric. Idempotent per question."""
    rubrics = state.get("rubrics") or {}
    teacher_rules_by_qid = state.get("teacher_rules") or {}
    graded = dict(state.get("graded_answers") or {})
    service = GradingService(inference_provider=provider)
    progress = max(state.get("progress_completed", 5), 5)

    for qid, rubric_dump in rubrics.items():
        if qid in graded:
            continue
        match = next((a for a in state.get("canonical_answers", []) if a.get("question_id") == qid), None)
        if match is None:
            continue
        try:
            canonical = CanonicalStructuredAnswer.model_validate(match)
            rubric = QuestionRubric.model_validate(rubric_dump)
            from answer_eval.grading.rules.schemas import TeacherQuestionRules

            rules_dump = teacher_rules_by_qid.get(qid)
            teacher_rules = TeacherQuestionRules.model_validate(rules_dump) if rules_dump else None
            graded_answer = _run_async(service.grade_question(canonical, rubric, teacher_rules=teacher_rules))
            graded[qid] = graded_answer.model_dump()
            progress += 1
        except Exception as e:
            try:
                logger.warning("Grading failed for question", question_id=qid, error=str(e)[:300])
            except Exception:
                pass
            return {
                "errors": [
                    *state.get("errors", []),
                    {
                        "node": "grade_answers",
                        "question_id": qid,
                        "error_type": type(e).__name__,
                        "message": str(e)[:300],
                        "retryable": True,
                    },
                ],
                "status": "failed_retryable",
                "current_stage": "evaluating",
            }

    return {
        **_advance(dict(state), "evaluating", min(progress, TOTAL_STAGES - 2)),
        "graded_answers": graded,
        "current_stage": "calculating_risk",
    }


def human_review_gate(state: EvaluationWorkflowState) -> dict:
    """Interrupt for teacher review when any graded answer requires it.

    Human review is a VALID workflow state (never a failure). The node calls
    LangGraph interrupt(); on resume it receives the teachers' decisions:
        {"<question_id>": {"approved": bool, "final_marks": float|None,
                           "reviewer_notes": str|None}}
    """
    from langgraph.types import interrupt

    graded: dict[str, Any] = dict(state.get("graded_answers") or {})
    decisions: dict[str, Any] = dict(state.get("review_decisions") or {})

    def _apply(qid: str, decision: Any, target: dict[str, Any]) -> None:
        if qid not in target or not isinstance(decision, dict):
            return
        g = target[qid]
        marks = dict(g.get("marks") or {})
        override = decision.get("final_marks")
        if override is not None:
            try:
                override = max(0.0, float(override))
                if override <= float(marks.get("maximum_marks", 0.0)):
                    marks["final_proposed_marks"] = round(override, 2)
                    marks["criteria_total"] = marks["final_proposed_marks"]
                    marks["deterministic_penalty"] = 0.0
            except (TypeError, ValueError):
                pass
        g["marks"] = marks
        review = dict(g.get("review") or {})
        review.update(
            {
                "required": False,
                "status": "reviewed",
                "reviewer_notes": decision.get("reviewer_notes"),
                "final_marks_override": override,
            }
        )
        if decision.get("approved") is False:
            review["status"] = "rejected"
        g["review"] = review
        target[qid] = g

    # Decisions carried in the state (e.g. re-supplied at a fresh start after a
    # restart lost the in-memory checkpoint) are applied without requiring a
    # second interrupt — a teacher's verdict must never be lost (#52/#85).
    for qid, decision in list(decisions.items()):
        _apply(qid, decision, graded)

    pending = {
        qid: {
            "question_id": qid,
            "proposed_marks": g.get("marks", {}).get("final_proposed_marks"),
            "maximum_marks": g.get("marks", {}).get("maximum_marks"),
            "risk": g.get("risk", {}),
            "comparison": {
                "total_difference": g.get("comparison", {}).get("total_difference"),
                "major_disagreement": g.get("comparison", {}).get("major_disagreement"),
            },
            "feedback": g.get("evaluation", {}).get("feedback", ""),
            "reasons": g.get("risk", {}).get("review_reasons", []),
            "criteria": g.get("evaluation", {}).get("criteria", []),
        }
        for qid, g in graded.items()
        if g.get("review", {}).get("required") and qid not in decisions
    }

    if not pending:
        return {"graded_answers": graded, "review_decisions": decisions, "status": "finalizing"}

    # Persisted by the checkpointer; workflow resumes here with Command(resume=...).
    teacher_input = interrupt({"awaiting_review": pending, "instructions": _REVIEW_INSTRUCTIONS})

    for qid, decision in (teacher_input or {}).items():
        if qid not in graded or not isinstance(decision, dict):
            continue
        decisions[qid] = decision
        _apply(qid, decision, graded)

    return {"graded_answers": graded, "review_decisions": decisions, "status": "finalizing"}


_REVIEW_INSTRUCTIONS = (
    'Submit {"<question_id>": {"approved": bool, "final_marks": number|null, '
    '"reviewer_notes": str|null}} for every pending question.'
)


def finalize(state: EvaluationWorkflowState) -> dict:
    graded: dict[str, Any] = dict(state.get("graded_answers") or {})
    failed = [e for e in state.get("errors", []) if e.get("retryable") is False]

    result_summary = {
        "submission_id": state["submission_id"],
        "questions": {},
        "total_proposed_marks": 0.0,
        "auto_approved": [],
        "human_reviewed": [],
    }
    for qid, g in sorted(graded.items()):
        marks = g.get("marks", {})
        final = marks.get("final_proposed_marks", 0.0)
        result_summary["questions"][qid] = {
            "final_marks": final,
            "maximum_marks": marks.get("maximum_marks"),
            "criteria_total": marks.get("criteria_total"),
            "deterministic_penalty": marks.get("deterministic_penalty"),
            "auto_approve": g.get("risk", {}).get("auto_approve", False),
            "risk_level": g.get("risk", {}).get("risk_level"),
            "feedback": g.get("evaluation", {}).get("feedback", ""),
            "criteria": g.get("evaluation", {}).get("criteria", []),
            "versions": g.get("versions", {}),
        }
        result_summary["total_proposed_marks"] = round(result_summary["total_proposed_marks"] + final, 2)
        (
            result_summary["auto_approved"]
            if g.get("risk", {}).get("auto_approve")
            else result_summary["human_reviewed"]
        ).append(qid)

    status = "completed" if not failed else "completed_with_errors"
    return {
        **_advance(dict(state), "completed", TOTAL_STAGES),
        "status": status,
        "result_summary": result_summary,
    }


# Backwards-friendly alias used by tests.
finalize_node = finalize
