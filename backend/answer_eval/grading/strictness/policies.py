"""Versioned strictness band data (Module 13).

Calibration data lives here — NOT scattered through code. Bump
STRICTNESS_POLICY_VERSION (e.g. strictness-v2) when changing what a strictness
score means so existing exams keep their original semantics.
"""

from typing import Any

STRICTNESS_POLICY_VERSION = "strictness-v1"

# Inclusive lower bound, exclusive upper bound (last band includes 100).
STRICTNESS_BANDS: list[dict[str, Any]] = [
    {
        "name": "very_lenient",
        "min": 0,
        "max": 20,
        "semantic_equivalence": {
            "accept_synonyms": True,
            "accept_paraphrases": True,
            "accept_implicit_concepts": True,
            "precision_required": "broad",
        },
        "partial_credit": {"enabled": True, "generosity": "very_generous"},
        "word_count": {"grace_percentage": 20.0, "maximum_penalty_percentage": 5.0},
        "terminology": {
            "precision": "flexible",
            "standard_abbreviations_allowed": True,
            "enforce_mandatory_terms": False,
            "mandatory_missing_penalty_percentage": 0.0,
        },
        "contradictions": {"severity": "low"},
        "diagram": {"layout_tolerance": "high", "label_tolerance": "high"},
    },
    {
        "name": "lenient",
        "min": 21,
        "max": 40,
        "semantic_equivalence": {
            "accept_synonyms": True,
            "accept_paraphrases": True,
            "accept_implicit_concepts": True,
            "precision_required": "broad",
        },
        "partial_credit": {"enabled": True, "generosity": "generous"},
        "word_count": {"grace_percentage": 15.0, "maximum_penalty_percentage": 10.0},
        "terminology": {
            "precision": "flexible",
            "standard_abbreviations_allowed": True,
            "enforce_mandatory_terms": False,
            "mandatory_missing_penalty_percentage": 5.0,
        },
        "contradictions": {"severity": "medium"},
        "diagram": {"layout_tolerance": "moderate", "label_tolerance": "moderate"},
    },
    {
        "name": "standard",
        "min": 41,
        "max": 60,
        "semantic_equivalence": {
            "accept_synonyms": True,
            "accept_paraphrases": True,
            "accept_implicit_concepts": False,
            "precision_required": "normal",
        },
        "partial_credit": {"enabled": True, "generosity": "normal"},
        "word_count": {"grace_percentage": 10.0, "maximum_penalty_percentage": 15.0},
        "terminology": {
            "precision": "standard",
            "standard_abbreviations_allowed": True,
            "enforce_mandatory_terms": False,
            "mandatory_missing_penalty_percentage": 10.0,
        },
        "contradictions": {"severity": "medium"},
        "diagram": {"layout_tolerance": "moderate", "label_tolerance": "moderate"},
    },
    {
        "name": "strict",
        "min": 61,
        "max": 80,
        "semantic_equivalence": {
            "accept_synonyms": True,
            "accept_paraphrases": True,
            "accept_implicit_concepts": False,
            "precision_required": "high",
        },
        "partial_credit": {"enabled": True, "generosity": "conservative"},
        "word_count": {"grace_percentage": 5.0, "maximum_penalty_percentage": 20.0},
        "terminology": {
            "precision": "important",
            "standard_abbreviations_allowed": True,
            "enforce_mandatory_terms": True,
            "mandatory_missing_penalty_percentage": 10.0,
        },
        "contradictions": {"severity": "high"},
        "diagram": {"layout_tolerance": "low", "label_tolerance": "low"},
    },
    {
        "name": "very_strict",
        "min": 81,
        "max": 100,
        "semantic_equivalence": {
            "accept_synonyms": True,
            "accept_paraphrases": False,
            "accept_implicit_concepts": False,
            "precision_required": "very_high",
        },
        "partial_credit": {"enabled": True, "generosity": "minimal"},
        "word_count": {"grace_percentage": 2.0, "maximum_penalty_percentage": 25.0},
        "terminology": {
            "precision": "highly_important",
            "standard_abbreviations_allowed": False,
            "enforce_mandatory_terms": True,
            "mandatory_missing_penalty_percentage": 15.0,
        },
        "contradictions": {"severity": "high"},
        "diagram": {"layout_tolerance": "low", "label_tolerance": "low"},
    },
]


def band_for_score(score: int) -> dict[str, Any]:
    """Return the band definition containing `score` (inclusive bounds)."""
    for band in STRICTNESS_BANDS:
        if band["min"] <= score <= band["max"]:
            return band
    raise ValueError(f"strictness score {score} outside 0-100")
