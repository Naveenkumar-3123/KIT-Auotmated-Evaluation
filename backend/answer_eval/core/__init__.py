"""Core module exports."""

from answer_eval.core.config import Settings, load_settings
from answer_eval.core.errors import (
    AnswerEvalError,
    DiagramExtractionError,
    ImageProcessingError,
    InferenceError,
    InferenceOOMError,
    InferenceTimeoutError,
    ModelNotAvailableError,
    ModelStartupError,
    OCRExtractionError,
    PDFProcessingError,
    PDFValidationError,
    ReconstructionError,
    SegmentationError,
    UnsupportedCapabilityError,
)
from answer_eval.core.hashing import (
    calculate_bytes_hash,
    calculate_dict_hash,
    calculate_file_hash,
)
from answer_eval.core.logging import bind_context, clear_context, configure_logging, get_logger
from answer_eval.core.provenance import Provenance

__all__ = [
    "AnswerEvalError",
    "DiagramExtractionError",
    "ImageProcessingError",
    "InferenceError",
    "InferenceOOMError",
    "InferenceTimeoutError",
    "ModelNotAvailableError",
    "ModelStartupError",
    "OCRExtractionError",
    "PDFProcessingError",
    "PDFValidationError",
    "Provenance",
    "ReconstructionError",
    "SegmentationError",
    "Settings",
    "UnsupportedCapabilityError",
    "bind_context",
    "calculate_bytes_hash",
    "calculate_dict_hash",
    "calculate_file_hash",
    "clear_context",
    "configure_logging",
    "get_logger",
    "load_settings",
]
