"""Benchmark report generator producing Markdown comparison tables and JSON exports."""

import json
from pathlib import Path

from pydantic import BaseModel


class ModelBenchmarkSummary(BaseModel):
    """Aggregate benchmark evaluation for a single model profile."""

    model_id: str
    display_name: str
    quantization: str | None = None
    sample_count: int = 0
    mean_cer: float = 0.0
    mean_wer: float = 0.0
    mean_exact_match_pct: float = 0.0
    mean_insertion_rate: float = 0.0
    mean_deletion_rate: float = 0.0
    mean_substitution_rate: float = 0.0
    mean_unwanted_correction_rate: float = 0.0
    mean_tokens_per_sec: float | None = None
    mean_inference_ms: float = 0.0
    peak_vram_gb: float = 0.0
    peak_ram_gb: float = 0.0
    json_validity_pct: float = 100.0
    diagram_label_f1: float | None = None
    diagram_component_f1: float | None = None


class BenchmarkReporter:
    """Generates comparative Markdown tables and JSON metrics files."""

    @staticmethod
    def generate_markdown_comparison_table(
        summaries: list[ModelBenchmarkSummary],
    ) -> str:
        """Generate side-by-side Markdown comparison table."""
        if not summaries:
            return "No benchmark results to display."

        headers = [
            "Metric",
            *[f"**{s.display_name}** ({s.quantization or 'native'})" for s in summaries],
        ]

        rows: list[list[str]] = [
            ["**Model ID**", *[s.model_id for s in summaries]],
            ["**Quantization**", *[s.quantization or "native" for s in summaries]],
            ["**Samples Evaluated**", *[str(s.sample_count) for s in summaries]],
            ["---", *["---" for _ in summaries]],
            [
                "**OCR CER** (lower is better)",
                *[f"{s.mean_cer:.4f} ({s.mean_cer * 100:.1f}%)" for s in summaries],
            ],
            [
                "**OCR WER** (lower is better)",
                *[f"{s.mean_wer:.4f} ({s.mean_wer * 100:.1f}%)" for s in summaries],
            ],
            ["**Exact Match Rate**", *[f"{s.mean_exact_match_pct:.1f}%" for s in summaries]],
            ["**Substitution Rate**", *[f"{s.mean_substitution_rate:.4f}" for s in summaries]],
            ["**Insertion Rate**", *[f"{s.mean_insertion_rate:.4f}" for s in summaries]],
            ["**Deletion Rate**", *[f"{s.mean_deletion_rate:.4f}" for s in summaries]],
            [
                "**Unwanted Correction Rate**",
                *[f"{s.mean_unwanted_correction_rate:.4f}" for s in summaries],
            ],
            ["---", *["---" for _ in summaries]],
            ["**JSON Validity Rate**", *[f"{s.json_validity_pct:.1f}%" for s in summaries]],
            [
                "**Diagram Label F1**",
                *[f"{s.diagram_label_f1:.3f}" if s.diagram_label_f1 is not None else "N/A" for s in summaries],
            ],
            ["---", *["---" for _ in summaries]],
            ["**Avg Latency (ms)**", *[f"{s.mean_inference_ms:.1f} ms" for s in summaries]],
            [
                "**Tokens / sec**",
                *[f"{s.mean_tokens_per_sec:.1f} tok/s" if s.mean_tokens_per_sec else "TBD" for s in summaries],
            ],
            ["**Peak VRAM (GB)**", *[f"{s.peak_vram_gb:.2f} GB" for s in summaries]],
            ["**Peak RAM (GB)**", *[f"{s.peak_ram_gb:.2f} GB" for s in summaries]],
        ]

        table_lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join([":---"] + [":---:" for _ in summaries]) + " |",
        ]

        for row in rows:
            if row[0] == "---":
                table_lines.append("| " + " | ".join(["---" for _ in range(len(headers))]) + " |")
            else:
                table_lines.append("| " + " | ".join(row) + " |")

        return "\n".join(table_lines)

    @staticmethod
    def save_json_report(
        summaries: list[ModelBenchmarkSummary],
        output_file: Path | str,
    ) -> None:
        """Export benchmark summary list to JSON."""
        p = Path(output_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = [s.model_dump() for s in summaries]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
