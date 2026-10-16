"""Unit tests: LLM semantic question mapping (mapping robustness step 2)."""

from __future__ import annotations

import json

from answer_eval.processing.mapping.schemas import (
    MarkerPosition,
    QuestionMappingResult,
    QuestionSpan,
    UnassignedContent,
)
from answer_eval.processing.mapping.semantic_mapper import (
    apply_semantic_assignments,
    build_semantic_prompt,
    candidate_regions_for_missing,
    parse_semantic_assignments,
    semantic_mapping_fallback,
)
from answer_eval.processing.segmentation.schemas import (
    BoundingBox,
    QuestionRegion,
    RegionType,
)


def region(rid: str, y_min: float, page: int = 1) -> QuestionRegion:
    return QuestionRegion(
        region_id=rid,
        page_number=page,
        submission_id="SUB-S",
        bbox=BoundingBox(x_min=0.2, y_min=y_min, x_max=1.0, y_max=y_min + 0.2),
        region_type=RegionType.ANSWER_TEXT,
        reading_order=int(rid.rsplit("-", 1)[-1]),
    )


def marker(number: int, page: int = 1, y: float = 0.10) -> MarkerPosition:
    return MarkerPosition(
        question_number=number,
        raw_text=f"Q{number}",
        page_number=page,
        y_center=y,
        line_index=0,
    )


def anchored_mapping() -> QuestionMappingResult:
    """Q3 anchored at the top; trailing regions continuation-claimed as usual."""
    span = QuestionSpan(question_id="Q3", question_number=3, start_page=1, end_page=1, markers=[marker(3)])
    span.region_ids.extend(["REG-P01-01", "REG-P01-02", "REG-P01-03"])
    return QuestionMappingResult(submission_id="SUB-S", spans=[span], unassigned=UnassignedContent())


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_direct_json() -> None:
    raw = '{"assignments": [{"question_id": "Q4", "region_ids": ["REG-P01-02"]}]}'
    assert parse_semantic_assignments(raw, {"Q4"}, {"REG-P01-02"}) == {"Q4": ["REG-P01-02"]}


def test_parse_fenced_json_with_commentary() -> None:
    raw = 'Here is my mapping:\n```json\n{"assignments": [{"question_id": "Q4", "region_ids": ["REG-P01-03"]}]}\n```\nDone.'
    assert parse_semantic_assignments(raw, {"Q4"}, {"REG-P01-03"}) == {"Q4": ["REG-P01-03"]}


def test_parse_unwraps_ocr_style_envelope() -> None:
    inner = '{"assignments": [{"question_id": "Q4", "region_ids": ["REG-P01-02"]}]}'
    raw = json.dumps({"raw_text": inner, "lines": []})
    assert parse_semantic_assignments(raw, {"Q4"}, {"REG-P01-02"}) == {"Q4": ["REG-P01-02"]}


def test_parse_rejects_unknown_ids_and_duplicate_region_claims() -> None:
    raw = (
        '{"assignments": ['
        '{"question_id": "Q99", "region_ids": ["REG-P01-02"]},'
        '{"question_id": "Q4", "region_ids": ["REG-P01-02", "REG-P01-03"]},'
        '{"question_id": "Q5", "region_ids": ["REG-P01-02"]},'
        '{"question_id": "Q6", "region_ids": ["NOT-A-REGION"]}]}'
    )
    parsed = parse_semantic_assignments(raw, {"Q4", "Q5", "Q6"}, {"REG-P01-02", "REG-P01-03"})
    # Q99 invalid; Q4 wins the first claim on REG-P01-02; Q6's unknown region dropped.
    assert parsed == {"Q4": ["REG-P01-02", "REG-P01-03"]}


def test_parse_garbage_returns_empty() -> None:
    assert parse_semantic_assignments("I cannot help with that", {"Q4"}, {"REG-P01-02"}) == {}
    assert parse_semantic_assignments("", {"Q4"}, {"REG-P01-02"}) == {}


# ---------------------------------------------------------------------------
# Candidates + application
# ---------------------------------------------------------------------------


def test_candidates_include_trailing_and_exclude_guessed_spans() -> None:
    mapping = anchored_mapping()
    # R3 already guessed (marker-less span) -> excluded; R2 is continuation tail.
    guessed = QuestionSpan(question_id="Q5", question_number=5, start_page=1, end_page=1)
    guessed.region_ids.append("REG-P01-03")
    mapping.spans.append(guessed)

    candidates = candidate_regions_for_missing(
        mapping, [region(f"REG-P01-{i:02d}", 0.1 * i) for i in (1, 2, 3)]
    )
    assert [r.region_id for r in candidates] == ["REG-P01-02"]


def test_apply_creates_flagged_span_and_flags_unmatched_owner() -> None:
    mapping = anchored_mapping()  # Q3 owns R1..R3 by continuation
    regions = {f"REG-P01-{i:02d}": region(f"REG-P01-{i:02d}", 0.1 * i) for i in (1, 2, 3)}
    candidates = [regions["REG-P01-02"], regions["REG-P01-03"]]

    created = apply_semantic_assignments(mapping, {"Q4": ["REG-P01-02"]}, regions, candidates)
    assert created == 1
    q4 = next(s for s in mapping.spans if s.question_id == "Q4")
    assert q4.region_ids == ["REG-P01-02"]
    assert q4.mapping_uncertain
    assert "semantic_mapping" in q4.uncertainty_reasons
    assert "llm_assigned_by_content" in q4.uncertainty_reasons
    # The LLM did not claim R3, so it keeps its continuation owner (Q3) — but
    # that ambiguity is flagged so the tail reaches teacher review.
    q3 = next(s for s in mapping.spans if s.question_id == "Q3")
    assert q3.region_ids == ["REG-P01-01", "REG-P01-03"]
    assert q3.mapping_uncertain
    assert "semantic_unmatched_tail" in q3.uncertainty_reasons
    assert mapping.unassigned.region_ids == []


def test_prompt_contains_questions_and_regions() -> None:
    prompt = build_semantic_prompt(
        [
            {
                "question_id": "Q5",
                "question_text": "Explain PCA",
                "expected_answer": "",
                "concepts": ["eigenvectors"],
                "keywords": [],
            }
        ],
        [{"region_id": "REG-P01-02", "page_number": 1, "text": "principal components are..."}],
    )
    assert "Explain PCA" in prompt and "eigenvectors" in prompt
    assert "REG-P01-02" in prompt and "principal components" in prompt
    assert '"assignments"' in prompt


# ---------------------------------------------------------------------------
# Full fallback orchestration
# ---------------------------------------------------------------------------


def test_fallback_assigns_by_content() -> None:
    mapping = anchored_mapping()
    regions = [region(f"REG-P01-{i:02d}", 0.1 * i) for i in (1, 2, 3)]

    def complete(prompt: str) -> str:
        assert "Explain PCA" in prompt and "REG-P01-02" in prompt
        return '{"assignments": [{"question_id": "Q4", "region_ids": ["REG-P01-02"]}]}'

    updated = semantic_mapping_fallback(
        submission_id="SUB-S",
        mapping=mapping,
        regions=regions,
        missing_numbers=[4],
        rubrics={
            "Q4": {
                "question_text": "Explain PCA",
                "expected_concepts": [{"concept": "eigenvectors"}],
            }
        },
        region_texts={"REG-P01-02": "principal component analysis projects data"},
        complete=complete,
    )
    assert updated is not None
    assert any(s.question_id == "Q4" and s.region_ids == ["REG-P01-02"] for s in updated.spans)


def test_fallback_declines_when_model_unhelpful() -> None:
    mapping = anchored_mapping()
    regions = [region(f"REG-P01-{i:02d}", 0.1 * i) for i in (1, 2)]

    updated = semantic_mapping_fallback(
        submission_id="SUB-S",
        mapping=mapping,
        regions=regions,
        missing_numbers=[4],
        rubrics={"Q4": {"question_text": "Explain PCA"}},
        region_texts={"REG-P01-02": "principal component analysis"},
        complete=lambda _prompt: "no idea",
    )
    assert updated is None
    assert [s.question_id for s in mapping.spans] == ["Q3"]


def test_fallback_skips_when_no_candidates() -> None:
    mapping = anchored_mapping()
    # Marker sits near the page bottom: no region trails it and nothing is
    # unassigned, so there is nothing for the LLM to look at.
    mapping.spans[0].markers[0].y_center = 0.9
    regions = [region("REG-P01-01", 0.02), region("REG-P01-02", 0.5)]
    mapping.spans[0].region_ids = ["REG-P01-01", "REG-P01-02"]

    calls: list[str] = []

    def complete(prompt: str) -> str:
        calls.append(prompt)
        return '{"assignments": []}'

    updated = semantic_mapping_fallback(
        submission_id="SUB-S",
        mapping=mapping,
        regions=regions,
        missing_numbers=[4],
        rubrics={},
        region_texts={"REG-P01-01": "text", "REG-P01-02": "text"},
        complete=complete,
    )
    assert updated is None
    assert calls == []


def test_fallback_survives_complete_failures() -> None:
    mapping = anchored_mapping()
    regions = [region("REG-P01-02", 0.5)]

    def complete(_prompt: str) -> str:
        raise RuntimeError("ollama down")

    updated = semantic_mapping_fallback(
        submission_id="SUB-S",
        mapping=mapping,
        regions=regions,
        missing_numbers=[4],
        rubrics={"Q4": {"question_text": "Explain PCA"}},
        region_texts={"REG-P01-02": "pca text"},
        complete=complete,
    )
    assert updated is None

