"""Benchmark runner: orchestrates evaluations across test sets and generates reports."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from answer_eval.agents.ocr.agent import OCRAgent
from answer_eval.benchmark.metrics import (
    calculate_character_error_rate,
    calculate_exact_match,
    calculate_word_error_rate,
    detect_unwanted_corrections,
)
from answer_eval.benchmark.reporter import ModelBenchmarkSummary
from answer_eval.core.logging import get_logger
from answer_eval.models.profiles import ModelProfile
from answer_eval.processing.segmentation.schemas import BoundingBox, QuestionRegion

logger = get_logger("benchmark.runner")


@dataclass
class BenchmarkSample:
    """A test sample with an image crop and ground truth text."""

    sample_id: str
    image_path: str
    ground_truth_text: str
    known_misspellings: list[str] | None = None
    expected_diagram_labels: list[str] | None = None


class BenchmarkRunner:
    """Runs perception benchmarks across models and collects comparative metrics."""

    def __init__(
        self,
        benchmarks_dir: Path | str | None = None,
    ) -> None:
        cand = Path(benchmarks_dir or "benchmarks")
        if not cand.exists() and (Path("..") / cand).exists():
            cand = Path("..") / cand
        self.benchmarks_dir = cand
        self.test_images_dir = self.benchmarks_dir / "test_images"
        self.ground_truth_dir = self.benchmarks_dir / "ground_truth"
        self.results_dir = self.benchmarks_dir / "results"

    def load_samples(self) -> list[BenchmarkSample]:
        """Load benchmark samples from ground_truth JSON files."""
        samples: list[BenchmarkSample] = []
        if not self.ground_truth_dir.exists():
            return samples

        for gt_file in sorted(self.ground_truth_dir.glob("*.json")):
            try:
                with open(gt_file, encoding="utf-8") as f:
                    data = json.load(f)
                img_rel = data.get("image_file", f"{gt_file.stem}.png")
                img_path = str(self.test_images_dir / img_rel)
                samples.append(
                    BenchmarkSample(
                        sample_id=gt_file.stem,
                        image_path=img_path,
                        ground_truth_text=data.get("ground_truth_text", ""),
                        known_misspellings=data.get("known_misspellings"),
                        expected_diagram_labels=data.get("expected_diagram_labels"),
                    )
                )
            except Exception as e:
                logger.warning("Failed to load ground truth sample", file=gt_file.name, error=str(e))

        return samples

    async def evaluate_model_ocr(
        self,
        ocr_agent: OCRAgent,
        samples: list[BenchmarkSample],
        model_profile: ModelProfile,
    ) -> ModelBenchmarkSummary:
        """Run OCR evaluation on samples using an initialized OCRAgent."""
        if not samples:
            return ModelBenchmarkSummary(
                model_id=model_profile.model_id,
                display_name=model_profile.display_name,
                quantization=model_profile.quantization,
            )

        cers: list[float] = []
        wers: list[float] = []
        exact_matches: list[bool] = []
        ins_rates: list[float] = []
        del_rates: list[float] = []
        sub_rates: list[float] = []
        unwanted_rates: list[float] = []
        latencies: list[float] = []
        json_success_count = 0

        for sample in samples:
            # Create synthetic region for OCRAgent
            region = QuestionRegion(
                region_id=sample.sample_id,
                page_number=1,
                submission_id="BENCHMARK",
                bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0),
                crop_image_path=sample.image_path,
                crop_image_hash="bench_hash",
            )

            try:
                start_t = time.perf_counter()
                ocr_res = await ocr_agent.extract_text(region)
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                json_success_count += 1
                latencies.append(elapsed_ms)

                predicted = ocr_res.raw_text
                gt = sample.ground_truth_text

                # Calculate metrics
                cer, cer_ops = calculate_character_error_rate(predicted, gt)
                wer, wer_ops = calculate_word_error_rate(predicted, gt)
                exact = calculate_exact_match(predicted, gt)
                unwanted = detect_unwanted_corrections(predicted, gt, sample.known_misspellings)

                cers.append(cer)
                wers.append(wer)
                exact_matches.append(exact)
                ins_rates.append(cer_ops.insertion_rate)
                del_rates.append(cer_ops.deletion_rate)
                sub_rates.append(cer_ops.substitution_rate)
                unwanted_rates.append(unwanted.unwanted_correction_rate)

            except Exception as e:
                logger.warning("Benchmark sample extraction failed", sample_id=sample.sample_id, error=str(e))

        mem_snap = ocr_agent.provider.get_memory_usage()

        sample_count = len(samples)
        return ModelBenchmarkSummary(
            model_id=model_profile.model_id,
            display_name=model_profile.display_name,
            quantization=model_profile.quantization,
            sample_count=sample_count,
            mean_cer=round(sum(cers) / max(1, len(cers)), 4),
            mean_wer=round(sum(wers) / max(1, len(wers)), 4),
            mean_exact_match_pct=round((sum(1 for m in exact_matches if m) / max(1, len(exact_matches))) * 100.0, 1),
            mean_insertion_rate=round(sum(ins_rates) / max(1, len(ins_rates)), 4),
            mean_deletion_rate=round(sum(del_rates) / max(1, len(del_rates)), 4),
            mean_substitution_rate=round(sum(sub_rates) / max(1, len(sub_rates)), 4),
            mean_unwanted_correction_rate=round(sum(unwanted_rates) / max(1, len(unwanted_rates)), 4),
            mean_inference_ms=round(sum(latencies) / max(1, len(latencies)), 2),
            peak_vram_gb=mem_snap.vram_used_gb,
            peak_ram_gb=mem_snap.ram_used_gb,
            json_validity_pct=round((json_success_count / max(1, sample_count)) * 100.0, 1),
        )
