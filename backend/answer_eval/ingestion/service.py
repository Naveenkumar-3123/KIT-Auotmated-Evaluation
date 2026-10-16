"""Student answer-sheet ingestion service.

Pure scanning lives in `zipscan`; this module ties it to PDF validation
(reusing the existing Module 4 processor), immutable storage, and durable
submission rows. Roll numbers come from filenames; object keys are generated
internally so untrusted names never touch the filesystem.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import asyncpg

from answer_eval.core.hashing import calculate_bytes_hash
from answer_eval.db.repositories import assessments as assessments_repo
from answer_eval.db.repositories import submissions as submissions_repo
from answer_eval.ingestion.zipscan import DetectedEntry, IngestLimits, read_member, scan_zip
from answer_eval.processing.pdf.processor import PDFProcessor
from answer_eval.storage import StorageProvider

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Archive-level rejection (size/count/structure)."""


@dataclass
class IngestionResult:
    assessment_id: str
    detected: int = 0
    valid: int = 0
    invalid: int = 0
    students: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class StudentZipIngestionService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        storage: StorageProvider,
        *,
        limits: IngestLimits | None = None,
    ) -> None:
        self._pool = pool
        self._storage = storage
        self._limits = limits or IngestLimits()
        self._pdf = PDFProcessor(max_file_size_mb=self._limits.max_pdf_bytes / (1024 * 1024))

    async def ingest(
        self,
        *,
        assessment_id: str,
        teacher_id: str,
        zip_bytes: bytes,
    ) -> IngestionResult:
        # Ownership check before touching anything.
        await assessments_repo.require_owned(
            self._pool, assessment_id=assessment_id, teacher_id=teacher_id
        )

        try:
            scan = scan_zip(zip_bytes, self._limits)
        except ValueError as exc:
            raise IngestionError(str(exc)) from exc

        result = IngestionResult(assessment_id=assessment_id)
        existing_submissions = await submissions_repo.list_for_assessment(self._pool, assessment_id)
        seen_hashes: dict[str, str] = {
            s["pdf_sha256"]: s["roll_number"]
            for s in existing_submissions
            if s.get("pdf_sha256") and s.get("roll_number")
        }
        for entry in scan.entries:
            student_row: dict = {
                "roll_number": entry.roll_number,
                "file_name": entry.file_name,
                "status": entry.status,
                "reason": entry.reason,
            }
            if entry.status != "valid":
                result.students.append(student_row)
                continue

            pdf_bytes = read_member(zip_bytes, entry.file_name)
            sha256 = hashlib.sha256(pdf_bytes).hexdigest()

            owner = seen_hashes.get(sha256)
            if owner is not None and owner != str(entry.roll_number):
                student_row["status"] = "invalid_duplicate"
                student_row["reason"] = f"identical file was already provided for roll {owner}"
                result.students.append(student_row)
                continue

            page_count, quality_flags = self._validate_pdf(entry.file_name, pdf_bytes)
            if page_count is None:
                student_row["status"] = "invalid_corrupt"
                student_row["reason"] = "PDF could not be opened or is corrupt"
                result.students.append(student_row)
                continue
            if quality_flags:
                student_row["flags"] = quality_flags

            object_key = self._storage.put(
                "original-pdfs",
                f"assessments/{assessment_id}/{sha256[:12]}-{entry.roll_number}.pdf",
                pdf_bytes,
                content_type="application/pdf",
            )
            seen_hashes[sha256] = str(entry.roll_number)

            try:
                submission = await submissions_repo.upsert_submission(
                    self._pool,
                    assessment_id=assessment_id,
                    roll_number=str(entry.roll_number),
                    pdf_object_key=object_key,
                    pdf_sha256=calculate_bytes_hash(pdf_bytes)[:64],
                    page_count=page_count,
                    flags=list(student_row.get("flags") or []),
                    uploaded_by=teacher_id,
                )
            except ValueError as exc:
                student_row["status"] = "invalid_duplicate"
                student_row["reason"] = str(exc)
                result.students.append(student_row)
                continue
            except Exception as exc:
                logger.exception("Failed to upsert submission for roll %s", entry.roll_number)
                student_row["status"] = "invalid_corrupt"
                student_row["reason"] = f"Failed to save submission: {exc}"
                result.students.append(student_row)
                continue
            duplicate = any(flag in ("reupload_identical", "replaced_file") for flag in (submission.get("flags") or []))
            if duplicate:
                student_row["status"] = "duplicate"
                student_row["reason"] = (
                    "identical file already uploaded" if "reupload_identical" in submission["flags"]
                    else "existing submission replaced with new file"
                )
            student_row["submission_id"] = submission["id"]
            result.students.append(student_row)

        result.detected = len(scan.entries)
        result.valid = sum(1 for s in result.students if s["status"] in ("valid", "duplicate"))
        result.invalid = result.detected - result.valid
        logger.info(
            "ingested zip assessment=%s detected=%s valid=%s invalid=%s",
            assessment_id,
            result.detected,
            result.valid,
            result.invalid,
        )
        return result

    def _validate_pdf(self, filename: str, pdf_bytes: bytes) -> tuple[int | None, list[str]]:
        """Validate using the existing PDF processor; returns (pages, flags)."""
        flags: list[str] = []
        with tempfile.TemporaryDirectory(prefix="evalai-ingest-") as tmp:
            path = Path(tmp) / Path(filename).name
            try:
                path.write_bytes(pdf_bytes)
                validation = self._pdf.validate_pdf(path)
            except Exception:  # noqa: BLE001 - any parser failure means corrupt/unsupported
                logger.info("PDF validation failed for %s", filename, exc_info=True)
                return None, flags
            if not getattr(validation, "is_valid", True):
                return None, flags
            issues = getattr(validation, "issues", None) or []
            for issue in issues:
                severity = str(getattr(issue, "severity", "")).lower()
                message = str(getattr(issue, "message", issue))
                if severity == "error":
                    return None, flags
                if message:
                    flags.append(f"pdf_warning:{message[:80]}")
            metadata = self._pdf.inspect_pdf(path)
            return int(metadata.page_count), flags


__all__ = ["IngestLimits", "IngestionError", "IngestionResult", "StudentZipIngestionService", "DetectedEntry"]
