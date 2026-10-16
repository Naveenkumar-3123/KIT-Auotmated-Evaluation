"""Unit tests for centralized OCR inference configuration (env -> Settings -> provider)."""

import pytest

from answer_eval.core.config import OCRSettings, load_settings
from answer_eval.core.errors import ConfigurationError

OCR_ENV_VARS = [
    "OLLAMA_OCR_MODEL",
    "OLLAMA_OCR_NUM_CTX",
    "OLLAMA_OCR_NUM_PREDICT",
    "OLLAMA_OCR_TEMPERATURE",
    "OCR_THINKING",
    "OCR_TEMPERATURE",
    "OCR_NUM_PREDICT",
    "OCR_MAX_ATTEMPTS",
    "OCR_MIN_VALID_CHARS",
]


@pytest.fixture(autouse=True)
def _clean_ocr_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from ambient environment / developer .env values."""
    for var in OCR_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_dataclass_defaults() -> None:
    s = OCRSettings()
    assert s.model == ""  # '' = inherit global VISION_MODEL / ollama.model
    assert s.num_ctx == 16384
    assert s.num_predict == 4096
    assert s.temperature == 0.0


def test_load_settings_defaults() -> None:
    s = load_settings()
    assert s.ollama.model == "qwen3-vl:4b"
    assert s.ocr.model == ""
    assert s.ocr.num_ctx == 16384
    assert s.ocr.num_predict == 4096
    assert s.ocr.temperature == 0.0
    assert s.ocr.thinking_enabled is False


def test_env_overrides_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_OCR_NUM_CTX", "32768")
    monkeypatch.setenv("OLLAMA_OCR_NUM_PREDICT", "8192")
    monkeypatch.setenv("OLLAMA_OCR_TEMPERATURE", "0")
    monkeypatch.setenv("OLLAMA_OCR_MODEL", "qwen3-vl:8b")

    s = load_settings()
    assert s.ocr.num_ctx == 32768
    assert s.ocr.num_predict == 8192
    assert s.ocr.temperature == 0.0
    assert s.ocr.model == "qwen3-vl:8b"


def test_invalid_num_ctx_not_numeric(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_OCR_NUM_CTX", "banana")
    with pytest.raises(ConfigurationError, match="num_ctx"):
        load_settings()


@pytest.mark.parametrize("value", ["0", "-1024"])
def test_invalid_num_ctx_range(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OLLAMA_OCR_NUM_CTX", value)
    with pytest.raises(ConfigurationError, match="OLLAMA_OCR_NUM_CTX"):
        load_settings()


@pytest.mark.parametrize("value", ["0", "-5"])
def test_invalid_num_predict(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OLLAMA_OCR_NUM_PREDICT", value)
    with pytest.raises(ConfigurationError, match="OLLAMA_OCR_NUM_PREDICT"):
        load_settings()


def test_invalid_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_OCR_TEMPERATURE", "-1.5")
    with pytest.raises(ConfigurationError, match="OLLAMA_OCR_TEMPERATURE"):
        load_settings()


def test_legacy_names_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_NUM_PREDICT", "2048")
    monkeypatch.setenv("OCR_MAX_ATTEMPTS", "3")
    s = load_settings()
    assert s.ocr.num_predict == 2048
    assert s.ocr.max_attempts == 3


def test_new_names_take_precedence_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_NUM_PREDICT", "2048")
    monkeypatch.setenv("OLLAMA_OCR_NUM_PREDICT", "8192")
    assert load_settings().ocr.num_predict == 8192
