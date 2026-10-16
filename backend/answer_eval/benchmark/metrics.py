"""Comprehensive benchmarking metrics: CER, WER, Edit Operations, Unwanted Corrections, and Diagram precision."""

from dataclasses import dataclass

import rapidfuzz.distance.Levenshtein as lev


@dataclass
class EditOperations:
    """Detailed breakdown of Levenshtein edit distance operations."""

    substitutions: int
    insertions: int
    deletions: int
    reference_length: int

    @property
    def total_errors(self) -> int:
        return self.substitutions + self.insertions + self.deletions

    @property
    def error_rate(self) -> float:
        if self.reference_length == 0:
            return 0.0 if self.total_errors == 0 else 1.0
        return round(self.total_errors / float(self.reference_length), 4)

    @property
    def substitution_rate(self) -> float:
        if self.reference_length == 0:
            return 0.0
        return round(self.substitutions / float(self.reference_length), 4)

    @property
    def insertion_rate(self) -> float:
        if self.reference_length == 0:
            return 0.0
        return round(self.insertions / float(self.reference_length), 4)

    @property
    def deletion_rate(self) -> float:
        if self.reference_length == 0:
            return 0.0
        return round(self.deletions / float(self.reference_length), 4)


def calculate_character_error_rate(hypothesis: str, reference: str) -> tuple[float, EditOperations]:
    """
    Calculate Character Error Rate (CER) and detailed character edit breakdown.
    CER = (Substitutions + Insertions + Deletions) / Reference_Length
    """
    ops = lev.editops(reference, hypothesis)
    subs = sum(1 for op in ops if op.tag == "replace")
    ins = sum(1 for op in ops if op.tag == "insert")
    dels = sum(1 for op in ops if op.tag == "delete")
    ref_len = len(reference)

    edit_ops = EditOperations(
        substitutions=subs,
        insertions=ins,
        deletions=dels,
        reference_length=ref_len,
    )
    return edit_ops.error_rate, edit_ops


def calculate_word_error_rate(hypothesis: str, reference: str) -> tuple[float, EditOperations]:
    """
    Calculate Word Error Rate (WER) using word-level Levenshtein alignment.
    WER = (Substitutions + Insertions + Deletions) / Reference_Word_Count
    """
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()

    ops = lev.editops(ref_words, hyp_words)
    subs = sum(1 for op in ops if op.tag == "replace")
    ins = sum(1 for op in ops if op.tag == "insert")
    dels = sum(1 for op in ops if op.tag == "delete")
    ref_len = len(ref_words)

    edit_ops = EditOperations(
        substitutions=subs,
        insertions=ins,
        deletions=dels,
        reference_length=ref_len,
    )
    return edit_ops.error_rate, edit_ops


def calculate_exact_match(hypothesis: str, reference: str) -> bool:
    """Check if hypothesis exactly matches reference string."""
    return hypothesis.strip() == reference.strip()


@dataclass
class UnwantedCorrectionResult:
    """Detection of unintended spelling/grammar corrections."""

    detected_corrections: list[tuple[str, str]]  # (ground_truth_misspelling, model_corrected_word)
    unwanted_correction_count: int
    unwanted_correction_rate: float


def detect_unwanted_corrections(
    hypothesis: str,
    reference: str,
    known_misspellings: list[str] | None = None,
) -> UnwantedCorrectionResult:
    """
    Detect if model unhelpfully auto-corrected a student's intentional or unintentional spelling error.
    Example: reference="The protocall is use for comunication", hypothesis="The protocol is used for communication"
    """
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()

    detected: list[tuple[str, str]] = []

    # Map words using editops
    ops = lev.editops(ref_words, hyp_words)
    for op in ops:
        if op.tag == "replace":
            ref_w = ref_words[op.src_pos]
            hyp_w = hyp_words[op.dest_pos]
            # If reference word is in known misspellings or differs slightly from hyp word
            if (
                known_misspellings
                and ref_w.lower() in [m.lower() for m in known_misspellings]
                or (len(ref_w) > 3 and len(hyp_w) > 3 and lev.distance(ref_w.lower(), hyp_w.lower()) in (1, 2))
            ):
                detected.append((ref_w, hyp_w))

    rate = round(len(detected) / max(1, len(ref_words)), 4)
    return UnwantedCorrectionResult(
        detected_corrections=detected,
        unwanted_correction_count=len(detected),
        unwanted_correction_rate=rate,
    )


@dataclass
class DiagramMetricScore:
    """Precision, recall, and F1 score for diagram labels or components."""

    precision: float
    recall: float
    f1_score: float
    true_positives: int
    false_positives: int
    false_negatives: int


def calculate_set_overlap_metrics(
    extracted_items: list[str],
    ground_truth_items: list[str],
    case_sensitive: bool = False,
) -> DiagramMetricScore:
    """Calculate precision, recall, and F1 score between extracted set and ground truth set."""
    ext = [x.strip() if case_sensitive else x.strip().lower() for x in extracted_items if x.strip()]
    gt = [x.strip() if case_sensitive else x.strip().lower() for x in ground_truth_items if x.strip()]

    ext_set = set(ext)
    gt_set = set(gt)

    tp = len(ext_set.intersection(gt_set))
    fp = len(ext_set - gt_set)
    fn = len(gt_set - ext_set)

    precision = round(tp / float(tp + fp), 4) if (tp + fp) > 0 else 1.0
    recall = round(tp / float(tp + fn), 4) if (tp + fn) > 0 else 1.0
    f1 = round(2 * (precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    return DiagramMetricScore(
        precision=precision,
        recall=recall,
        f1_score=f1,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
    )
