"""Left-margin question anchor detection (Milestone 7, spec #31).

Students write the question number near the FAR LEFT margin. That position is
the strong structural signal; regex shape, reading order and the known valid
question numbers from the answer key are combined with it.

A line is a marker candidate only when ALL of the following hold:
  1. its text matches a question-marker pattern (``1``, ``1.``, ``Q1``,
     ``Q.1``, ``11``, ``12(a)`` ...), and
  2. it sits inside the left-margin band, and
  3. (optionally enforced) its number is in the valid question set.
Body lines that merely *start* with a number ("16 marks are awarded...") are
rejected by rule 2, not silently misassigned.
"""

from __future__ import annotations

import re

from answer_eval.processing.mapping.schemas import LineObservation, MarkerPosition
from answer_eval.processing.segmentation.schemas import BoundingBox

# Normalized x threshold for "near the far left margin".
DEFAULT_LEFT_MARGIN_X = 0.15

# Marker shapes:
#   Q11 / Q.11 / q11 -> prefix form
#   11 / 11. / 11) / 11: -> bare number with optional separator
#   12(a) / 12 a / 11.(a) -> optional sub-part suffix
_Q_PREFIX = r"(?:[Qq]\s*[.．]?\s*)?"
_NUM = r"(\d{1,3})"
_SUBPART = r"(?:\s*[\(\[]?\s*([a-z])\s*[\)\]])?"
_MARKER_RE = re.compile(rf"^{_Q_PREFIX}{_NUM}{_SUBPART}\s*(?:[.．:\-–)]\s*)?.*$")
_TRAILING_WORD_RE = re.compile(r"^\d{1,3}\s+[a-zA-Z]{3,}")  # "11 The process..." without separator


def parse_marker_text(text: str) -> tuple[int, str | None] | None:
    """Return (question_number, sub_part) if *text* has marker SHAPE, else None.

    Purely lexical — no positional or validity checks.
    """
    stripped = text.strip()
    if not stripped:
        return None
    match = _MARKER_RE.match(stripped)
    if match is None:
        return None
    # A bare number directly followed by several words ("11 The process")
    # is body text, not an anchor — require a separator/pattern boundary.
    if _TRAILING_WORD_RE.match(stripped):
        return None
    number = int(match.group(1))
    if number < 1:
        # "0" / "00" is OCR noise (smudges, borders), never a question marker;
        # MarkerPosition requires >= 1 and must never see a zero.
        return None
    sub_part = match.group(2)
    return number, sub_part


def _find_ruled_line_indices(observations: list[LineObservation]) -> set[int]:
    bare_indices = []
    bare_nums = []
    for idx, obs in enumerate(observations):
        s = obs.text.strip()
        m = re.fullmatch(r"\(?\s*(\d{1,2})\s*\)?", s)
        if m and not re.search(r"[Qq]uestion|[Qq]\b", s):
            bare_indices.append(idx)
            bare_nums.append(int(m.group(1)))
    
    if len(bare_nums) >= 3:
        sequential_steps = sum(1 for i in range(len(bare_nums) - 1) if 0 < bare_nums[i+1] - bare_nums[i] <= 3)
        if sequential_steps >= 2:
            return set(bare_indices)
    return set()


def detect_markers(
    lines_by_page: dict[int, list[LineObservation]],
    valid_question_numbers: list[int],
    *,
    left_margin_x: float = DEFAULT_LEFT_MARGIN_X,
) -> dict[int, list[MarkerPosition]]:
    """Detect question anchors per page, sorted by reading order.

    Markers whose number is NOT in ``valid_question_numbers`` are still
    returned but carry a warning so the mapper can flag uncertainty instead of
    silently assigning content to a guessed question.
    """
    valid = set(valid_question_numbers)
    markers: dict[int, list[MarkerPosition]] = {}
    for page_number in sorted(lines_by_page):
        page_lines = lines_by_page[page_number]
        ruled_indices = _find_ruled_line_indices(page_lines)
        page_markers: list[MarkerPosition] = []
        for index, line in enumerate(page_lines):
            if index in ruled_indices:
                continue
            parsed = parse_marker_text(line.text)
            if parsed is None:
                continue
            if line.bbox.x_min > left_margin_x:
                continue  # not at the far-left margin -> body text
            number, _sub_part = parsed
            warnings: list[str] = []
            confidence = 0.9
            if number not in valid:
                warnings.append("question_number_not_in_answer_key")
                confidence = 0.4
            if line.bbox.x_min > left_margin_x * 0.5:
                # Not flush with the margin — weaker positional signal.
                confidence = min(confidence, 0.6)
                warnings.append("marker_not_flush_left")
            page_markers.append(
                MarkerPosition(
                    question_number=number,
                    raw_text=line.text.strip(),
                    page_number=page_number,
                    y_center=round((line.bbox.y_min + line.bbox.y_max) / 2.0, 4),
                    line_index=index,
                    confidence=confidence,
                    warnings=warnings,
                )
            )
        if page_markers:
            markers[page_number] = page_markers
    return markers


def make_line(page_number: int, text: str, *, x_min: float, y_min: float, height: float = 0.02, order: int = 1) -> LineObservation:
    """Test/adapter helper to build a LineObservation quickly."""
    return LineObservation(
        page_number=page_number,
        text=text,
        bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=min(1.0, x_min + 0.8), y_max=y_min + height),
        reading_order=order,
    )
