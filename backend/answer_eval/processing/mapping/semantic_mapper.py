"""LLM semantic question mapping (mapping robustness step 2 - content-based).

Layout anchors (margin numbers, region-header numbers) are deterministic but
they fail when a student forgets to number an answer. This module covers that
case BY CONTENT: the unclaimed regions are OCR'd, and the VLM compares each
transcription against the UNANSWERED questions from the answer key (question
text, expected answer, concepts) and assigns regions to questions.

Safety rules, mirroring the rest of the mapping stack (spec #33):

* only UNANSWERED questions may receive regions;
* only UNCLAIMED candidate regions may be assigned;
* every semantically-assigned span is flagged ``semantic_mapping`` so the
  teacher-review routing applies - graded, never silent;
* anything the model fails to assign keeps continuation semantics or lands in
  ``unassigned`` for the teacher.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from answer_eval.core.logging import get_logger
from answer_eval.processing.mapping.header_anchors import _answer_regions
from answer_eval.processing.mapping.schemas import (
    QuestionMappingResult,
    QuestionSpan,
    UnassignedContent,
)
from answer_eval.processing.segmentation.schemas import QuestionRegion

logger = get_logger("processing.mapping.semantic")

# Maximum transcription characters shown to the model per region.
MAX_REGION_TEXT_CHARS = 600
# Maximum answer-key text characters shown per question.
MAX_QUESTION_TEXT_CHARS = 400


def candidate_regions_for_missing(
    mapping: QuestionMappingResult,
    regions: list[QuestionRegion],
) -> list[QuestionRegion]:
    """Answer regions that could still belong to a missing question.

    Candidates are regions positioned after the last anchored marker (the
    continuation tail) plus explicitly unassigned regions, EXCLUDING regions
    already owned by marker-less spans (earlier deterministic/semantic guesses)
    so repeated repair passes never re-steal each other's assignments.
    """
    guessed_owner_ids = {
        rid
        for span in mapping.spans
        if not span.markers
        for rid in (*span.region_ids, *span.diagram_region_ids)
    }
    unassigned_ids = set(mapping.unassigned.region_ids)

    last_marker = max(
        (marker for span in mapping.spans for marker in span.markers),
        key=lambda m: (m.page_number, m.y_center),
        default=None,
    )

    def _is_candidate(r: QuestionRegion) -> bool:
        if r.region_id in guessed_owner_ids:
            return False  # already claimed by a deterministic/semantic guess
        if last_marker is None:
            return True  # nothing anchored anywhere: every region is open
        after_last = (r.page_number, r.bbox.y_min) > (last_marker.page_number, last_marker.y_center)
        return after_last or r.region_id in unassigned_ids

    seen: set[str] = set()
    candidates: list[QuestionRegion] = []
    for region in _answer_regions(regions):
        if region.region_id in seen:
            continue
        if _is_candidate(region):
            seen.add(region.region_id)
            candidates.append(region)
    return candidates


def build_semantic_prompt(
    missing_questions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    """Render the semantic-mapping prompt (template + answer key + regions)."""
    from answer_eval.prompts.manager import PromptManager

    questions_block = json.dumps(missing_questions, indent=1, ensure_ascii=False)
    regions_block = "\n".join(
        f"- {item['region_id']} (page {item['page_number']}): {item['text']}"
        for item in candidates
    )
    return PromptManager().render_prompt(
        "semantic_mapping",
        questions=questions_block,
        regions=regions_block,
    )


def parse_semantic_assignments(
    raw: str,
    valid_question_ids: set[str],
    candidate_region_ids: set[str],
) -> dict[str, list[str]]:
    """Extract {question_id: [region_id, ...]} from the model response.

    Defensive by design: accepts fenced or bare JSON, one ``raw_text`` unwrap
    (OCR-agent-style payloads), and silently rejects unknown ids, duplicate
    region claims (first claim wins) and unknown shapes.
    """
    if not raw or not raw.strip():
        return {}
    payload = _extract_json(raw.strip())
    if payload is None:
        return {}

    raw_assignments: Any = None
    if isinstance(payload, dict):
        raw_assignments = payload.get("assignments", payload)
    if isinstance(raw_assignments, dict):
        raw_assignments = [
            {"question_id": qid, "region_ids": rids} for qid, rids in raw_assignments.items()
        ]
    if not isinstance(raw_assignments, list):
        return {}

    assignments: dict[str, list[str]] = {}
    claimed: set[str] = set()
    for entry in raw_assignments:
        if not isinstance(entry, dict):
            continue
        qid = str(entry.get("question_id", "")).strip().upper()
        if qid not in valid_question_ids or qid in assignments:
            continue
        rids = entry.get("region_ids")
        if not isinstance(rids, list):
            continue
        accepted: list[str] = []
        for rid in rids:
            rid = str(rid).strip()
            if rid in candidate_region_ids and rid not in claimed:
                claimed.add(rid)
                accepted.append(rid)
        if accepted:
            assignments[qid] = accepted
    return assignments


def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction: direct, fenced, embedded, or raw_text-wrapped."""
    candidates_to_try = [text]
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        candidates_to_try.insert(0, fenced.group(1).strip())
    embedded = re.search(r"\{.*\}", text, re.DOTALL)
    if embedded:
        candidates_to_try.append(embedded.group(0))

    for attempt in candidates_to_try:
        try:
            payload = json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("raw_text"), str):
            # OCR-agent-style envelope: the mapping JSON rides in raw_text.
            try:
                inner = json.loads(payload["raw_text"])
            except (json.JSONDecodeError, ValueError):
                continue
            return inner
        return payload
    return None


def apply_semantic_assignments(
    mapping: QuestionMappingResult,
    assignments: dict[str, list[str]],
    regions_by_id: dict[str, QuestionRegion],
    candidates: list[QuestionRegion] | None = None,
) -> int:
    """Re-claim assigned regions from continuation owners; create flagged spans.

    Candidate regions the model did NOT assign keep their continuation owner,
    but that owner span is flagged ``semantic_unmatched_tail`` so the ambiguous
    tail reaches teacher review instead of being silently graded.

    Returns the number of questions that received a semantic span.
    """
    assigned_rids = {rid for rids in assignments.values() for rid in rids}
    candidate_ids = {r.region_id for r in (candidates or [])}
    unmatched = candidate_ids - assigned_rids
    for span in mapping.spans:
        span.region_ids = [rid for rid in span.region_ids if rid not in assigned_rids]

    created = 0
    for qid, rids in sorted(assignments.items()):
        regions = [regions_by_id[rid] for rid in rids if rid in regions_by_id]
        if not regions:
            continue
        first = regions[0]
        span = QuestionSpan(
            question_id=qid,
            question_number=int(qid.lstrip("Qq")),
            start_page=first.page_number,
            end_page=max(r.page_number for r in regions),
        )
        span.region_ids.extend(r.region_id for r in regions)
        span.add_uncertainty("semantic_mapping")
        span.add_uncertainty("llm_assigned_by_content")
        mapping.spans.append(span)
        created += 1

    next_unassigned = [rid for rid in mapping.unassigned.region_ids if rid not in assigned_rids]
    mapping.unassigned = UnassignedContent(region_ids=next_unassigned, reasons=mapping.unassigned.reasons)

    if unmatched:
        # Flag the span that kept the ambiguous leftovers (usually the last
        # anchored question's continuation tail) for teacher review.
        for span in mapping.spans:
            if unmatched.intersection(span.region_ids):
                span.mapping_uncertain = True
                if "semantic_unmatched_tail" not in span.uncertainty_reasons:
                    span.uncertainty_reasons.append("semantic_unmatched_tail")
    return created



def semantic_mapping_fallback(
    *,
    submission_id: str,
    mapping: QuestionMappingResult,
    regions: list[QuestionRegion],
    missing_numbers: list[int],
    rubrics: dict[str, Any],
    region_texts: dict[str, str],
    complete: Callable[[str], str],
) -> QuestionMappingResult | None:
    """Map content-verified regions to unanswered questions via the VLM.

    ``region_texts`` maps candidate region ids to their OCR transcription;
    ``complete`` runs one text-only LLM call (prompt -> response text).
    Returns the updated mapping, or ``None`` when there is nothing to run or
    the model declined/failed - callers keep the previous mapping unchanged.
    """
    if not missing_numbers:
        return None
    candidates = [r for r in candidate_regions_for_missing(mapping, regions) if (region_texts.get(r.region_id) or "").strip()]
    if not candidates:
        return None

    missing_questions: list[dict[str, Any]] = []
    for number in missing_numbers:
        qid = f"Q{number}"
        dump = rubrics.get(qid) if isinstance(rubrics, dict) else None
        dump = dump if isinstance(dump, dict) else {}
        concepts = [
            str(c.get("concept") if isinstance(c, dict) else c)
            for c in (dump.get("expected_concepts") or [])[:6]
        ]
        missing_questions.append(
            {
                "question_id": qid,
                "question_text": str(dump.get("question_text") or "")[:MAX_QUESTION_TEXT_CHARS],
                "expected_answer": str(dump.get("expected_answer") or "")[:MAX_QUESTION_TEXT_CHARS],
                "concepts": [c for c in concepts if c and c != "None"],
                "keywords": [str(k) for k in (dump.get("keywords") or [])[:8]],
            }
        )

    prompt = build_semantic_prompt(
        missing_questions,
        [
            {
                "region_id": r.region_id,
                "page_number": r.page_number,
                "text": region_texts[r.region_id][:MAX_REGION_TEXT_CHARS],
            }
            for r in candidates
        ],
    )
    try:
        raw = complete(prompt)
    except Exception as exc:  # noqa: BLE001 - LLM outage must never kill mapping
        logger.warning("semantic mapping inference failed", submission_id=submission_id, error=str(exc))
        return None

    assignments = parse_semantic_assignments(
        raw,
        {f"Q{n}" for n in missing_numbers},
        {r.region_id for r in candidates},
    )
    if not assignments:
        logger.warning("semantic mapping returned no usable assignments", submission_id=submission_id)
        return None

    created = apply_semantic_assignments(
        mapping, assignments, {r.region_id: r for r in regions}, candidates
    )
    if created == 0:
        return None
    logger.info(
        "semantic mapping applied",
        submission_id=submission_id,
        questions=sorted(assignments),
        regions_assigned=sum(len(v) for v in assignments.values()),
    )
    return mapping


