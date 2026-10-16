"""Unit tests for BenchmarkRunner with sample test fixtures."""

from pathlib import Path

import pytest

from answer_eval.agents.ocr.agent import OCRAgent
from answer_eval.benchmark.reporter import BenchmarkReporter
from answer_eval.benchmark.runner import BenchmarkRunner
from answer_eval.models.profiles import ModelProfile, ProviderType
from tests.conftest import MockInferenceProvider


@pytest.mark.asyncio
async def test_benchmark_runner_flow(mock_provider: MockInferenceProvider) -> None:
    runner = BenchmarkRunner(benchmarks_dir=Path("benchmarks"))
    samples = runner.load_samples()
    assert len(samples) >= 2

    m_profile = ModelProfile(
        model_id="qwen_vl_4b_q8",
        display_name="Qwen3-VL 4B Q8",
        family="qwen3_vl",
        size_class="4b",
        provider_type=ProviderType.LLAMA_SERVER,
        quantization="Q8_0",
        checkpoint_path="models/test.gguf",
    )

    ocr_agent = OCRAgent(inference_provider=mock_provider)
    summary = await runner.evaluate_model_ocr(
        ocr_agent=ocr_agent,
        samples=samples,
        model_profile=m_profile,
    )

    assert summary.sample_count == len(samples)
    assert summary.mean_cer >= 0.0
    assert summary.mean_wer >= 0.0
    assert summary.json_validity_pct == 100.0

    # Generate Markdown table
    md_table = BenchmarkReporter.generate_markdown_comparison_table([summary])
    assert "| Metric |" in md_table
    assert "Qwen3-VL 4B Q8" in md_table
