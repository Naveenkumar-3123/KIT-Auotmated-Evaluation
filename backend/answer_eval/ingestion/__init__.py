"""Student ZIP ingestion package (Milestone 3)."""

from answer_eval.ingestion.service import (
    IngestionError,
    IngestionResult,
    IngestLimits,
    StudentZipIngestionService,
)
from answer_eval.ingestion.zipscan import DetectedEntry, ZipScanResult, parse_roll_number, scan_zip

__all__ = [
    "DetectedEntry",
    "IngestLimits",
    "IngestionError",
    "IngestionResult",
    "StudentZipIngestionService",
    "ZipScanResult",
    "parse_roll_number",
    "scan_zip",
]
