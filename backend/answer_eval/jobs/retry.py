"""Retry policy and error classification (Module 18).

Retry transient inference/network issues with bounded exponential backoff.
Permanent input problems (corrupted PDF, invalid rubric, configuration errors)
must NOT be retried — they go straight to the durable failed state (DLQ).
"""

from datetime import UTC, datetime, timedelta

from answer_eval.core.errors import (
    ConfigurationError,
    InferenceServerError,
    InferenceTimeoutError,
    OllamaNotAvailableError,
    PDFValidationError,
    PermanentJobError,
    RubricValidationError,
)

RETRYABLE_EXCEPTIONS = (
    InferenceTimeoutError,
    InferenceServerError,
    OllamaNotAvailableError,
    ConnectionError,
    TimeoutError,
)

PERMANENT_EXCEPTIONS = (
    PDFValidationError,
    ConfigurationError,
    RubricValidationError,
    ValueError,
    FileNotFoundError,
)


def is_retryable(exc: BaseException) -> bool:
    # RETRYABLE_EXCEPTIONS and unknown failures default to retryable, bounded by max_attempts.
    return not isinstance(exc, (*PERMANENT_EXCEPTIONS, PermanentJobError))


class RetryPolicy:
    """Bounded exponential backoff."""

    def __init__(self, max_attempts: int = 3, initial_delay_s: float = 2.0, backoff_factor: float = 2.0) -> None:
        self.max_attempts = max_attempts
        self.initial_delay_s = initial_delay_s
        self.backoff_factor = backoff_factor

    def delay_for_attempt(self, attempt: int) -> float:
        """Delay BEFORE the given attempt number's retry (1-based)."""
        return self.initial_delay_s * (self.backoff_factor ** max(0, attempt - 1))

    def next_attempt_at(self, attempt: int) -> str:
        delay = self.delay_for_attempt(attempt)
        return (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()

    def attempts_exhausted(self, attempt: int) -> bool:
        return attempt >= self.max_attempts


DEFAULT_RETRY_POLICY = RetryPolicy()
