"""Structured output of the answer-key parser agent (answer-key-v1).

The parser extracts what the teacher supplied. It must NOT invent rubric
information: optional fields stay None/empty and uncertainties are surfaced
as warnings for the teacher review step.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

ANSWER_KEY_SCHEMA_VERSION = "answer-key-v1"

ANSWER_TYPES = (
    "descriptive",
    "explain",
    "short_answer",
    "numerical",
    "formula",
    "diagram",
    "mixed",
)


class ParsedMathStep(BaseModel):
    step_id: str = Field(description="Rubric step code, e.g. M1")
    description: str
    marks: float = Field(ge=0)


class ParsedConcept(BaseModel):
    concept_code: str = Field(description="Rubric concept code, e.g. C1")
    description: str
    maximum_marks: float = Field(ge=0, default=0)


class ParsedDiagramHint(BaseModel):
    """Where a diagram for this question lives in the source document."""

    page: int = Field(ge=1)
    ordinal: int = Field(default=1, ge=1)
    type_label: str | None = Field(default=None, description="Short role/type label, e.g. 'TCP three-way handshake'")
    bbox: list[float] | None = Field(
        default=None,
        description="Normalized [x_min, y_min, x_max, y_max] on the page; null if unknown",
    )
    uncertain: bool = Field(default=False)


class ParsedQuestionOption(BaseModel):
    option_code: str = Field(default="a", description="'a' or 'b'")
    option_title: str = Field(default="", description="e.g. 'Option (a): Bagging and Boosting'")
    question_text: str = Field(default="")
    expected_answer_text: str = Field(default="")
    maximum_marks: float = Field(default=16.0, ge=0)
    expected_concepts: list[ParsedConcept] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    diagram_hints: list[ParsedDiagramHint] = Field(default_factory=list)


class ParsedQuestion(BaseModel):
    question_number: int = Field(ge=1)
    question_text: str = Field(default="")
    maximum_marks: float = Field(ge=0)
    answer_type: str = Field(default="descriptive")
    expected_answer_text: str = Field(default="")
    expected_concepts: list[ParsedConcept] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    mandatory_terms: list[str] = Field(default_factory=list)
    math_rubric: list[ParsedMathStep] | None = None
    diagram_hints: list[ParsedDiagramHint] = Field(default_factory=list)
    parser_uncertainties: list[str] = Field(default_factory=list)
    options: list[ParsedQuestionOption] = Field(default_factory=list)


class ParsedAnswerKey(BaseModel):
    schema_version: str = Field(default=ANSWER_KEY_SCHEMA_VERSION)
    title: str = Field(default="Answer key")
    question_count: int = Field(ge=0)
    questions: list[ParsedQuestion]
    parser_warnings: list[str] = Field(default_factory=list)

    def validated(self) -> ParsedAnswerKey:
        """Consistency pass: count vs list, duplicate numbers, mark totals."""
        warnings = list(self.parser_warnings)
        numbers = [q.question_number for q in self.questions]
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        if duplicates:
            warnings.append(f"Duplicate question numbers detected: {duplicates}")
        if len(self.questions) != self.question_count:
            warnings.append(
                f"question_count field said {self.question_count} but {len(self.questions)} questions were extracted"
            )
        for question in self.questions:
            if question.maximum_marks <= 0:
                warnings.append(f"Q{question.question_number}: maximum_marks missing or zero")
            concept_total = sum(c.maximum_marks for c in question.expected_concepts)
            if question.expected_concepts and abs(concept_total - question.maximum_marks) > 0.01:
                warnings.append(
                    f"Q{question.question_number}: concept marks total {concept_total:g} != maximum {question.maximum_marks:g}"
                )
            if question.math_rubric:
                step_total = sum(s.marks for s in question.math_rubric)
                if abs(step_total - question.maximum_marks) > 0.01:
                    warnings.append(
                        f"Q{question.question_number}: math step marks total {step_total:g} != maximum {question.maximum_marks:g}"
                    )
        return ParsedAnswerKey(
            schema_version=self.schema_version,
            title=self.title,
            question_count=len(self.questions),
            questions=self.questions,
            parser_warnings=warnings,
        )
