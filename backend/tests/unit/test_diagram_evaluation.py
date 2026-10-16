"""Milestone 10 unit tests: original-image diagram evaluation (specs #35-#38)."""

from __future__ import annotations

import pytest

from answer_eval.agents.reconstruction.schemas import AnswerSegment, CanonicalStructuredAnswer
from answer_eval.core.provenance import Provenance
from answer_eval.grading.evaluation.diagram_agent import DiagramEvaluationAgent
from answer_eval.grading.evaluation.diagram_schemas import (
    DiagramEvaluation,
    DiagramPresenceStatus,
    KeyDiagramImage,
)
from answer_eval.inference.types import InferenceResponse, InferenceTiming, TokenUsage
from tests.conftest import MockInferenceProvider


def provenance(region_id: str) -> Provenance:
    return Provenance(
        submission_id="SUB-D",
        page_number=3,
        region_id=region_id,
        question_id="Q4",
        source_image_hash="hash-x",
        source_image_path="/tmp/crops/REG-P03-02.png",
        request_id="req-1",
        model_id="mock",
    )


def make_answer() -> CanonicalStructuredAnswer:
    return CanonicalStructuredAnswer(
        submission_id="SUB-D",
        question_id="Q4",
        source_pages=[1, 2],
        raw_text="the handshake begins with a syn packet",
        word_count=7,
        segments=[
            AnswerSegment(
                page_number=1,
                region_id="REG-P01-01",
                reading_order=1,
                raw_text="text part",
                crop_image_path="/tmp/crops/REG-P01-01.png",
            ),
            AnswerSegment(
                page_number=3,
                region_id="REG-P03-02",
                reading_order=2,
                raw_text="diagram",
                crop_image_path="/tmp/crops/REG-P03-02.png",
            ),
        ],
        provenance=provenance("REG-P01-01"),
    )


def key_diagrams(with_paths: bool = True) -> list[KeyDiagramImage]:
    return [
        KeyDiagramImage(
            key="key-diagrams/k1/p3-1.png",
            image_path=("/tmp/key/k1.png" if with_paths else None),
            type_label="TCP three-way handshake sequence diagram",
            description="client and server exchange SYN / SYN-ACK / ACK",
        )
    ]


class CapturingStructuredProvider(MockInferenceProvider):
    """Records infer_structured requests; returns one scripted payload."""

    def __init__(self, structured: dict) -> None:
        super().__init__()
        self.structured = structured
        self.captured_images: list[str] = []
        self.captured_prompts: list[str] = []

    async def infer_structured(self, request, schema, max_retries: int = 2):
        self.captured_images.extend(img.image_path for img in request.images)
        self.captured_prompts.append(request.prompt)
        return InferenceResponse(
            request_id=request.request_id,
            provider="mock",
            model_id="mock_4b",
            text="structured",
            structured_data=self.structured,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            timing=InferenceTiming(total_inference_ms=50.0),
        )


SCRIPTED = {
    "question_id": "Q4",
    "overall_status": "incomplete",
    "diagrams_expected": 1,
    "diagrams_found": 1,
    "type_correct": True,
    "required_components_missing": ["server block"],
    "required_labels_missing": ["SYN-ACK"],
    "required_connections_missing": [],
    "logical_structure": "partial",
    "judgments": [
        {
            "diagram_id": "STUDENT-Q4-D1",
            "status": "incomplete",
            "type_detected": "sequence_diagram",
            "type_matches_key": True,
            "components_present": ["client"],
            "components_missing": ["server"],
            "labels_matched": ["SYN"],
            "labels_missing": ["SYN-ACK"],
            "connections_matched": ["client -> server SYN"],
            "connections_missing": [],
            "relationships_correct": True,
            "notes": "handshake drawn but response leg missing",
        }
    ],
    "academic_notes": "structure partially matches the key; no artistic judgement applied",
    "uncertain": False,
    "flags": [],
}


def _rubric():
    from answer_eval.grading.rubric import DiagramRequirements, QuestionRubric

    return QuestionRubric(
        question_id="Q4",
        maximum_marks=8,
        expected_concepts=[],
        require_exact_criteria_total=False,
        diagram=DiagramRequirements(
            required=True,
            minimum_components=1,
            required_labels=["SYN", "SYN-ACK"],
        ),
    )


@pytest.mark.asyncio
async def test_diagram_evaluation_sends_both_sides_original_images() -> None:
    provider = CapturingStructuredProvider(SCRIPTED)
    agent = DiagramEvaluationAgent(provider)
    run = await agent.evaluate(make_answer(), _rubric(), key_diagrams())

    # Student crop AND answer-key crop both reach the VLM (#35/#37)
    assert "/tmp/crops/REG-P01-01.png" in provider.captured_images
    assert "/tmp/crops/REG-P03-02.png" in provider.captured_images
    assert "/tmp/key/k1.png" in provider.captured_images

    # Context carries teacher requirements + key metadata
    prompt = "\n".join(provider.captured_prompts)
    assert "minimum_components" in prompt
    assert "TCP three-way handshake" in prompt

    result = run.result
    assert isinstance(result, DiagramEvaluation)
    assert result.overall_status == DiagramPresenceStatus.incomplete
    assert result.judgments[0].labels_missing == ["SYN-ACK"]


@pytest.mark.asyncio
async def test_key_image_without_resolved_path_is_skipped() -> None:
    provider = CapturingStructuredProvider(SCRIPTED)
    agent = DiagramEvaluationAgent(provider)
    await agent.evaluate(make_answer(), _rubric(), key_diagrams(with_paths=False))
    assert "/tmp/key/k1.png" not in provider.captured_images


def test_prompt_forbids_artistic_judgement() -> None:
    from answer_eval.prompts.manager import PromptManager

    prompt = PromptManager().get_prompt_template("diagram_evaluation")
    lowered = prompt.lower()
    assert "never judge" in lowered or "never grade" in lowered
    assert "artistic" in lowered


