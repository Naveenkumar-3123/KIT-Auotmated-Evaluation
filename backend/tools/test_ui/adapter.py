"""Test UI Adapter: clean bridge between Streamlit UI and Modules 4-11 perception pipeline."""

import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from answer_eval.agents.diagram.agent import DiagramAgent
from answer_eval.agents.diagram.schemas import DiagramResult
from answer_eval.agents.ocr.agent import OCRAgent
from answer_eval.agents.ocr.schemas import OCRResult
from answer_eval.agents.reconstruction.schemas import CanonicalStructuredAnswer
from answer_eval.agents.reconstruction.service import ReconstructionService
from answer_eval.benchmark.metrics import (
    calculate_character_error_rate,
    calculate_exact_match,
    calculate_word_error_rate,
    detect_unwanted_corrections,
)
from answer_eval.core.config import load_settings
from answer_eval.core.errors import AnswerEvalError, PDFValidationError
from answer_eval.core.hashing import calculate_bytes_hash
from answer_eval.core.logging import get_logger
from answer_eval.hardware.detector import detect_hardware
from answer_eval.hardware.profiles import HardwareProfile
from answer_eval.inference.factory import create_inference_provider
from answer_eval.inference.ollama_provider import OllamaProvider
from answer_eval.inference.provider import InferenceProvider
from answer_eval.models.profiles import ModelProfile, ProviderType
from answer_eval.models.registry import get_model_registry
from answer_eval.processing.image.preprocessing import ImagePreprocessor
from answer_eval.processing.image.schemas import PreprocessedPage, PreprocessingConfig
from answer_eval.processing.pdf.processor import PDFProcessor
from answer_eval.processing.pdf.schemas import PDFDocument
from answer_eval.processing.segmentation.schemas import (
    PageSegmentationResult,
    QuestionRegion,
    RegionType,
)
from answer_eval.processing.segmentation.segmenter import QuestionSegmenter
from answer_eval.runtime.planner import RuntimePlanner

logger = get_logger("tools.test_ui.adapter")


@dataclass
class ModelProfileUIInfo:
    """UI-friendly display model for profile cards and selector."""

    model_id: str
    display_name: str
    family: str
    size_class: str
    provider: str
    quantization: str | None
    context_size: int
    runtime_profile: str
    supports_vision: bool
    supports_thinking: bool
    checkpoint_path: str
    checkpoint_exists: bool
    mmproj_path: str | None
    mmproj_exists: bool
    notes: str | None


@dataclass
class PipelineExecutionOptions:
    """User-configured execution parameters from Streamlit interface."""

    model_id: str = "qwen_vl_4b_q8"
    render_dpi: int = 300
    deskew_enabled: bool = True
    border_removal_enabled: bool = True
    noise_reduction_enabled: bool = True
    contrast_adjustment_enabled: bool = True
    grayscale_enabled: bool = False
    use_original_image_for_ocr: bool = True  # True = use original RGB image for OCR crops, False = preprocessed
    ocr_only_mode: bool = False
    mock_mode: bool = False  # True = use in-memory MockProvider for rapid UI testing


@dataclass
class PipelineProgressEvent:
    """Progress event sent to Streamlit UI callback."""

    stage: str
    step_index: int
    total_steps: int
    progress_pct: float
    message: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class GranularPipelineResult:
    """Complete collection of all intermediate artifacts across Modules 4-11."""

    submission_id: str
    pdf_path: str
    pdf_document: PDFDocument | None = None
    preprocessed_pages: list[PreprocessedPage] = field(default_factory=list)
    segmentation_results: list[PageSegmentationResult] = field(default_factory=list)
    ocr_results: list[tuple[QuestionRegion, OCRResult]] = field(default_factory=list)
    diagram_results: list[tuple[QuestionRegion, DiagramResult]] = field(default_factory=list)
    canonical_answers: list[CanonicalStructuredAnswer] = field(default_factory=list)
    total_duration_ms: float = 0.0
    stage_durations_ms: dict[str, float] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    error_message: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)


class TestUIAdapter:
    """Orchestrates perception pipeline execution and granular inspection for Developer UI."""

    __test__ = False  # Prevent pytest from treating this as a test class

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        temp_dir: Path | str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd())
        self.temp_base_dir = Path(temp_dir or self.workspace_root / "temp" / "test_ui")
        self.temp_base_dir.mkdir(parents=True, exist_ok=True)

        config_file = self.workspace_root / "config" / "models.yaml"
        if not config_file.exists():
            config_file = Path(os.getcwd()) / "config" / "models.yaml"

        settings_file = self.workspace_root / "config" / "settings.yaml"
        if not settings_file.exists():
            settings_file = Path(os.getcwd()) / "config" / "settings.yaml"

        self.registry = get_model_registry(config_path=config_file)
        self.settings = load_settings(config_path=settings_file)

    # -----------------------------------------------------------------------
    def scan_local_gguf_files(self, search_dirs: list[Path | str] | None = None) -> list[dict[str, Any]]:
        """Scan workspace models/ and optional custom directories for local GGUF files."""
        dirs_to_search: list[Path] = [self.workspace_root / "models"]
        if search_dirs:
            for d in search_dirs:
                p = Path(d)
                if p.exists() and p.is_dir() and p not in dirs_to_search:
                    dirs_to_search.append(p)

        found_files: list[dict[str, Any]] = []
        for sdir in dirs_to_search:
            if not sdir.exists():
                continue
            for f in sdir.glob("*.gguf"):
                if f.is_file():
                    found_files.append(
                        {
                            "name": f.name,
                            "path": str(f.resolve()),
                            "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                            "directory": str(sdir),
                        }
                    )
        return found_files

    def register_custom_local_model(
        self,
        model_id: str,
        display_name: str,
        gguf_path: str | Path,
        mmproj_path: str | Path | None = None,
        context_size: int = 8192,
    ) -> ModelProfileUIInfo:
        """Dynamically register a custom local GGUF model file on this PC."""
        from answer_eval.models.profiles import ProviderType

        ckpt = Path(gguf_path)
        mmproj = Path(mmproj_path) if mmproj_path else None

        profile = ModelProfile(
            model_id=model_id,
            display_name=display_name,
            provider_type=ProviderType.LLAMA_SERVER,
            family="custom_local",
            size_class="local",
            checkpoint_path=str(ckpt),
            mmproj_path=str(mmproj) if mmproj else None,
            context_size=context_size,
            supports_vision=mmproj is not None or "vl" in ckpt.name.lower(),
            notes="Custom user-specified local GGUF model",
        )
        self.registry._profiles[model_id] = profile

        return ModelProfileUIInfo(
            model_id=profile.model_id,
            display_name=profile.display_name,
            family=profile.family,
            size_class=profile.size_class,
            provider=profile.provider_type.value,
            quantization="Custom",
            context_size=profile.context_size,
            runtime_profile="custom",
            supports_vision=profile.supports_vision,
            supports_thinking=False,
            checkpoint_path=str(ckpt),
            checkpoint_exists=ckpt.exists(),
            mmproj_path=str(mmproj) if mmproj else None,
            mmproj_exists=mmproj.exists() if mmproj else False,
            notes=profile.notes,
        )

    def get_available_models(self) -> list[ModelProfileUIInfo]:
        """Fetch all registered model profiles and verify local file presence."""
        # Auto-discover unmapped GGUF files in models/
        local_ggufs = self.scan_local_gguf_files()
        registered_ckpts = {
            Path(p.checkpoint_path).name for p in self.registry.list_profiles(enabled_only=False) if p.checkpoint_path
        }

        for gguf in local_ggufs:
            if gguf["name"] not in registered_ckpts:
                custom_id = f"local_{Path(gguf['name']).stem.lower().replace('-', '_')}"
                if custom_id not in self.registry._profiles:
                    self.register_custom_local_model(
                        model_id=custom_id,
                        display_name=f"Local: {gguf['name']} ({gguf['size_mb']} MB)",
                        gguf_path=gguf["path"],
                    )

        profiles = self.registry.list_profiles(enabled_only=False)
        ui_models: list[ModelProfileUIInfo] = []

        for p in profiles:
            ckpt_path, mmproj_path = p.resolve_paths(self.workspace_root)
            ckpt_exists = (
                (ckpt_path.exists() and ckpt_path.is_file()) if ckpt_path else (p.provider_type == ProviderType.OLLAMA)
            )
            mmproj_exists = (mmproj_path.exists() and mmproj_path.is_file()) if mmproj_path else False

            ui_models.append(
                ModelProfileUIInfo(
                    model_id=p.model_id,
                    display_name=p.display_name,
                    family=p.family,
                    size_class=p.size_class,
                    provider=p.provider_type.value,
                    quantization=p.quantization,
                    context_size=p.context_size,
                    runtime_profile=p.runtime_profile_hint,
                    supports_vision=p.supports_vision,
                    supports_thinking=p.supports_thinking,
                    checkpoint_path=str(ckpt_path) if ckpt_path else f"Ollama ({p.model_id})",
                    checkpoint_exists=ckpt_exists,
                    mmproj_path=str(mmproj_path) if mmproj_path else None,
                    mmproj_exists=mmproj_exists,
                    notes=p.notes,
                )
            )

        return ui_models

    def get_hardware_status(self) -> HardwareProfile:
        """Inspect and return current host hardware specifications."""
        return detect_hardware()

    async def check_inference_server_status(
        self,
        model_id: str,
        custom_provider: InferenceProvider | None = None,
    ) -> tuple[bool, str]:
        """Check if active inference server is reachable and healthy."""
        if custom_provider is not None:
            is_healthy = await custom_provider.health_check()
            return (
                is_healthy,
                "Ready (Custom/Mock Provider)" if is_healthy else "Unreachable",
            )

        try:
            profile = self.registry.get_profile(model_id)
            provider = create_inference_provider(profile)

            if isinstance(provider, OllamaProvider):
                detail = await provider.check_detailed_health()
                if detail["available"]:
                    return True, f"Ready (Ollama - {detail['model']})"
                else:
                    msg = detail.get("help_message") or detail.get("error") or "Ollama server not ready"
                    return False, f"Not Ready — {msg}"

            is_healthy = await provider.health_check()
            if is_healthy:
                return True, f"Ready ({profile.provider_type.value})"
            else:
                return (
                    False,
                    f"Not Ready — {profile.provider_type.value} is not responding",
                )
        except Exception as e:
            return False, f"Error: {e}"

    # -----------------------------------------------------------------------
    # Session & Temporary File Management
    # -----------------------------------------------------------------------

    def create_session(self) -> tuple[str, Path]:
        """Create isolated session directory for an upload."""
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        session_dir = self.temp_base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_id, session_dir

    def save_uploaded_pdf(
        self,
        file_bytes: bytes,
        original_filename: str,
        session_dir: Path,
    ) -> Path:
        """Save uploaded PDF bytes safely with a sanitized internal name."""
        # Sanitize extension
        ext = Path(original_filename).suffix.lower()
        if ext != ".pdf":
            raise PDFValidationError(f"Invalid file extension '{ext}'. Only .pdf is allowed.")

        file_hash = calculate_bytes_hash(file_bytes)
        safe_filename = f"upload_{file_hash[:12]}.pdf"
        target_path = session_dir / safe_filename

        with open(target_path, "wb") as f:
            f.write(file_bytes)

        return target_path

    def create_demo_answer_sheet_pdf(self, session_dir: Path) -> Path:
        """Generate a realistic 2-page synthetic student answer sheet PDF for instant UI testing."""
        import pymupdf as fitz

        target_path = session_dir / "demo_student_answer_sheet.pdf"
        doc = fitz.open()

        # Page 1
        page1 = doc.new_page(width=595, height=842)  # A4
        page1.insert_text(fitz.Point(50, 60), "STUDENT ANSWER SHEET — MID-TERM EXAM", fontsize=14)
        page1.insert_text(
            fitz.Point(50, 100), "Q1: Explain the Transport Layer protocols and TCP 3-way handshake.", fontsize=11
        )
        page1.insert_text(
            fitz.Point(50, 140),
            "Answer: The transport layer provides end-to-end communication services for applications.\n"
            "The two primary protocols are TCP (Transmission Control Protocol) and UDP.\n"
            "TCP is connection-oriented and reliable, using sequence numbers and acknowledgements.",
            fontsize=10,
        )

        # Draw diagram box & labels for 3-way handshake
        page1.draw_rect(fitz.Rect(50, 230, 540, 420), color=(0.2, 0.2, 0.2), width=1.5)
        page1.insert_text(fitz.Point(70, 260), "Client", fontsize=11)
        page1.insert_text(fitz.Point(470, 260), "Server", fontsize=11)
        page1.draw_line(fitz.Point(120, 280), fitz.Point(450, 310), color=(0.1, 0.1, 0.1), width=1.2)
        page1.insert_text(fitz.Point(260, 285), "1. SYN", fontsize=10)
        page1.draw_line(fitz.Point(450, 330), fitz.Point(120, 360), color=(0.1, 0.1, 0.1), width=1.2)
        page1.insert_text(fitz.Point(240, 335), "2. SYN-ACK", fontsize=10)
        page1.draw_line(fitz.Point(120, 380), fitz.Point(450, 400), color=(0.1, 0.1, 0.1), width=1.2)
        page1.insert_text(fitz.Point(260, 380), "3. ACK", fontsize=10)

        # Bottom section of page 1
        page1.insert_text(
            fitz.Point(50, 460),
            "The handshake ensures both sender and receiver are synchronized before payload transfer begins.",
            fontsize=10,
        )

        # Page 2 (Continuation)
        page2 = doc.new_page(width=595, height=842)
        page2.insert_text(fitz.Point(50, 60), "STUDENT ANSWER SHEET — PAGE 2", fontsize=14)
        page2.insert_text(fitz.Point(50, 100), "Q1 (Continued):", fontsize=11)
        page2.insert_text(
            fitz.Point(50, 130),
            "In contrast, UDP is connectionless and does not guarantee message delivery or ordering.\n"
            "UDP is preferred in real-time multimedia streaming, DNS lookups, and gaming where low latency\n"
            "is critical and dropped packets can be tolerated.",
            fontsize=10,
        )

        page2.insert_text(
            fitz.Point(50, 220), "Q2: Distinguish between Flow Control and Congestion Control.", fontsize=11
        )
        page2.insert_text(
            fitz.Point(50, 250),
            "Answer: Flow control prevents the sender from overwhelming the receiver's buffer using\n"
            "sliding window mechanisms. Congestion control prevents network saturation by regulating the\n"
            "injection rate based on packet loss and latency signals.",
            fontsize=10,
        )

        doc.save(str(target_path))
        doc.close()
        return target_path

    def clear_session(self, session_dir: Path | str) -> None:
        """Remove temporary session directory and all derived images/crops."""
        p = Path(session_dir)
        if p.exists() and p.is_dir() and "temp" in str(p):
            shutil.rmtree(p, ignore_errors=True)
            logger.info("Session directory cleared", path=str(p))

    # -----------------------------------------------------------------------
    # Visual Annotation Helpers
    # -----------------------------------------------------------------------

    def draw_segmentation_boxes_on_page(
        self,
        page_image_path: str | Path,
        regions: list[QuestionRegion],
    ) -> Image.Image:
        """
        Draw color-coded bounding boxes and region labels over a page image.
        Colors:
        - answer_text: Green / Blue
        - diagram: Purple / Orange
        - mixed: Amber / Yellow
        - unknown: Gray
        """
        p = Path(page_image_path)
        if not p.exists():
            # Return blank image if not found
            return Image.new("RGB", (600, 800), color=(240, 240, 240))

        pil_img = Image.open(p).convert("RGB")
        draw = ImageDraw.Draw(pil_img)
        w, h = pil_img.size

        # Color palette (RGB)
        color_map = {
            RegionType.ANSWER_TEXT: (34, 139, 34),  # Forest Green
            RegionType.DIAGRAM: (147, 51, 234),  # Purple
            RegionType.MIXED: (217, 119, 6),  # Amber
            RegionType.UNKNOWN: (107, 114, 128),  # Gray
        }

        for reg in regions:
            left, top, right, bottom = reg.bbox.to_pixel_coords(w, h)
            color = color_map.get(reg.region_type, (59, 130, 246))

            # Draw outer rectangle with 3px border
            for offset in range(3):
                draw.rectangle(
                    [
                        left - offset,
                        top - offset,
                        right + offset,
                        bottom + offset,
                    ],
                    outline=color,
                )

            # Draw label banner
            label_text = f"{reg.question_id or reg.region_id} [{reg.region_type.value}] #{reg.reading_order}"
            banner_height = 24
            draw.rectangle(
                [left, top, left + (len(label_text) * 9) + 12, top + banner_height],
                fill=color,
            )
            draw.text((left + 6, top + 4), label_text, fill=(255, 255, 255))

        return pil_img

    # -----------------------------------------------------------------------
    # Ground Truth Metric Calculation & Fixture Export
    # -----------------------------------------------------------------------

    def calculate_ocr_metrics_for_region(
        self,
        predicted_text: str,
        ground_truth_text: str,
        known_misspellings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Calculate CER, WER, edit operations, and unwanted spelling corrections."""
        cer, cer_ops = calculate_character_error_rate(hypothesis=predicted_text, reference=ground_truth_text)
        wer, wer_ops = calculate_word_error_rate(hypothesis=predicted_text, reference=ground_truth_text)
        exact = calculate_exact_match(hypothesis=predicted_text, reference=ground_truth_text)
        unwanted = detect_unwanted_corrections(
            hypothesis=predicted_text,
            reference=ground_truth_text,
            known_misspellings=known_misspellings,
        )

        return {
            "cer": cer,
            "cer_percentage": round(cer * 100, 2),
            "wer": wer,
            "wer_percentage": round(wer * 100, 2),
            "exact_match": exact,
            "substitutions": cer_ops.substitutions,
            "insertions": cer_ops.insertions,
            "deletions": cer_ops.deletions,
            "unwanted_corrections": unwanted.detected_corrections,
            "unwanted_correction_count": unwanted.unwanted_correction_count,
            "unwanted_correction_rate": unwanted.unwanted_correction_rate,
        }

    def save_as_benchmark_fixture(
        self,
        crop_image_path: str | Path,
        ground_truth_text: str,
        sample_id: str | None = None,
        known_misspellings: list[str] | None = None,
        notes: str | None = None,
    ) -> tuple[Path, Path]:
        """Save a region crop + ground truth JSON to benchmarks directory."""
        source_crop = Path(crop_image_path)
        if not source_crop.exists():
            raise AnswerEvalError(f"Source crop image not found: {source_crop}")

        bench_dir = self.workspace_root / "benchmarks"
        img_dir = bench_dir / "test_images"
        gt_dir = bench_dir / "ground_truth"
        img_dir.mkdir(parents=True, exist_ok=True)
        gt_dir.mkdir(parents=True, exist_ok=True)

        sid = sample_id or f"sample_{uuid.uuid4().hex[:6]}"
        target_img = img_dir / f"{sid}.png"
        target_gt = gt_dir / f"{sid}.json"

        # Copy crop image
        shutil.copy2(source_crop, target_img)

        # Write GT JSON
        gt_data = {
            "sample_id": sid,
            "image_file": target_img.name,
            "ground_truth_text": ground_truth_text,
            "known_misspellings": known_misspellings or [],
            "notes": notes or "Captured via Developer Test UI",
        }
        with open(target_gt, "w", encoding="utf-8") as f:
            json.dump(gt_data, f, indent=2)

        return target_img, target_gt

    # -----------------------------------------------------------------------
    # Pipeline Execution with Live Progress Callback
    # -----------------------------------------------------------------------

    async def execute_perception_pipeline(
        self,
        pdf_path: str | Path,
        session_dir: Path,
        options: PipelineExecutionOptions,
        progress_callback: (Callable[[PipelineProgressEvent], None] | None) = None,
        custom_inference_provider: InferenceProvider | None = None,
    ) -> GranularPipelineResult:
        """
        Execute full perception pipeline (Modules 4-11) step-by-step with real-time event reporting.
        """
        sub_id = f"SUB-{uuid.uuid4().hex[:8].upper()}"
        start_time = time.perf_counter()
        events: list[str] = []
        stage_times: dict[str, float] = {}

        def emit_progress(stage: str, step: int, total: int, msg: str) -> None:
            pct = round((step / float(total)), 2)
            event_text = f"[{time.strftime('%H:%M:%S')}] {stage.upper()}: {msg}"
            events.append(event_text)
            if progress_callback:
                progress_callback(
                    PipelineProgressEvent(
                        stage=stage,
                        step_index=step,
                        total_steps=total,
                        progress_pct=pct,
                        message=msg,
                    )
                )

        p = Path(pdf_path)
        result = GranularPipelineResult(
            submission_id=sub_id,
            pdf_path=str(p),
            events=events,
        )

        TOTAL_STEPS = 6

        try:
            # ---------------------------------------------------------------
            # Step 1: PDF Validation & Rendering (Module 4)
            # ---------------------------------------------------------------
            emit_progress("PDF", 1, TOTAL_STEPS, f"Validating PDF: {p.name}")
            t0 = time.perf_counter()

            pdf_out_dir = session_dir / "rendered_pages"
            pdf_processor = PDFProcessor(
                default_dpi=options.render_dpi,
                output_dir=pdf_out_dir,
            )

            validation = pdf_processor.validate_pdf(p)
            if not validation.is_valid:
                raise PDFValidationError(
                    validation.error_message or "PDF validation failed",
                    details=validation.details,
                )

            emit_progress(
                "PDF",
                1,
                TOTAL_STEPS,
                f"Rendering {validation.page_count} pages at {options.render_dpi} DPI...",
            )
            pdf_doc = pdf_processor.process_pdf(p, submission_id=sub_id, dpi=options.render_dpi)
            result.pdf_document = pdf_doc
            stage_times["pdf_processing"] = round((time.perf_counter() - t0) * 1000, 2)
            emit_progress(
                "PDF",
                1,
                TOTAL_STEPS,
                f"Rendered {len(pdf_doc.pages)} pages successfully.",
            )

            # ---------------------------------------------------------------
            # Step 2: Image Preprocessing (Module 5)
            # ---------------------------------------------------------------
            emit_progress(
                "Preprocessing",
                2,
                TOTAL_STEPS,
                "Applying conservative preprocessing pipeline...",
            )
            t0 = time.perf_counter()

            prep_out_dir = session_dir / "preprocessed_pages"
            prep_cfg = PreprocessingConfig(
                deskew_enabled=options.deskew_enabled,
                border_removal_enabled=options.border_removal_enabled,
                noise_reduction_enabled=options.noise_reduction_enabled,
                contrast_adjustment_enabled=options.contrast_adjustment_enabled,
                grayscale_enabled=options.grayscale_enabled,
            )
            preprocessor = ImagePreprocessor(
                config=prep_cfg,
                output_dir=prep_out_dir,
            )

            preprocessed_pages: list[PreprocessedPage] = []
            for idx, page_img in enumerate(pdf_doc.pages, start=1):
                emit_progress(
                    "Preprocessing",
                    2,
                    TOTAL_STEPS,
                    f"Preprocessing page {idx}/{len(pdf_doc.pages)}...",
                )
                prep_page = preprocessor.preprocess_page(page_img)
                preprocessed_pages.append(prep_page)

            result.preprocessed_pages = preprocessed_pages
            stage_times["preprocessing"] = round((time.perf_counter() - t0) * 1000, 2)
            emit_progress(
                "Preprocessing",
                2,
                TOTAL_STEPS,
                f"Preprocessed {len(preprocessed_pages)} pages.",
            )

            # ---------------------------------------------------------------
            # Step 3: Question Segmentation (Module 6)
            # ---------------------------------------------------------------
            emit_progress(
                "Segmentation",
                3,
                TOTAL_STEPS,
                "Analyzing document layout and splitting question regions...",
            )
            t0 = time.perf_counter()

            crops_out_dir = session_dir / "region_crops"
            segmenter = QuestionSegmenter(
                crops_output_dir=crops_out_dir,
            )

            segmentation_results: list[PageSegmentationResult] = []
            all_regions: list[QuestionRegion] = []

            for idx, prep_page in enumerate(preprocessed_pages, start=1):
                emit_progress(
                    "Segmentation",
                    3,
                    TOTAL_STEPS,
                    f"Segmenting page {idx}/{len(preprocessed_pages)}...",
                )
                seg_res = segmenter.segment_page(
                    prep_page,
                    use_original_image=options.use_original_image_for_ocr,
                )
                segmentation_results.append(seg_res)
                all_regions.extend(seg_res.regions)

            result.segmentation_results = segmentation_results
            stage_times["segmentation"] = round((time.perf_counter() - t0) * 1000, 2)
            emit_progress(
                "Segmentation",
                3,
                TOTAL_STEPS,
                f"Identified {len(all_regions)} regions across {len(segmentation_results)} pages.",
            )

            # ---------------------------------------------------------------
            # Initialize Inference Provider (Module 7 & 8)
            # ---------------------------------------------------------------
            if custom_inference_provider is not None:
                provider = custom_inference_provider
            else:
                profile = self.registry.get_profile(options.model_id)
                provider = create_inference_provider(profile)
                planner = RuntimePlanner(workspace_root=self.workspace_root)
                hw = detect_hardware()
                runtime_cfg = planner.plan_candidate(hw, profile, self.settings)
                await provider.initialize(profile, runtime_cfg, hw)

            ocr_agent = OCRAgent(inference_provider=provider)
            diagram_agent = DiagramAgent(inference_provider=provider)

            # ---------------------------------------------------------------
            # Step 4: OCR Perception Agent (Module 9)
            # ---------------------------------------------------------------
            emit_progress("OCR", 4, TOTAL_STEPS, "Extracting verbatim text from regions...")
            t0 = time.perf_counter()

            ocr_results: list[tuple[QuestionRegion, OCRResult]] = []
            text_regions = [
                r
                for r in all_regions
                if r.region_type
                in (
                    RegionType.ANSWER_TEXT,
                    RegionType.MIXED,
                    RegionType.UNKNOWN,
                )
            ]

            # Emit classification summary for every region
            for reg in all_regions:
                emit_progress(
                    "Classification",
                    3,
                    TOTAL_STEPS,
                    f"CLASSIFICATION: {reg.region_id} type={reg.region_type.value} "
                    f"confidence={reg.classification_confidence:.2f}",
                )

            for idx, region in enumerate(text_regions, start=1):
                emit_progress(
                    "OCR",
                    4,
                    TOTAL_STEPS,
                    f"Extracting OCR text {idx}/{len(text_regions)} ({region.region_id})...",
                )
                # If user selected 'Original Image' for OCR, adjust crop path if possible
                if options.use_original_image_for_ocr and region.crop_image_path:
                    # We can use the region crop as created, or re-crop from original
                    pass

                ocr_res = await ocr_agent.extract_text(region)
                ocr_results.append((region, ocr_res))

            result.ocr_results = ocr_results
            stage_times["ocr_extraction"] = round((time.perf_counter() - t0) * 1000, 2)
            emit_progress("OCR", 4, TOTAL_STEPS, f"Extracted OCR from {len(ocr_results)} regions.")

            # ---------------------------------------------------------------
            # Step 5: Diagram Perception Agent (Module 10)
            # ---------------------------------------------------------------
            diagram_results: list[tuple[QuestionRegion, DiagramResult]] = []
            if not options.ocr_only_mode:
                emit_progress(
                    "Diagram",
                    5,
                    TOTAL_STEPS,
                    "Analyzing visual diagrams and structure...",
                )
                t0 = time.perf_counter()

                diagram_regions = [r for r in all_regions if r.region_type in (RegionType.DIAGRAM, RegionType.MIXED)]

                for idx, region in enumerate(diagram_regions, start=1):
                    emit_progress(
                        "Diagram",
                        5,
                        TOTAL_STEPS,
                        f"Analyzing diagram {idx}/{len(diagram_regions)} ({region.region_id}, "
                        f"confidence={region.classification_confidence:.2f})...",
                    )
                    try:
                        diag_res = await diagram_agent.extract_diagram(region)
                        diagram_results.append((region, diag_res))

                        if not diag_res.diagram_present:
                            # Model confirmed this is not a diagram — treat as OCR result
                            emit_progress(
                                "Diagram",
                                5,
                                TOTAL_STEPS,
                                f"DIAGRAM: {region.region_id} — model reports NOT a diagram. "
                                f"Rerouted to OCR fallback. Pipeline continuing.",
                            )
                            # If fallback OCR text was captured, promote it to the ocr_results list
                            if diag_res.fallback_ocr_text:
                                fallback_ocr = OCRResult(
                                    raw_text=diag_res.fallback_ocr_text,
                                    lines=[
                                        line.strip()
                                        for line in diag_res.fallback_ocr_text.splitlines()
                                        if line.strip()
                                    ],
                                    uncertain_spans=[],
                                    flags=["rerouted_from_diagram_agent"],
                                    word_count=len(diag_res.fallback_ocr_text.split()),
                                    provenance=diag_res.provenance,
                                    model_metadata=diag_res.model_metadata,
                                )
                                ocr_results.append((region, fallback_ocr))
                        else:
                            emit_progress(
                                "Diagram",
                                5,
                                TOTAL_STEPS,
                                f"DIAGRAM: {region.region_id} — valid diagram extracted "
                                f"({len(diag_res.components)} components, {len(diag_res.relationships)} relationships).",
                            )

                    except Exception as diag_err:
                        # Per-region fallback: log the failure, attempt plain OCR, then continue
                        emit_progress(
                            "Diagram",
                            5,
                            TOTAL_STEPS,
                            f"DIAGRAM: {region.region_id} — extraction failed: {type(diag_err).__name__}. "
                            f"Falling back to OCR. Pipeline continuing.",
                        )
                        logger.warning(
                            "Diagram extraction failed for region — applying OCR fallback",
                            region_id=region.region_id,
                            error=str(diag_err)[:300],
                        )
                        try:
                            fallback_ocr_res = await ocr_agent.extract_text(region)
                            ocr_results.append((region, fallback_ocr_res))
                            emit_progress(
                                "Diagram",
                                5,
                                TOTAL_STEPS,
                                f"DIAGRAM: {region.region_id} — OCR fallback succeeded "
                                f"({fallback_ocr_res.word_count} words).",
                            )
                        except Exception as ocr_err:
                            logger.warning(
                                "OCR fallback also failed for diagram region — region skipped",
                                region_id=region.region_id,
                                error=str(ocr_err)[:200],
                            )
                            emit_progress(
                                "Diagram",
                                5,
                                TOTAL_STEPS,
                                f"DIAGRAM: {region.region_id} — OCR fallback also failed. Region skipped.",
                            )

                result.diagram_results = diagram_results
                stage_times["diagram_extraction"] = round((time.perf_counter() - t0) * 1000, 2)
                # Update ocr_results with any fallbacks added during diagram stage
                result.ocr_results = ocr_results
                emit_progress(
                    "Diagram",
                    5,
                    TOTAL_STEPS,
                    f"Analyzed {len(diagram_regions)} diagram-classified regions "
                    f"({len(diagram_results)} diagram results, any failures fell back to OCR).",
                )
            else:
                emit_progress(
                    "Diagram",
                    5,
                    TOTAL_STEPS,
                    "Skipped (OCR Only mode enabled).",
                )

            # ---------------------------------------------------------------
            # Step 6: Answer Reconstruction (Module 11)
            # ---------------------------------------------------------------
            canonical_answers: list[CanonicalStructuredAnswer] = []
            if not options.ocr_only_mode:
                emit_progress(
                    "Reconstruction",
                    6,
                    TOTAL_STEPS,
                    "Reconstructing continuous answers and provenance...",
                )
                t0 = time.perf_counter()

                recon_service = ReconstructionService()

                # Group by question ID
                q_groups: dict[str, list[tuple[QuestionRegion, OCRResult]]] = {}
                d_groups: dict[str, list[tuple[QuestionRegion, DiagramResult]]] = {}

                for r, o in ocr_results:
                    qid = r.question_id or "Q1"
                    q_groups.setdefault(qid, []).append((r, o))

                for r, d in diagram_results:
                    qid = r.question_id or "Q1"
                    d_groups.setdefault(qid, []).append((r, d))

                all_qids = sorted(list(set(list(q_groups.keys()) + list(d_groups.keys()))))

                for qid in all_qids:
                    ans = recon_service.reconstruct_answer(
                        submission_id=sub_id,
                        question_id=qid,
                        ocr_results=q_groups.get(qid, []),
                        diagram_results=d_groups.get(qid, []),
                    )
                    canonical_answers.append(ans)

                result.canonical_answers = canonical_answers
                stage_times["reconstruction"] = round((time.perf_counter() - t0) * 1000, 2)
                emit_progress(
                    "Reconstruction",
                    6,
                    TOTAL_STEPS,
                    f"Reconstructed {len(canonical_answers)} canonical answers.",
                )
            else:
                emit_progress(
                    "Reconstruction",
                    6,
                    TOTAL_STEPS,
                    "Skipped (OCR Only mode enabled).",
                )

            result.total_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            result.stage_durations_ms = stage_times
            emit_progress(
                "Complete",
                TOTAL_STEPS,
                TOTAL_STEPS,
                f"Perception pipeline complete in {result.total_duration_ms:.1f}ms.",
            )

            return result

        except Exception as e:
            logger.error("Pipeline execution failed", error=str(e))
            result.error_message = str(e)
            result.error_details = getattr(e, "details", {})
            emit_progress(
                "Error",
                TOTAL_STEPS,
                TOTAL_STEPS,
                f"Failed: {type(e).__name__}: {e}",
            )
            return result
