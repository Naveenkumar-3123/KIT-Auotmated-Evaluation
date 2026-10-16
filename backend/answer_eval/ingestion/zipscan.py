"""Student answer-sheet ZIP ingestion (Milestone 3).

Security posture:
    * hard size/count limits on the archive and its members
    * ZIP-Slip defence (absolute paths, drive letters, '..' segments)
    * extension allowlist: only .pdf student papers are accepted
    * encrypted archives rejected
    * filenames are never trusted: roll numbers are derived and sanitized,
      internal object keys are generated server-side
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MAX_FILENAME_BYTES = 512

_ROLL_ALLOWED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DANGEROUS_SUFFIXES = (".exe", ".bat", ".cmd", ".com", ".scr", ".ps1", ".sh", ".js", ".vbs", ".msi", ".zip", ".rar", ".7z", ".gz", ".tar")


@dataclass(frozen=True)
class IngestLimits:
    max_zip_bytes: int = 200 * 1024 * 1024
    max_total_uncompressed_bytes: int = 1024 * 1024 * 1024
    max_files: int = 300
    max_pdf_bytes: int = 50 * 1024 * 1024


@dataclass
class DetectedEntry:
    """One archive member as seen by the scanner."""

    file_name: str
    roll_number: str | None = None
    status: str = "valid"  # valid | invalid_filename | unsupported_type | unsafe_path | duplicate_roll | too_large
    reason: str | None = None
    uncompressed_size: int = 0


@dataclass
class ZipScanResult:
    detected: int = 0
    valid: int = 0
    invalid: int = 0
    entries: list[DetectedEntry] = field(default_factory=list)

    def add(self, entry: DetectedEntry) -> None:
        self.detected += 1
        if entry.status == "valid":
            self.valid += 1
        else:
            self.invalid += 1
        self.entries.append(entry)


def parse_roll_number(filename_stem: str) -> str | None:
    """Derive a safe roll number from an uploaded filename stem."""
    # Strip Windows copy suffixes like " (1)", "(1)", " - Copy", "(copy)"
    cleaned = re.sub(r"\s*\(\d+\)$", "", filename_stem.strip())
    cleaned = re.sub(r"\s*-\s*copy$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(copy\)$", "", cleaned, flags=re.IGNORECASE)
    candidate = cleaned.strip().replace(" ", "")
    if not _ROLL_ALLOWED.match(candidate):
        return None
    return candidate.upper()


def scan_zip(data: bytes, limits: IngestLimits | None = None) -> ZipScanResult:
    limits = limits or IngestLimits()
    result = ZipScanResult()

    if len(data) > limits.max_zip_bytes:
        raise ValueError(
            f"ZIP exceeds maximum size ({len(data)} bytes > {limits.max_zip_bytes})"
        )

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > limits.max_files:
            raise ValueError(f"ZIP contains too many files ({len(infos)} > {limits.max_files})")

        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > limits.max_total_uncompressed_bytes:
            raise ValueError("ZIP uncompressed contents exceed the maximum allowed size")

        for info in sorted(infos, key=lambda i: i.filename):
            if info.flag_bits & 0x1:
                result.add(DetectedEntry(info.filename, status="unsupported_type", reason="encrypted entries are not supported"))
                continue
            name = info.filename
            if len(name.encode("utf-8", "surrogateescape")) > MAX_FILENAME_BYTES:
                result.add(DetectedEntry(name, status="invalid_filename", reason="filename too long"))
                continue

            path = PurePosixPath(name.replace("\\", "/"))
            parts = path.parts
            if path.is_absolute() or ":" in path.drive or any(part == ".." for part in parts):
                result.add(DetectedEntry(name, status="unsafe_path", reason="path traversal rejected"))
                continue

            suffix = path.suffix.lower()
            if suffix != ".pdf":
                hint = "executable or nested archives are not accepted" if suffix in _DANGEROUS_SUFFIXES else "only PDF answer sheets are accepted"
                result.add(DetectedEntry(name, status="unsupported_type", reason=hint))
                continue

            if info.file_size > limits.max_pdf_bytes:
                result.add(DetectedEntry(name, status="too_large", reason="individual PDF exceeds size limit"))
                continue

            roll = parse_roll_number(path.stem)
            if roll is None:
                result.add(DetectedEntry(name, status="invalid_filename", reason="filename must be the student roll number, e.g. 23CS041.pdf"))
                continue

            clash = next((e for e in result.entries if e.roll_number == roll), None)
            if clash is not None:
                result.add(DetectedEntry(name, roll_number=roll, status="duplicate_roll", reason=f"roll number {roll} already provided by {clash.file_name}"))
                continue

            result.add(DetectedEntry(name, roll_number=roll, status="valid"))

    return result


def read_member(data: bytes, member_name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(member_name)
