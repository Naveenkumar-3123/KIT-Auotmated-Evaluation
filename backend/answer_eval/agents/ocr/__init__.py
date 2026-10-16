"""OCR agent package exports."""

from answer_eval.agents.ocr.agent import OCRAgent, count_words_deterministic
from answer_eval.agents.ocr.schemas import OCRResult, OCRUncertainSpan

__all__ = [
    "OCRAgent",
    "OCRResult",
    "OCRUncertainSpan",
    "count_words_deterministic",
]
