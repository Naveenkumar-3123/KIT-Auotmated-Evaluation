"""Unit tests for core foundation modules."""

from pathlib import Path

from answer_eval.core.config import load_settings
from answer_eval.core.errors import (
    AnswerEvalError,
    InferenceOOMError,
    PDFValidationError,
)
from answer_eval.core.hashing import (
    calculate_bytes_hash,
    calculate_dict_hash,
    generate_ocr_cache_key,
    generate_pdf_cache_key,
    generate_reconstruction_cache_key,
)
from answer_eval.core.provenance import Provenance


def test_normalized_errors() -> None:
    err = PDFValidationError("File is invalid", details={"file": "test.pdf"})
    d = err.to_dict()
    assert d["error_type"] == "PDFValidationError"
    assert d["message"] == "File is invalid"
    assert d["details"]["file"] == "test.pdf"

    oom = InferenceOOMError("Out of memory on GPU 0")
    assert isinstance(oom, AnswerEvalError)


def test_hashing_and_cache_keys() -> None:
    data = b"hello answer paper evaluation"
    h1 = calculate_bytes_hash(data)
    h2 = calculate_bytes_hash(data)
    assert h1 == h2
    assert len(h1) == 64

    dict_hash = calculate_dict_hash({"b": 2, "a": 1})
    dict_hash_same = calculate_dict_hash({"a": 1, "b": 2})
    assert dict_hash == dict_hash_same

    pdf_key = generate_pdf_cache_key("abcd1234", dpi=300)
    assert pdf_key == "pdf:abcd1234:dpi_300"

    ocr_key = generate_ocr_cache_key("imghash", "qwen3_vl_4b", "Q8_0", "v1")
    assert ocr_key == "ocr:imghash:qwen3_vl_4b:Q8_0:v1"

    recon_key = generate_reconstruction_cache_key(["hash1", "hash2"], ["diag1"], "v1")
    assert recon_key.startswith("reconstruct:")


def test_provenance_schema() -> None:
    prov = Provenance(
        submission_id="SUB-001",
        page_number=1,
        region_id="REG-01",
        question_id="Q1",
        source_image_hash="abc123hash",
        model_id="qwen_vl_4b_q8",
        request_id="req-999",
    )
    assert prov.submission_id == "SUB-001"
    assert prov.timestamp is not None
    assert prov.model_family == "qwen3_vl"


def test_settings_loader(temp_workspace: Path) -> None:
    settings = load_settings()
    assert settings.active_model_profile in ("qwen3_vl_8b_local", "qwen3_vl_4b", "qwen_vl_4b_q8", "qwen_vl_4b_q4")
    assert settings.vram_safety_margin_gb == 1.5
    assert len(settings.oom_resolution_tiers) >= 3
