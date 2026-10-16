"""Configuration loader and settings management."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

from answer_eval.core.errors import ConfigurationError

# Load .env if present
load_dotenv()


class OllamaSettings(BaseModel):
    """Ollama OpenAI-compatible connection and runtime settings."""

    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3-vl:4b"
    api_key: str = "ollama"
    timeout_seconds: int = 120
    max_retries: int = 2


class OCRSettings(BaseModel):
    """
    Centralized OCR inference configuration (Ollama vision OCR path).

    Primary environment variables (see .env.example):
        OLLAMA_OCR_MODEL        -> model        ('' = inherit the global Ollama model)
        OLLAMA_OCR_NUM_CTX      -> num_ctx
        OLLAMA_OCR_NUM_PREDICT  -> num_predict
        OLLAMA_OCR_TEMPERATURE  -> temperature

    Legacy names OCR_TEMPERATURE / OCR_NUM_PREDICT / OCR_THINKING /
    OCR_MAX_ATTEMPTS / OCR_MIN_VALID_CHARS remain supported as fallbacks and
    are overridden by the OLLAMA_OCR_* names above.
    """

    # '' = inherit settings.ollama.model / VISION_MODEL so the global vision
    # model knob stays the single source of truth unless explicitly overridden.
    model: str = ""
    # Context window for vision + prompt + generated text. Ollama's previous
    # default (~4096) was insufficient for larger vision crops because image
    # tokens consumed most of the window before generation started.
    # 16384 is the currently tested OCR default.
    num_ctx: int = 16384
    num_predict: int = 4096  # max tokens an OCR request may generate
    temperature: float = 0.0  # deterministic transcription
    thinking_enabled: bool = False  # Qwen3 reasoning OFF for OCR requests
    max_attempts: int = 2  # controlled retry cap for transient/empty responses (no infinite loops)
    min_valid_chars: int = 2  # below this, a non-empty response is treated as suspiciously tiny

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str) -> str:
        return (v or "").strip()  # empty string is allowed: means "inherit"

    @field_validator("num_ctx")
    @classmethod
    def _validate_num_ctx(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(
                f"OLLAMA_OCR_NUM_CTX must be > 0 (got {v}). "
                "The context window must fit image tokens + prompt + generated text."
            )
        return v

    @field_validator("num_predict")
    @classmethod
    def _validate_num_predict(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"OLLAMA_OCR_NUM_PREDICT must be > 0 (got {v}).")
        return v

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"OLLAMA_OCR_TEMPERATURE must be >= 0 (got {v}).")
        return v

    @field_validator("max_attempts")
    @classmethod
    def _validate_max_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"OCR_MAX_ATTEMPTS must be >= 1 (got {v}).")
        return v

    @field_validator("min_valid_chars")
    @classmethod
    def _validate_min_valid_chars(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"OCR_MIN_VALID_CHARS must be >= 1 (got {v}).")
        return v


class LlamaServerSettings(BaseModel):
    path: str = "llama-server"
    host: str = "127.0.0.1"
    port: int = 8090
    startup_timeout_seconds: int = 120
    health_check_interval_seconds: int = 2
    health_check_retries: int = 30


class StructuredOutputSettings(BaseModel):
    max_repair_retries: int = 2
    validate_json_schema: bool = True


class CacheSettings(BaseModel):
    enabled: bool = True
    backend: str = "filesystem"


class Settings(BaseModel):
    """Application settings loaded from settings.yaml + environment."""

    ai_provider: str = Field(default="gemini")
    active_model_profile: str = Field(default="gemini_flash_latest")
    log_level: str = Field(default="INFO")
    log_inference_timing: bool = Field(default=True)
    log_memory_snapshots: bool = Field(default=True)

    vram_safety_margin_gb: float = Field(default=1.5)
    max_oom_retries: int = Field(default=3)
    oom_resolution_tiers: list[int] = Field(default_factory=lambda: [1048576, 589824, 262144, 147456])

    models_dir: str = Field(default="models")
    prompts_dir: str = Field(default="answer_eval/prompts/templates")
    data_dir: str = Field(default="data")
    cache_dir: str = Field(default="cache")
    benchmarks_dir: str = Field(default="benchmarks")

    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    llama_server: LlamaServerSettings = Field(default_factory=LlamaServerSettings)
    structured_output: StructuredOutputSettings = Field(default_factory=StructuredOutputSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    ocr: OCRSettings = Field(default_factory=OCRSettings)

    # Base workspace path
    workspace_root: Path = Field(default_factory=lambda: Path(os.getcwd()))

    def get_path(self, relative_path: str) -> Path:
        """Resolve a path relative to workspace_root if not absolute."""
        p = Path(relative_path)
        if p.is_absolute():
            return p
        return self.workspace_root / p


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from yaml file with env var overrides."""
    workspace_root = Path(os.getcwd())
    config_path = workspace_root / "config" / "settings.yaml" if config_path is None else Path(config_path)

    raw_config: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    raw_config = loaded
        except Exception as e:
            raise ConfigurationError(f"Failed to read settings from {config_path}: {e}") from e

    # Environment variable overrides
    if ai_provider_env := os.getenv("AI_PROVIDER"):
        raw_config["ai_provider"] = ai_provider_env

    if model_profile_env := os.getenv("MODEL_PROFILE"):
        raw_config["active_model_profile"] = model_profile_env

    if vision_model_env := os.getenv("VISION_MODEL"):
        raw_config.setdefault("ollama", {})["model"] = vision_model_env

    if ollama_url_env := os.getenv("OLLAMA_BASE_URL"):
        raw_config.setdefault("ollama", {})["base_url"] = ollama_url_env

    if ollama_key_env := os.getenv("OLLAMA_API_KEY"):
        raw_config.setdefault("ollama", {})["api_key"] = ollama_key_env

    if ollama_timeout_env := os.getenv("OLLAMA_TIMEOUT"):
        raw_config.setdefault("ollama", {})["timeout_seconds"] = ollama_timeout_env

    if ollama_retries_env := os.getenv("OLLAMA_MAX_RETRIES"):
        raw_config.setdefault("ollama", {})["max_retries"] = ollama_retries_env

    # OCR inference overrides. Values are passed as raw strings so pydantic
    # performs coercion + validation centrally (e.g. "banana" for a numeric
    # field fails with a clear ConfigurationError instead of an obscure
    # runtime error deep inside OCR processing).
    ocr_overrides: dict[str, Any] = {}
    for env_name, key in (
        ("OLLAMA_OCR_MODEL", "model"),
        ("OLLAMA_OCR_NUM_CTX", "num_ctx"),
        ("OLLAMA_OCR_NUM_PREDICT", "num_predict"),
        ("OLLAMA_OCR_TEMPERATURE", "temperature"),
    ):
        val = os.getenv(env_name)
        if val is not None and val.strip() != "":
            ocr_overrides[key] = val.strip()

    # Legacy OCR_* names remain supported; OLLAMA_OCR_* takes precedence.
    for env_name, key in (
        ("OCR_TEMPERATURE", "temperature"),
        ("OCR_NUM_PREDICT", "num_predict"),
        ("OCR_THINKING", "thinking_enabled"),
        ("OCR_MAX_ATTEMPTS", "max_attempts"),
        ("OCR_MIN_VALID_CHARS", "min_valid_chars"),
    ):
        val = os.getenv(env_name)
        if val is not None and val.strip() != "" and key not in ocr_overrides:
            ocr_overrides[key] = val.strip()

    if ocr_overrides:
        raw_config.setdefault("ocr", {}).update(ocr_overrides)

    if log_level_env := os.getenv("LOG_LEVEL"):
        raw_config["log_level"] = log_level_env

    if server_port_env := os.getenv("LLAMA_SERVER_PORT"):
        raw_config.setdefault("llama_server", {})["port"] = server_port_env

    if server_host_env := os.getenv("LLAMA_SERVER_HOST"):
        raw_config.setdefault("llama_server", {})["host"] = server_host_env

    if server_path_env := os.getenv("LLAMA_SERVER_PATH"):
        raw_config.setdefault("llama_server", {})["path"] = server_path_env

    raw_config["workspace_root"] = workspace_root
    try:
        return Settings(**raw_config)
    except ValidationError as e:
        raise ConfigurationError(
            f"Invalid application configuration (check environment variables and "
            f"{config_path}):{os.linesep}{e}"
        ) from e
