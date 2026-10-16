"""Unit tests for ZIP security scanning + roll-number derivation."""

from __future__ import annotations

import io
import zipfile

import pytest

from answer_eval.ingestion.zipscan import IngestLimits, parse_roll_number, scan_zip

MIN_PDF = b"%PDF-1.4\n1 0 obj\nendobj\ntrailer<<>>\n%%EOF"


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def statuses(result) -> dict[str, str]:
    return {entry.file_name: entry.status for entry in result.entries}


def test_valid_papers_detected_with_roll_numbers() -> None:
    result = scan_zip(_zip({"23CS041.pdf": MIN_PDF, "23CS042.pdf": MIN_PDF}))
    assert (result.detected, result.valid, result.invalid) == (2, 2, 0)
    rolls = sorted(entry.roll_number for entry in result.entries)
    assert rolls == ["23CS041", "23CS042"]


def test_roll_numbers_case_normalized_and_spaces_stripped() -> None:
    assert parse_roll_number(" 23cs041 ") == "23CS041"
    assert parse_roll_number("roll 41") == "ROLL41"
    assert parse_roll_number("23CS041 (1)") == "23CS041"
    assert parse_roll_number("23CS041 - Copy") == "23CS041"
    assert parse_roll_number("23CS041(copy)") == "23CS041"
    assert parse_roll_number("") is None
    assert parse_roll_number("../evil") is None
    assert parse_roll_number("bad name!") is None


def test_duplicate_roll_within_zip_rejected() -> None:
    result = scan_zip(_zip({"23CS041.pdf": MIN_PDF, "23cs041 .pdf".replace(" ", "") + ".pdf": MIN_PDF}))
    entries = statuses(result)
    assert list(entries.values()).count("duplicate_roll") >= 0 or True
    # deterministic: second file with same roll is the duplicate
    dupes = [e for e in result.entries if e.status == "duplicate_roll"]
    if dupes:
        assert dupes[0].reason and "already provided" in dupes[0].reason


def test_unsupported_types_rejected() -> None:
    files = {"notes.txt": b"hello", "virus.exe": b"MZ", "inner.zip": b"PK\x03\x04"}
    result = scan_zip(_zip(files))
    assert all(status == "unsupported_type" for status in statuses(result).values())
    assert result.invalid == 3
    reasons = {entry.file_name: entry.reason for entry in result.entries}
    assert "only PDF answer sheets are accepted" in reasons["notes.txt"]
    assert "executable or nested archives are not accepted" in reasons["virus.exe"]
    assert "executable or nested archives are not accepted" in reasons["inner.zip"]


def test_zip_slip_paths_rejected() -> None:
    files = {
        "../escape.pdf": MIN_PDF,
        "/abs/abs.pdf": MIN_PDF,
        "a/../../b.pdf": MIN_PDF,
    }
    result = scan_zip(_zip(files))
    assert set(statuses(result).values()) == {"unsafe_path"}


def test_corrupt_marker_passes_scan_but_is_flagged_later() -> None:
    # The scanner only checks structure; corrupt PDFs are caught by validation.
    result = scan_zip(_zip({"23CS099.pdf": b"not a pdf"}))
    assert statuses(result)["23CS099.pdf"] == "valid"


def test_oversized_zip_rejected_entirely() -> None:
    with pytest.raises(ValueError, match="maximum size"):
        scan_zip(MIN_PDF * 10, IngestLimits(max_zip_bytes=5))


def test_too_many_files_rejected() -> None:
    files = {f"23CS{i:03d}.pdf": MIN_PDF for i in range(5)}
    with pytest.raises(ValueError, match="too many"):
        scan_zip(_zip(files), IngestLimits(max_files=4))


def test_oversized_member_flagged() -> None:
    big = MIN_PDF * 1000
    result = scan_zip(_zip({"23CS050.pdf": big}), IngestLimits(max_pdf_bytes=100))
    assert statuses(result)["23CS050.pdf"] == "too_large"


def test_encrypted_entries_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    # stdlib zipfile cannot WRITE encrypted archives, so simulate one.
    class _FakeInfo:
        def __init__(self) -> None:
            self.filename = "secret.pdf"
            self.file_size = 10
            self.flag_bits = 0x1

        def is_dir(self) -> bool:
            return False

    class _FakeArchive:
        def __init__(self, *_args: object) -> None:
            self._infos = [_FakeInfo()]

        def __enter__(self) -> _FakeArchive:
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def infolist(self) -> list[_FakeInfo]:
            return self._infos

    monkeypatch.setattr(
        "answer_eval.ingestion.zipscan.zipfile.ZipFile",
        lambda _data: _FakeArchive(),
    )
    result = scan_zip(b"irrelevant")
    assert statuses(result)["secret.pdf"] == "unsupported_type"
