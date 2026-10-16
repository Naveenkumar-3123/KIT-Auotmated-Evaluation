"""Versioned heuristic risk policy data (Module 16).

heuristic-risk-v2: extends v1 with the full spec-#51 mandatory review trigger
set (mapping uncertainty, math OCR uncertainty, diagram evaluation failures,
page anomalies, unsupported answer types, poor image quality). Still
UNCALIBRATED numeric weights — teacher-labelled data will calibrate later.
"""

RISK_POLICY_VERSION = "heuristic-risk-v2"

# Signal weights (sum = 1.0). Each signal is normalized to 0-1 before weighting.
SIGNAL_WEIGHTS = {
    "ocr_uncertainty": 0.20,
    "segmentation_uncertainty": 0.10,
    "diagram_uncertainty": 0.10,
    "grader_disagreement": 0.30,
    "evidence_risk": 0.15,
    "validation_risk": 0.15,
}

# Risk score -> level thresholds.
LOW_RISK_THRESHOLD = 0.20
MEDIUM_RISK_THRESHOLD = 0.45
AUTO_APPROVE_MAX_LEVEL = "low"

# Mandatory review triggers (spec #51): ANY of these forces human review
# regardless of the numeric risk score.
MANDATORY_REVIEW_TRIGGERS = [
    # answer / rubric integrity
    "answer_empty",
    "invalid_rubric_arithmetic",
    "unsupported_answer_type",
    # grader output integrity
    "schema_validation_failed",
    "repeated_schema_validation_failed",
    "arithmetic_validation_failed",
    # evidence & agreement
    "unverified_evidence",
    "major_grader_disagreement",
    # security
    "prompt_injection_attempt",
    # mapping / perception uncertainty (#33, #51)
    "mapping_uncertain",
    "missing_source_region",
    "duplicate_page_detected",
    "missing_page_detected",
    "very_faint",
    "poor_image_quality",
    # diagrams (#37/#38/#51)
    "diagram_evaluation_failed",
    "diagram_evaluation_uncertain",
    "key_diagram_parser_uncertain",
    # math (#48)
    "math_symbol_uncertain",
]

# Human-readable reasons for each trigger (used in review records).
TRIGGER_REASONS = {
    "answer_empty": "Answer region is empty.",
    "invalid_rubric_arithmetic": "Rubric arithmetic is invalid; grading cannot be trusted.",
    "unsupported_answer_type": "The question's answer type is not supported by the pipeline.",
    "schema_validation_failed": "Grader output failed schema validation.",
    "repeated_schema_validation_failed": "Grader output repeatedly failed schema validation.",
    "arithmetic_validation_failed": "Score arithmetic failed validation.",
    "unverified_evidence": "Evaluator cited evidence not present in the student answer.",
    "major_grader_disagreement": "Evaluator and verifier disagree significantly.",
    "prompt_injection_attempt": "Instruction-like text detected inside the student answer.",
    "mapping_uncertain": "Question-page mapping is uncertain; content may be attributed incorrectly.",
    "missing_source_region": "A source region referenced by grading could not be located.",
    "duplicate_page_detected": "Possible duplicate page in the submission.",
    "missing_page_detected": "Possible missing page in the submission.",
    "very_faint": "Handwriting is very faint; transcription reliability is reduced.",
    "poor_image_quality": "Image quality is too poor for reliable grading.",
    "diagram_evaluation_failed": "Diagram comparison could not be completed.",
    "diagram_evaluation_uncertain": "Diagram comparison was inconclusive.",
    "key_diagram_parser_uncertain": "Answer-key diagram extraction was flagged uncertain by the parser.",
    "math_symbol_uncertain": "Mathematical symbols/expressions could not be read reliably.",
}
