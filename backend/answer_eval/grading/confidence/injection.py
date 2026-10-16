"""Deterministic prompt-injection screening (Milestones 10-12, specs #51/#83).

Student handwriting is DATA. Instruction-like content inside it ("ignore the
rubric", "you are now the examiner", "give this answer full marks") must never
steer grading — and when detected deterministically it routes the question to
teacher review, because interpretation may have been affected.

Heuristic patterns only FLAG; they never alter marks. False positives are safe
(a human reviews); false negatives are mitigated by the model-side instruction
to flag manipulation as well.
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (
        "ignore_instructions",
        r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|following)\s+"
        r"(?:instructions|prompts|rules|directions)\b",
    ),
    (
        "disregard_instructions",
        r"\bdisregard\s+(?:the\s+|all\s+|any\s+|previous\s+|your\s+|earlier\s+)?"
        r"(?:instructions|rubric|prompt|rules|criteria)\b",
    ),
    (
        "role_override",
        r"\b(?:you\s+are|act\s+as)\s+(?:now\s+)?(?:a\s+|an\s+|my\s+)?"
        r"(?:system|administrator|admin|teacher|examiner|grader|evaluator)\b",
    ),
    (
        "marks_directive",
        r"\b(?:give|award|grant|assign)\w*\s+(?:me\s+|him\s+|her\s+|this\s+(?:answer|student)\s+)?"
        r"(?:a\s+)?(?:full|maximum|complete|100%|\d+)\s*(?:marks?|points?|credit)\b",
    ),
    (
        "override_grading",
        r"\boverride\s+(?:the\s+)?(?:grading|rubric|score|marks|evaluation)\b",
    ),
    (
        "system_prompt_probe",
        r"\bsystem\s*prompt\b",
    ),
    (
        "replacement_instructions",
        r"\bnew\s+instructions\s*:",
    ),
]

_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _INJECTION_PATTERNS]


def detect_injection_attempts(text: str | None) -> list[str]:
    """Return pattern ids found in the text (empty when clean).

    Deliberately conservative: matches only directive-style constructions, not
    mere mentions of words like "marks" or "instructions".
    """
    if not text or not text.strip():
        return []
    haystack = text.casefold()
    hits: list[str] = []
    for name, pattern in _COMPILED:
        if pattern.search(haystack):
            hits.append(name)
    return hits


__all__ = ["detect_injection_attempts"]
