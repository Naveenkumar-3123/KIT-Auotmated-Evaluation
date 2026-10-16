"""Deterministic content hashing and cache-key generation."""

import hashlib
from pathlib import Path
from typing import Any


def calculate_bytes_hash(data: bytes) -> str:
    """Calculate SHA-256 hash of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def calculate_file_hash(file_path: str | Path, chunk_size: int = 65536) -> str:
    """Calculate SHA-256 hash of a file incrementally."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def calculate_dict_hash(d: dict[str, Any]) -> str:
    """Calculate deterministic hash of a dictionary (sorted keys)."""
    import json

    encoded = json.dumps(d, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Version-safe Cache Key Generators
# ---------------------------------------------------------------------------


def generate_pdf_cache_key(pdf_hash: str, dpi: int) -> str:
    """Generate cache key for rendered PDF pages."""
    return f"pdf:{pdf_hash}:dpi_{dpi}"


def generate_preprocessing_cache_key(page_hash: str, config_hash: str) -> str:
    """Generate cache key for preprocessed page image."""
    return f"preprocess:{page_hash}:cfg_{config_hash}"


def generate_ocr_cache_key(image_hash: str, model_id: str, quantization: str, prompt_version: str) -> str:
    """Generate cache key for OCR extraction output."""
    return f"ocr:{image_hash}:{model_id}:{quantization}:{prompt_version}"


def generate_diagram_cache_key(image_hash: str, model_id: str, prompt_version: str) -> str:
    """Generate cache key for diagram extraction output."""
    return f"diagram:{image_hash}:{model_id}:{prompt_version}"


def generate_reconstruction_cache_key(ocr_hashes: list[str], diagram_hashes: list[str], schema_version: str) -> str:
    """Generate cache key for reconstructed canonical answer."""
    content = f"ocr:{','.join(sorted(ocr_hashes))}|diag:{','.join(sorted(diagram_hashes))}|v:{schema_version}"
    return f"reconstruct:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
