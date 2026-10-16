"""LocalStorageProvider sandbox + immutability tests."""

from __future__ import annotations

import pytest

from answer_eval.storage import LocalStorageProvider, StorageObjectMissing


def test_put_open_roundtrip(tmp_path) -> None:
    storage = LocalStorageProvider(tmp_path)
    key = storage.put("original-pdfs", "assessments/a1/x.pdf", b"%PDF-1.4 test")
    assert key == "original-pdfs/assessments/a1/x.pdf"
    assert storage.get(key) == b"%PDF-1.4 test"
    assert storage.exists(key)


def test_immutability_same_bytes_ok_conflict_rejected(tmp_path) -> None:
    storage = LocalStorageProvider(tmp_path)
    key = storage.put("answer-keys", "k1.pdf", b"A")
    assert storage.put("answer-keys", "k1.pdf", b"A") == key  # idempotent
    with pytest.raises(ValueError, match="immutable"):
        storage.put("answer-keys", "k1.pdf", b"B")


def test_traversal_outside_root_rejected(tmp_path) -> None:
    storage = LocalStorageProvider(tmp_path)
    with pytest.raises(ValueError, match="sandbox"):
        storage.put("original-pdfs", "../../outside.pdf", b"x")
    with pytest.raises(ValueError, match="sandbox"):
        storage.get("../secret.txt")


def test_missing_object_raises(tmp_path) -> None:
    storage = LocalStorageProvider(tmp_path)
    with pytest.raises(StorageObjectMissing):
        storage.get("original-pdfs/nope.pdf")
    storage.delete("original-pdfs/nope.pdf")  # delete is a no-op when absent
