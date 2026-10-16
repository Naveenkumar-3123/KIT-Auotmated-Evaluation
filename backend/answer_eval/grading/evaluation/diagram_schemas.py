"""Original-image diagram evaluation contract (Milestone 10, spec #37).

The VLM compares ACADEMIC STRUCTURE between the student's original diagram
crops and the answer-key's original diagram crops. Artistic quality,
handwriting neatness and drawing style are NEVER graded unless the teacher
explicitly requires it. Presence status feeds the deterministic teacher
penalties (spec #38); this agent never assigns marks.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class DiagramPresenceStatus(StrEnum):
    present = "present"
    incomplete = "incomplete"
    incorrect = "incorrect"
    missing = "missing"
    uncertain = "uncertain"


class LogicalStructure(StrEnum):
    adequate = "adequate"
    partial = "partial"
    poor = "poor"
    not_assessable = "not_assessable"


class DiagramJudgment(BaseModel):
    """One student diagram compared against the key's expectations."""

    diagram_id: str = Field(description="Student diagram id, e.g. STUDENT-Q4-D1")
    status: DiagramPresenceStatus
    type_detected: str | None = Field(default=None, description="e.g. flowchart, sequence_diagram")
    type_matches_key: bool | None = Field(default=None)
    components_present: list[str] = Field(default_factory=list)
    components_missing: list[str] = Field(default_factory=list)
    labels_matched: list[str] = Field(default_factory=list)
    labels_missing: list[str] = Field(default_factory=list)
    connections_matched: list[str] = Field(default_factory=list, description="Including direction/arrows")
    connections_missing: list[str] = Field(default_factory=list)
    relationships_correct: bool | None = Field(
        default=None, description="Logical relationships/directions match the key"
    )
    notes: str = ""


class DiagramEvaluation(BaseModel):
    """Structured comparison result. NO marks — penalties stay deterministic."""

    schema_version: str = "diagram-evaluation-v1"
    question_id: str
    overall_status: DiagramPresenceStatus
    diagrams_expected: int = Field(ge=0)
    diagrams_found: int = Field(ge=0)
    type_correct: bool | None = None
    required_components_missing: list[str] = Field(default_factory=list)
    required_labels_missing: list[str] = Field(default_factory=list)
    required_connections_missing: list[str] = Field(default_factory=list)
    logical_structure: LogicalStructure = LogicalStructure.not_assessable
    judgments: list[DiagramJudgment] = Field(default_factory=list)
    academic_notes: str = ""
    uncertain: bool = False
    flags: list[str] = Field(default_factory=list)


class KeyDiagramImage(BaseModel):
    """An answer-key ORIGINAL diagram crop resolved for grading."""

    key: str = Field(description="Storage object key or local path identifier")
    image_path: str | None = Field(default=None, description="Resolved local PNG path for inference")
    type_label: str | None = None
    description: str | None = None
