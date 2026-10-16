"""Typed LangGraph workflow state (Module 17).

All node outputs are JSON-serializable (pydantic models are stored as dumped
dicts and revalidated where needed) so every checkpointer backend works.
"""

from typing import Any, TypedDict


class EvaluationWorkflowState(TypedDict, total=False):
    # Identity / idempotency
    job_id: str
    submission_id: str
    input_hash: str

    # Inputs
    pdf_path: str
    rubrics: dict[str, Any]  # question_id -> QuestionRubric dump
    teacher_rules: dict[str, Any]  # question_id -> resolved question_policies dump (optional)

    # Perception stage outputs (Modules 4-11)
    pdf_pages: int
    regions_count: int
    canonical_answers: list[Any]  # list[CanonicalStructuredAnswer dumps]

    # Grading stage outputs (Modules 12-16), keyed by question_id
    strictness_policies: dict[str, Any]
    rule_results: dict[str, Any]
    evaluation_results: dict[str, Any]
    verification_results: dict[str, Any]
    comparisons: dict[str, Any]
    risk_results: dict[str, Any]
    graded_answers: dict[str, Any]

    # Human-in-the-loop
    review_decisions: dict[str, Any]  # question_id -> teacher decision

    # Perception intermediate records (JSON-serializable)
    page_records: list[Any]  # list[PreprocessedPage dumps]
    region_records: list[Any]
    ocr_records: list[Any]
    diagram_records: list[Any]

    # Milestone 7/8: cross-page question mapping
    line_records: list[Any]  # list[LineObservation dumps] per page
    question_spans: list[Any]  # list[QuestionSpan dumps] from QuestionSpanMapper
    mapping_uncertain_questions: list[str]  # qids needing teacher verification
    unassigned_regions: list[str]  # region ids before first marker / ambiguous

    # Control
    status: str  # running | awaiting_review | finalizing | completed | failed_retryable | failed_permanent
    current_stage: str
    progress_total: int
    progress_completed: int
    errors: list[dict[str, Any]]
    result_summary: dict[str, Any]
    metadata: dict[str, Any]
