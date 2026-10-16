"""DiagramEvaluationAgent (Milestone 10, spec #37).

Sends the STUDENT's original diagram crops AND the ANSWER-KEY's original
diagram crops plus the teacher's diagram requirements to the VLM, and obtains
a strict-schema ACADEMIC STRUCTURE comparison. Marks and missing-presence
penalties remain deterministic (Module 12 / spec #38).
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.core.logging import get_logger
from answer_eval.grading.evaluation.agent import BaseGradingAgent
from answer_eval.grading.evaluation.diagram_schemas import DiagramEvaluation, KeyDiagramImage
from answer_eval.grading.rubric import QuestionRubric

logger = get_logger("grading.diagram_evaluation")

DIAGRAM_EVALUATION_PROMPT_VERSION = "diagram-evaluation-v1"


@dataclass
class DiagramAgentRunOutput:
    result: DiagramEvaluation
    model_id: str = ""
    prompt_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class DiagramEvaluationAgent(BaseGradingAgent):
    """Compares student vs answer-key diagram IMAGES on academic structure."""

    task_name = "diagram_evaluation"
    prompt_version = DIAGRAM_EVALUATION_PROMPT_VERSION

    def build_context(
        self,
        answer: CanonicalStructuredAnswer,
        rubric: QuestionRubric,
        key_diagrams: list[KeyDiagramImage],
        expected_count: int,
    ) -> str:
        sections = [
            "## TASK",
            f"Compare the student's diagram(s) for question '{rubric.question_id}' against the "
            "answer-key diagram image(s). Judge ACADEMIC STRUCTURE ONLY.",
            "",
            "## DIAGRAM REQUIREMENTS (teacher configuration)",
            json.dumps(rubric.diagram.model_dump(), ensure_ascii=False),
            "",
            "## EXPECTED DIAGRAM COUNT",
            json.dumps({"expected": expected_count}),
            "",
            "## ANSWER-KEY DIAGRAM METADATA",
            json.dumps(
                [
                    {
                        "key": kd.key,
                        "type_label": kd.type_label,
                        "description": kd.description,
                    }
                    for kd in key_diagrams
                ],
                ensure_ascii=False,
            ),
            "",
            "## STUDENT MODULE-10 OBSERVATIONS (neutral facts — verify against the images)",
            json.dumps(
                [d.model_dump(exclude={"provenance", "model_metadata"}) for d in answer.diagrams],
                ensure_ascii=False,
                default=str,
            ),
            "",
            "Return the structured JSON comparison now.",
        ]
        return "\n".join(sections)

    async def evaluate(
        self,
        answer: CanonicalStructuredAnswer,
        rubric: QuestionRubric,
        key_diagrams: list[KeyDiagramImage],
        student_image_paths: list[str] | None = None,
    ) -> DiagramAgentRunOutput:
        request_id = f"diag-eval-{uuid.uuid4().hex[:8]}"
        if student_image_paths is None:
            student_image_paths = [
                seg.crop_image_path for seg in answer.segments if seg.crop_image_path
            ]

        from answer_eval.inference.types import ImageInput

        images = [ImageInput(image_path=p, mime_type="image/png") for p in student_image_paths]
        images += [
            ImageInput(image_path=kd.image_path, mime_type="image/png")
            for kd in key_diagrams
            if kd.image_path
        ]
        images = images[:6]

        expected = max(
            rubric.diagram.minimum_components if rubric.diagram.required else 0,
            1 if rubric.diagram.required else 0,
        )
        system_prompt = self.prompt_manager.get_prompt_template(self.task_name)
        user_content = self.build_context(answer, rubric, key_diagrams, expected)

        resp = await self._run_structured(request_id, system_prompt, user_content, DiagramEvaluation, images)
        result = DiagramEvaluation.model_validate(resp.structured_data)
        logger.info(
            "[DIAGRAM-EVAL]",
            question_id=rubric.question_id,
            status=result.overall_status.value,
            uncertain=result.uncertain,
        )
        return DiagramAgentRunOutput(
            result=result,
            model_id=resp.model_id,
            prompt_version=self.prompt_version,
            extra={"usage": resp.usage.model_dump(), "stop_reason": resp.stop_reason},
        )
