"""Question mapping: left-margin anchors + cross-page QuestionSpans."""

from answer_eval.processing.mapping.header_anchors import (
    build_header_observations,
    extract_header_strip_png,
    harvest_header_mapping,
    harvest_header_markers,
    repair_missing_tail,
)
from answer_eval.processing.mapping.mapper import QuestionSpanMapper, assign_regions
from answer_eval.processing.mapping.markers import detect_markers, make_line, parse_marker_text
from answer_eval.processing.mapping.schemas import (
    LineObservation,
    MarkerPosition,
    QuestionMappingResult,
    QuestionSpan,
)
from answer_eval.processing.mapping.semantic_mapper import (
    apply_semantic_assignments,
    build_semantic_prompt,
    candidate_regions_for_missing,
    parse_semantic_assignments,
    semantic_mapping_fallback,
)

__all__ = [
    "LineObservation",
    "MarkerPosition",
    "QuestionMappingResult",
    "QuestionSpan",
    "QuestionSpanMapper",
    "apply_semantic_assignments",
    "assign_regions",
    "build_header_observations",
    "build_semantic_prompt",
    "candidate_regions_for_missing",
    "detect_markers",
    "extract_header_strip_png",
    "harvest_header_mapping",
    "harvest_header_markers",
    "make_line",
    "parse_marker_text",
    "parse_semantic_assignments",
    "repair_missing_tail",
    "semantic_mapping_fallback",
]
