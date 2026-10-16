"""Normalized error hierarchy for Answer Paper Evaluation System."""

from typing import Any


class AnswerEvalError(Exception):
    """Base exception for all domain errors in the evaluation system."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert error to structured dict for safe logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Module 4: PDF Errors
# ---------------------------------------------------------------------------
class PDFProcessingError(AnswerEvalError):
    """Base error for PDF processing failures."""


class PDFValidationError(PDFProcessingError):
    """Raised when PDF file fails security/integrity validation."""


class PDFEncryptedError(PDFValidationError):
    """Raised when PDF is password-protected or encrypted."""


class PDFCorruptError(PDFValidationError):
    """Raised when PDF file is corrupt or unreadable."""


class PDFRenderError(PDFProcessingError):
    """Raised when rendering a PDF page to an image fails."""


# ---------------------------------------------------------------------------
# Module 5: Image Preprocessing Errors
# ---------------------------------------------------------------------------
class ImageProcessingError(AnswerEvalError):
    """Base error for image preprocessing failures."""


class ImageQualityError(ImageProcessingError):
    """Raised when an image fails minimum acceptable quality thresholds."""


# ---------------------------------------------------------------------------
# Module 6: Segmentation Errors
# ---------------------------------------------------------------------------
class SegmentationError(AnswerEvalError):
    """Base error for document layout & question segmentation failures."""


# ---------------------------------------------------------------------------
# Hardware & Model Registry Errors
# ---------------------------------------------------------------------------
class HardwareDetectionError(AnswerEvalError):
    """Raised when hardware detection fails unexpectedly."""


class ModelProfileError(AnswerEvalError):
    """Raised for invalid or missing model profiles."""


class ModelNotAvailableError(ModelProfileError):
    """Raised when the specified model profile or checkpoint is not found/enabled."""


class UnsupportedCapabilityError(ModelProfileError):
    """Raised when an agent requests a capability not supported by the active model."""


# ---------------------------------------------------------------------------
# Runtime & Inference Errors (Modules 7 & 8)
# ---------------------------------------------------------------------------
class RuntimeErrorBase(AnswerEvalError):
    """Base error for local server and runtime execution."""


class ModelStartupError(RuntimeErrorBase):
    """Raised when llama-server fails to start or pass initial health check."""


class InferenceError(AnswerEvalError):
    """Base error for inference execution failures."""


class InferenceTimeoutError(InferenceError):
    """Raised when an inference request times out."""


class InferenceServerError(InferenceError):
    """Raised when the inference server returns a 5xx or connection error."""


class InferenceOOMError(InferenceError):
    """Raised when inference causes a CUDA/system Out-Of-Memory failure."""


class InferenceOutputValidationError(InferenceError):
    """Raised when model output fails JSON schema validation after retry."""


class OllamaNotAvailableError(InferenceServerError):
    """Raised when Ollama server is unreachable or offline."""


class ModelNotFoundError(ModelNotAvailableError):
    """Raised when the specified model is not installed/pulled in Ollama."""


class VisionRequestError(InferenceError):
    """Raised when a vision processing or image encoding request fails."""


# ---------------------------------------------------------------------------
# Perception Agents Errors (Modules 9, 10, 11)
# ---------------------------------------------------------------------------
class AgentError(AnswerEvalError):
    """Base error for perception agents."""


class OCRExtractionError(AgentError):
    """Raised when OCR agent fails to extract transcription."""


class DiagramExtractionError(AgentError):
    """Raised when Diagram agent fails to analyze visual elements."""


class ReconstructionError(AnswerEvalError):
    """Raised when answer reconstruction or multi-page continuation fails."""


# ---------------------------------------------------------------------------
# Grading Errors (Modules 12-16)
# ---------------------------------------------------------------------------
class GradingError(AnswerEvalError):
    """Base error for grading modules."""


class RubricValidationError(GradingError):
    """Raised when a question rubric / answer key is invalid."""


class EvaluationValidationError(GradingError):
    """Raised when an evaluation/verification result fails structural or score validation."""


class StrictnessPolicyError(GradingError):
    """Raised for invalid strictness scores or policy overrides."""


class RiskEngineError(GradingError):
    """Raised when the confidence/risk engine receives inconsistent inputs."""


# ---------------------------------------------------------------------------
# Jobs / Workflow Errors (Modules 17-18)
# ---------------------------------------------------------------------------
class WorkflowError(AnswerEvalError):
    """Base error for LangGraph workflow failures."""


class JobError(AnswerEvalError):
    """Base error for job queue / worker failures."""


class PermanentJobError(JobError):
    """Classified permanent failure: must NOT be retried."""


class RetryableJobError(JobError):
    """Classified transient failure: may be retried with backoff."""


# ---------------------------------------------------------------------------
# Configuration & Cache Errors
# ---------------------------------------------------------------------------
class ConfigurationError(AnswerEvalError):
    """Raised for invalid configuration settings."""


class CacheError(AnswerEvalError):
    """Raised when cache read/write fails."""
