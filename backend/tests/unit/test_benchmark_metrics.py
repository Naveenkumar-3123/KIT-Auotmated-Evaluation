"""Unit tests for Benchmark metrics and reporting."""

from answer_eval.benchmark.metrics import (
    calculate_character_error_rate,
    calculate_set_overlap_metrics,
    calculate_word_error_rate,
    detect_unwanted_corrections,
)
from answer_eval.benchmark.reporter import BenchmarkReporter, ModelBenchmarkSummary


def test_character_error_rate_calculation() -> None:
    ref = "The protocol is used for communication"
    hyp = "The protocall is use for comunication"

    cer, ops = calculate_character_error_rate(hyp, ref)
    assert 0.0 < cer < 0.2
    assert ops.substitutions >= 1
    assert ops.deletions >= 1
    assert ops.insertion_rate >= 0.0

    # Exact match
    cer_zero, ops_zero = calculate_character_error_rate("exact", "exact")
    assert cer_zero == 0.0
    assert ops_zero.total_errors == 0


def test_word_error_rate_calculation() -> None:
    ref = "The protocol is used for communication"
    hyp = "The protocall is use for comunication"

    wer, ops = calculate_word_error_rate(hyp, ref)
    assert 0.0 < wer <= 1.0
    assert ops.substitutions == 3  # protocol->protocall, used->use, communication->comunication
    assert ops.insertions == 0
    assert ops.deletions == 0


def test_unwanted_spelling_correction_detection() -> None:
    # Student wrote misspelling "protocall", model auto-corrected to "protocol"
    student_ref = "The protocall is use for comunication"
    model_hyp = "The protocol is used for communication"

    res = detect_unwanted_corrections(
        hypothesis=model_hyp,
        reference=student_ref,
        known_misspellings=["protocall", "comunication"],
    )
    assert res.unwanted_correction_count >= 2
    assert res.unwanted_correction_rate > 0.0
    misspellings = [orig for orig, corr in res.detected_corrections]
    assert "protocall" in misspellings


def test_diagram_set_overlap_metrics() -> None:
    extracted = ["Transport", "Network", "Physical"]
    ground_truth = ["Transport", "Network", "Data Link", "Physical"]

    score = calculate_set_overlap_metrics(extracted, ground_truth)
    assert score.precision == 1.0
    assert score.recall == 0.75
    assert score.f1_score > 0.8


def test_benchmark_reporter_markdown_generation() -> None:
    s1 = ModelBenchmarkSummary(
        model_id="qwen_vl_4b_q8",
        display_name="Qwen3-VL 4B Q8",
        quantization="Q8_0",
        sample_count=10,
        mean_cer=0.035,
        mean_wer=0.082,
        mean_exact_match_pct=80.0,
        mean_insertion_rate=0.01,
        mean_deletion_rate=0.01,
        mean_substitution_rate=0.015,
        mean_unwanted_correction_rate=0.005,
        mean_tokens_per_sec=42.5,
        mean_inference_ms=180.0,
        peak_vram_gb=5.4,
        peak_ram_gb=3.8,
        json_validity_pct=100.0,
        diagram_label_f1=0.92,
    )

    s2 = ModelBenchmarkSummary(
        model_id="qwen_vl_4b_q4",
        display_name="Qwen3-VL 4B Q4",
        quantization="Q4_K_M",
        sample_count=10,
        mean_cer=0.048,
        mean_wer=0.105,
        mean_exact_match_pct=70.0,
        mean_insertion_rate=0.015,
        mean_deletion_rate=0.015,
        mean_substitution_rate=0.018,
        mean_unwanted_correction_rate=0.012,
        mean_tokens_per_sec=55.0,
        mean_inference_ms=135.0,
        peak_vram_gb=3.6,
        peak_ram_gb=3.5,
        json_validity_pct=100.0,
        diagram_label_f1=0.88,
    )

    md_table = BenchmarkReporter.generate_markdown_comparison_table([s1, s2])
    assert "| Metric |" in md_table
    assert "Qwen3-VL 4B Q8" in md_table
    assert "Qwen3-VL 4B Q4" in md_table
    assert "OCR CER" in md_table
    assert "OCR WER" in md_table
    assert "Unwanted Correction Rate" in md_table
