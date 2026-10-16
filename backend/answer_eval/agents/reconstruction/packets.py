"""Canonical student question packets (Milestone 8, specs #34-35).

One packet per student/question is the ATOMIC evaluation unit sent to the
grading workers. Student diagrams are included as ORIGINAL IMAGE crops stored
via StorageProvider — descriptions never replace the image.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.core.logging import get_logger
from answer_eval.processing.segmentation.schemas import QuestionRegion, RegionType
from answer_eval.storage import StorageProvider

logger = get_logger("agents.packets")


class StudentDiagramImage(BaseModel):
    """Reference to the ORIGINAL cropped diagram image for a question."""

    diagram_id: str = Field(description="e.g. STUDENT-Q11-D1")
    image_object_key: str = Field(description="Storage key of the original crop (immutable)")
    page: int
    bbox: list[float] = Field(description="Normalized [x_min, y_min, x_max, y_max]")


class StudentQuestionPacket(BaseModel):
    """Complete evaluation packet for ONE student + ONE complete question."""

    student_id: str = Field(description="Submission tracking id")
    question_id: str
    pages: list[int] = Field(default_factory=list)
    raw_text: str = ""
    segments: list[dict] = Field(default_factory=list)
    word_count: int = 0
    student_diagram_images: list[StudentDiagramImage] = Field(default_factory=list)
    uncertainties: list[dict] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    mapping_uncertain: bool = False
    provenance: dict = Field(default_factory=dict)


def build_question_packets(
    answers: list[CanonicalStructuredAnswer],
    regions: list[QuestionRegion],
    storage: StorageProvider,
    *,
    upload_diagrams: bool = True,
) -> list[StudentQuestionPacket]:
    """Convert reconstructed answers into packets, storing original diagram crops."""
    by_qid: dict[str, list[QuestionRegion]] = {}
    for region in regions:
        if region.question_id and region.region_type in (RegionType.DIAGRAM, RegionType.MIXED):
            by_qid.setdefault(region.question_id, []).append(region)

    packets: list[StudentQuestionPacket] = []
    for answer in answers:
        qid = answer.question_id
        diagram_images: list[StudentDiagramImage] = []
        if upload_diagrams:
            for ordinal, region in enumerate(
                sorted(by_qid.get(qid, []), key=lambda r: (r.page_number, r.reading_order)),
                start=1,
            ):
                if not region.crop_image_path or not Path(region.crop_image_path).is_file():
                    continue
                png_bytes = Path(region.crop_image_path).read_bytes()
                object_key = storage.put(
                    "student-diagrams",
                    f"{answer.submission_id}/{qid}-D{ordinal}.png",
                    png_bytes,
                    content_type="image/png",
                )
                diagram_images.append(
                    StudentDiagramImage(
                        diagram_id=f"STUDENT-{qid}-D{ordinal}",
                        image_object_key=object_key,
                        page=region.page_number,
                        bbox=[
                            region.bbox.x_min,
                            region.bbox.y_min,
                            region.bbox.x_max,
                            region.bbox.y_max,
                        ],
                    )
                )
        mapping_flags = [f for f in answer.flags if f.startswith("mapping_")]
        packet = StudentQuestionPacket(
            student_id=answer.submission_id,
            question_id=qid,
            pages=sorted(set(answer.source_pages)),
            raw_text=answer.raw_text,
            segments=[segment.model_dump() for segment in answer.segments],
            word_count=answer.word_count,
            student_diagram_images=diagram_images,
            uncertainties=[u.model_dump() for u in answer.uncertainties],
            flags=sorted(set(answer.flags)),
            mapping_uncertain=bool(mapping_flags),
            provenance=answer.provenance.model_dump(),
        )
        packets.append(packet)

    logger.info(
        "question packets built",
        count=len(packets),
        with_diagrams=sum(1 for p in packets if p.student_diagram_images),
    )
    return packets
