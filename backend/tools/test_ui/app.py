"""Answer Sheet Perception Pipeline — Developer Test UI (Streamlit)."""

import asyncio
import json
import sys
from pathlib import Path

import streamlit as st

# Ensure workspace root and src/ are in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
if str(WORKSPACE_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from answer_eval.core.hashing import calculate_file_hash
from tests.conftest import MockInferenceProvider
from tools.test_ui.adapter import (
    GranularPipelineResult,
    PipelineExecutionOptions,
    PipelineProgressEvent,
    TestUIAdapter,
)

# Page configuration
st.set_page_config(
    page_title="Answer Sheet Evaluation — Test UI",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_adapter() -> TestUIAdapter:
    """Initialize singleton TestUIAdapter."""
    return TestUIAdapter(workspace_root=WORKSPACE_ROOT)


def main() -> None:
    # ---------------------------------------------------------------------
    # Workspace selector — Perception (M4-11) or Grading & Workflow (M12-18)
    # ---------------------------------------------------------------------
    with st.sidebar:
        workspace = st.radio(
            "Workspace",
            ["🔍 Perception Pipeline (M4–11)", "🎯 Grading & Workflow (M12–18)"],
            key="workspace_selector",
            help="Perception: what did the student write/draw? Grading: how is it evaluated against the rubric?",
        )

    if workspace.startswith("🎯"):
        from tools.test_ui.grading_views import render_grading_workspace

        render_grading_workspace()
        return

    adapter = get_adapter()

    # Session State Initialization
    if "session_id" not in st.session_state:
        sid, sdir = adapter.create_session()
        st.session_state["session_id"] = sid
        st.session_state["session_dir"] = str(sdir)
    if "pipeline_result" not in st.session_state:
        st.session_state["pipeline_result"] = None
    if "uploaded_pdf_path" not in st.session_state:
        st.session_state["uploaded_pdf_path"] = None
    if "uploaded_pdf_meta" not in st.session_state:
        st.session_state["uploaded_pdf_meta"] = None
    if "live_events" not in st.session_state:
        st.session_state["live_events"] = []

    # -----------------------------------------------------------------------
    # Sidebar: Model Selection, Server Health & Options
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.title("⚙️ Perception Pipeline")
        st.caption("Developer Test UI — Modules 4–11")
        st.divider()

        # 1. Model Profile Selector
        st.subheader("Model Profile")

        models = adapter.get_available_models()
        only_installed = st.checkbox("Only show downloaded models on this PC", value=False)

        filtered_models = [m for m in models if m.checkpoint_exists] if only_installed else models

        if not filtered_models and only_installed:
            st.info("No GGUF models downloaded in `models/` directory yet.")
            filtered_models = models

        def format_model_label(mid: str) -> str:
            m = next((item for item in models if item.model_id == mid), None)
            if not m:
                return mid
            badge = "🟢 Installed" if m.checkpoint_exists else "⚪ Template (Not Downloaded)"
            return f"[{badge}] {m.display_name}"

        selected_model_id = st.selectbox(
            "Active Model Profile",
            options=[m.model_id for m in filtered_models],
            format_func=format_model_label,
            index=0,
        )

        selected_model = next((m for m in models if m.model_id == selected_model_id), None)
        if selected_model:
            status_badge = "🟢 Present on PC" if selected_model.checkpoint_exists else "⚪ Not Downloaded on PC"
            st.caption(
                f"**File Status**: {status_badge}\n\n"
                f"**Path**: `{selected_model.checkpoint_path}`\n\n"
                f"**Provider**: `{selected_model.provider}` | **Context**: `{selected_model.context_size}`"
            )

        # Custom GGUF loader
        with st.expander("➕ Use Custom GGUF File from PC", expanded=False):
            custom_gguf_path = st.text_input("GGUF Model File Path", placeholder="e.g. C:/models/my_model.gguf")
            custom_mmproj_path = st.text_input(
                "Vision mmproj Path (Optional)", placeholder="e.g. C:/models/mmproj.gguf"
            )
            custom_name = st.text_input("Display Name", placeholder="My Local Model")

            if st.button("Register Custom Model", use_container_width=True):
                if custom_gguf_path.strip() and Path(custom_gguf_path.strip()).exists():
                    p_name = custom_name.strip() or Path(custom_gguf_path.strip()).name
                    c_id = f"custom_{Path(custom_gguf_path.strip()).stem.lower().replace('-', '_')}"
                    adapter.register_custom_local_model(
                        model_id=c_id,
                        display_name=p_name,
                        gguf_path=custom_gguf_path.strip(),
                        mmproj_path=custom_mmproj_path.strip() if custom_mmproj_path.strip() else None,
                    )
                    st.success(f"Registered `{p_name}`!")
                    st.rerun()
                else:
                    st.error("File path does not exist on disk.")

        st.divider()

        # 2. Server Status & Mock Mode
        st.subheader("Inference Runtime")

        is_ready, msg = asyncio.run(adapter.check_inference_server_status(selected_model_id))

        # Auto-enable mock mode if server is offline on initial visit
        if "mock_mode" not in st.session_state:
            st.session_state["mock_mode"] = not is_ready

        mock_mode = st.toggle(
            "Mock / Test Mode",
            value=st.session_state["mock_mode"],
            help="Enable in-memory MockProvider for rapid UI and layout debugging without running llama-server.",
            key="mock_toggle",
        )
        st.session_state["mock_mode"] = mock_mode

        hw = adapter.get_hardware_status()
        gpu_name = hw.gpu.name if hw.gpu else "CPU-Only"
        vram_info = f"{hw.gpu.vram_free_gb:.1f} / {hw.gpu.vram_total_gb:.1f} GB" if hw.gpu else "N/A"
        ram_info = f"{hw.system_ram_available_gb:.1f} / {hw.system_ram_total_gb:.1f} GB"

        if mock_mode:
            st.success("● Mock Provider Active")
            st.caption("Testing full pipeline stages with deterministic mock perception.")
        else:
            if is_ready:
                st.success(f"● {msg}")
            else:
                st.warning(f"○ {msg}")
                st.caption("Switch to **Mock / Test Mode** above to test offline, or start Ollama.")

        st.caption(f"**GPU**: {gpu_name} | **VRAM Free**: {vram_info}\n\n**RAM Free**: {ram_info}")

        # Guide expander
        with st.expander("📖 Ollama Setup & Verification Guide", expanded=False):
            st.markdown(
                """
                **1. Verify Model**:
                ```powershell
                ollama list
                ```
                **2. Pull Model (if missing)**:
                ```powershell
                ollama pull qwen3-vl:4b
                ```
                **3. Check GPU Usage**:
                ```powershell
                ollama ps
                ```
                **4. Optional Port 8090**:
                ```powershell
                $env:OLLAMA_HOST="127.0.0.1:8090"
                ollama serve
                ```
                """
            )

        st.divider()

        # 3. Processing Options (Advanced Expander)
        with st.expander("🛠️ Advanced Options", expanded=False):
            render_dpi = st.select_slider(
                "PDF Render DPI",
                options=[150, 200, 250, 300, 400],
                value=300,
                help="Higher DPI preserves fine handwriting details.",
            )

            st.write("**Image Preprocessing Stages**")
            deskew = st.checkbox("Deskew (Rotation correction)", value=True)
            border_cleanup = st.checkbox("Border Removal", value=True)
            noise_red = st.checkbox("Noise Reduction (Gaussian)", value=True)
            contrast_clahe = st.checkbox("Contrast Enhancement (CLAHE)", value=True)
            grayscale = st.checkbox("Convert to Grayscale", value=False)

            st.write("**Pipeline Mode**")
            image_source = st.radio(
                "OCR Image Input Source",
                options=["Preprocessed Image", "Original Image"],
                index=0,
                help="Compare OCR accuracy on preprocessed vs original scan.",
            )
            use_orig = image_source == "Original Image"

            ocr_only = st.checkbox(
                "OCR Only Mode",
                value=False,
                help="Skip diagram extraction and reconstruction for faster OCR testing.",
            )

        # 4. Session Cleanup
        if st.button("🗑️ Clear Current Session", use_container_width=True):
            adapter.clear_session(st.session_state["session_dir"])
            sid, sdir = adapter.create_session()
            st.session_state["session_id"] = sid
            st.session_state["session_dir"] = str(sdir)
            st.session_state["pipeline_result"] = None
            st.session_state["uploaded_pdf_path"] = None
            st.session_state["uploaded_pdf_meta"] = None
            st.session_state["live_events"] = []
            st.rerun()

    # -----------------------------------------------------------------------
    # Main Panel: Header & PDF Upload
    # -----------------------------------------------------------------------
    st.header("📝 Answer Sheet Perception Pipeline — Developer Test UI")
    st.caption("Upload a handwritten student answer sheet PDF, execute Modules 4–11, and inspect intermediate stages.")

    if mock_mode:
        st.info(
            "💡 **Mock / Test Mode Active**: All document processing, image quality preprocessing (deskew/CLAHE/borders), horizontal layout segmentation, CER/WER ground truth benchmarking, and multi-page answer reconstruction run end-to-end without requiring GPU llama-server."
        )

    col_up, col_info = st.columns([1.2, 1.0])

    with col_up:
        uploaded_file = st.file_uploader(
            "Upload Student Answer Sheet (.pdf)",
            type=["pdf"],
            help="Upload a scanned answer sheet PDF to test perception modules.",
        )

        session_dir = Path(st.session_state["session_dir"])

        if uploaded_file is not None:
            # Save file to session dir if new
            file_bytes = uploaded_file.getvalue()
            pdf_path = adapter.save_uploaded_pdf(
                file_bytes=file_bytes,
                original_filename=uploaded_file.name,
                session_dir=session_dir,
            )
            st.session_state["uploaded_pdf_path"] = str(pdf_path)

        st.markdown("**OR load a synthetic multi-page student answer sheet:**")
        if st.button("⚡ Load Demo Answer Sheet PDF", use_container_width=True):
            demo_path = adapter.create_demo_answer_sheet_pdf(session_dir=session_dir)
            st.session_state["uploaded_pdf_path"] = str(demo_path)
            st.rerun()

    with col_info:
        if st.session_state["uploaded_pdf_path"]:
            pdf_p = Path(st.session_state["uploaded_pdf_path"])
            file_size_kb = round(pdf_p.stat().st_size / 1024, 1)
            file_hash = calculate_file_hash(pdf_p)

            st.subheader("📄 Active PDF Document")
            st.markdown(
                f"- **Filename**: `{pdf_p.name}`\n"
                f"- **Size**: `{file_size_kb} KB`\n"
                f"- **SHA-256**: `{file_hash[:16]}...`\n"
                f"- **Status**: 🟢 Ready to Run"
            )
        else:
            st.info(
                "Upload a PDF or click **'Load Demo Answer Sheet PDF'** to inspect metadata and run the perception pipeline."
            )

    st.divider()

    # -----------------------------------------------------------------------
    # Pipeline Execution Section
    # -----------------------------------------------------------------------
    col_btn, col_prog = st.columns([1, 3])

    with col_btn:
        can_run = st.session_state["uploaded_pdf_path"] is not None
        run_clicked = st.button(
            "▶ Run Perception Pipeline",
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )

    progress_placeholder = st.empty()
    status_placeholder = st.empty()

    if run_clicked and can_run:
        opts = PipelineExecutionOptions(
            model_id=selected_model_id,
            render_dpi=render_dpi,
            deskew_enabled=deskew,
            border_removal_enabled=border_cleanup,
            noise_reduction_enabled=noise_red,
            contrast_adjustment_enabled=contrast_clahe,
            grayscale_enabled=grayscale,
            use_original_image_for_ocr=use_orig,
            ocr_only_mode=ocr_only,
            mock_mode=mock_mode,
        )

        custom_prov = None
        if mock_mode:
            custom_prov = MockInferenceProvider()

        prog_bar = progress_placeholder.progress(0.0)
        status_box = status_placeholder.info("Initializing perception pipeline...")

        def on_progress(evt: PipelineProgressEvent) -> None:
            prog_bar.progress(evt.progress_pct)
            status_box.info(f"**Stage [{evt.stage.upper()}]**: {evt.message}")

        # Execute async pipeline
        session_dir = Path(st.session_state["session_dir"])
        with st.spinner("Processing document through Modules 4–11..."):
            res = asyncio.run(
                adapter.execute_perception_pipeline(
                    pdf_path=st.session_state["uploaded_pdf_path"],
                    session_dir=session_dir,
                    options=opts,
                    progress_callback=on_progress,
                    custom_inference_provider=custom_prov,
                )
            )
            st.session_state["pipeline_result"] = res
            st.session_state["live_events"] = res.events

        prog_bar.progress(1.0)
        if res.error_message:
            status_box.error(f"Pipeline failed: {res.error_message}")
        else:
            status_box.success(f"Pipeline completed successfully in {res.total_duration_ms:.1f}ms!")

    # -----------------------------------------------------------------------
    # Results & Inspection Tabs
    # -----------------------------------------------------------------------
    res: GranularPipelineResult | None = st.session_state.get("pipeline_result")

    if res is not None:
        st.subheader(f"📊 Perception Results — Submission `{res.submission_id}`")

        tabs = st.tabs(
            [
                "📌 Overview",
                "📄 Pages (Orig vs Prep)",
                "🔲 Segmentation",
                "✍️ Exact OCR",
                "📊 Diagrams",
                "🧩 Reconstruction",
                "📦 Final Canonical JSON",
                "⚡ Runtime Metrics",
                "📜 Pipeline Events",
            ]
        )

        # -------------------------------------------------------------------
        # Tab 1: Overview
        # -------------------------------------------------------------------
        with tabs[0]:
            st.subheader("Submission Summary")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Pages Rendered", len(res.pdf_document.pages) if res.pdf_document else 0)
            c2.metric("Total Regions", sum(len(s.regions) for s in res.segmentation_results))
            c3.metric("OCR Segments", len(res.ocr_results))
            c4.metric("Diagrams", len(res.diagram_results))
            c5.metric("Reconstructed Answers", len(res.canonical_answers))

            st.divider()
            st.subheader("Stage Latencies")
            if res.stage_durations_ms:
                cols = st.columns(len(res.stage_durations_ms))
                for idx, (stage_name, dur_ms) in enumerate(res.stage_durations_ms.items()):
                    cols[idx].metric(stage_name.replace("_", " ").title(), f"{dur_ms:.1f} ms")

            if res.error_message:
                st.error(f"Error Encountered: {res.error_message}")
                with st.expander("🔍 Developer Details"):
                    st.json(res.error_details)

        # -------------------------------------------------------------------
        # Tab 2: Pages (Original vs Preprocessed)
        # -------------------------------------------------------------------
        with tabs[1]:
            st.subheader("Page-by-Page Comparison & Quality Signals")
            st.caption("Verify that preprocessing enhances contrast without degrading handwriting strokes.")

            if res.preprocessed_pages:
                for prep in res.preprocessed_pages:
                    st.markdown(f"#### Page {prep.page_number}")
                    p_col1, p_col2 = st.columns(2)

                    with p_col1:
                        st.caption("ORIGINAL RENDERED PAGE")
                        if Path(prep.original_image_path).exists():
                            st.image(prep.original_image_path, use_container_width=True)

                    with p_col2:
                        st.caption("PREPROCESSED PAGE")
                        if Path(prep.preprocessed_image_path).exists():
                            st.image(prep.preprocessed_image_path, use_container_width=True)

                    # Quality Metrics Badge
                    qm = prep.quality_metrics
                    q_c1, q_c2, q_c3, q_c4, q_c5 = st.columns(5)
                    q_c1.metric("Blur Score", f"{qm.blur_score:.1f}")
                    q_c2.metric("Brightness", f"{qm.brightness_score:.1f}")
                    q_c3.metric("Contrast", f"{qm.contrast_score:.1f}")
                    q_c4.metric("Detected Skew", f"{qm.estimated_skew_degrees:.1f}°")
                    q_c5.metric("Quality Flags", len(qm.quality_flags) or "None")

                    if qm.quality_flags:
                        st.warning(f"Quality Flags: {', '.join(qm.quality_flags)}")

                    st.info(f"Applied Operations: {', '.join(prep.applied_operations) or 'None'}")
                    st.divider()
            else:
                st.info("No pages processed yet.")

        # -------------------------------------------------------------------
        # Tab 3: Segmentation
        # -------------------------------------------------------------------
        with tabs[2]:
            st.subheader("Question Layout Segmentation (Module 6)")
            st.caption("Inspect detected bounding boxes overlaying page images and individual region crops.")

            if res.segmentation_results and res.preprocessed_pages:
                for seg in res.segmentation_results:
                    page_prep = next((p for p in res.preprocessed_pages if p.page_number == seg.page_number), None)
                    st.markdown(f"#### Page {seg.page_number} — {len(seg.regions)} Detected Regions")

                    s_col_img, s_col_regions = st.columns([1.2, 1.0])

                    with s_col_img:
                        if page_prep:
                            annotated_img = adapter.draw_segmentation_boxes_on_page(
                                page_image_path=page_prep.preprocessed_image_path,
                                regions=seg.regions,
                            )
                            st.image(
                                annotated_img,
                                caption=f"Page {seg.page_number} Annotated Bounding Boxes",
                                use_container_width=True,
                            )

                    with s_col_regions:
                        st.markdown("**Detected Region Crops**")
                        for reg in seg.regions:
                            with st.expander(
                                f"{reg.region_id} [{reg.region_type.value}] — Reading Order #{reg.reading_order}",
                                expanded=False,
                            ):
                                st.write(f"- **Type**: `{reg.region_type.value}`")
                                st.write(
                                    f"- **BBox**: `x: [{reg.bbox.x_min:.2f}..{reg.bbox.x_max:.2f}], y: [{reg.bbox.y_min:.2f}..{reg.bbox.y_max:.2f}]`"
                                )
                                st.write(f"- **Continues on next page**: `{reg.continues_on_next_page}`")
                                if reg.crop_image_path and Path(reg.crop_image_path).exists():
                                    st.image(
                                        reg.crop_image_path, caption=f"Crop: {reg.region_id}", use_container_width=True
                                    )

                    st.divider()

        # -------------------------------------------------------------------
        # Tab 4: Exact OCR
        # -------------------------------------------------------------------
        with tabs[3]:
            st.subheader("Exact OCR / Handwriting Transcription (Module 9)")
            st.caption(
                "OCR extracts verbatim text without spelling/grammar corrections. Test transcription accuracy below."
            )

            if res.ocr_results:
                for reg, ocr in res.ocr_results:
                    st.markdown(f"#### Region `{reg.region_id}` (Page {reg.page_number}, #{reg.reading_order})")
                    o_col1, o_col2 = st.columns([1.1, 1.2])

                    with o_col1:
                        st.caption("HANDWRITING CROP")
                        if reg.crop_image_path and Path(reg.crop_image_path).exists():
                            st.image(reg.crop_image_path, use_container_width=True)

                    with o_col2:
                        st.caption("VERBATIM RAW OCR TRANSCRIPTION")
                        st.code(ocr.raw_text, language="text")

                        m1, m2, m3 = st.columns(3)
                        m1.metric("Word Count", ocr.word_count)
                        m2.metric("Model", ocr.provenance.model_id)
                        m3.metric("Quantization", ocr.provenance.quantization or "N/A")

                        if ocr.uncertain_spans:
                            st.warning("⚠️ Uncertain Spans Detected:")
                            for u in ocr.uncertain_spans:
                                st.write(f"- `{u.text}` — *Reason: {u.reason}* ({u.position_hint or ''})")

                    # Developer Tool: Ground Truth & Metric Calculator
                    with st.expander(f"🔬 Developer Evaluation & CER/WER Tool for {reg.region_id}"):
                        gt_input = st.text_area(
                            "Manual Ground Truth Transcription",
                            key=f"gt_{reg.region_id}",
                            placeholder="Type exactly what the student wrote on the answer sheet...",
                        )

                        known_misspells = st.text_input(
                            "Known Misspellings (comma separated)",
                            key=f"misspells_{reg.region_id}",
                            placeholder="e.g. protocall, comunication",
                        )

                        b_c1, b_c2 = st.columns(2)
                        with b_c1:
                            if st.button("📊 Calculate OCR Metrics", key=f"btn_calc_{reg.region_id}"):
                                if gt_input.strip():
                                    misspells_list = [m.strip() for m in known_misspells.split(",") if m.strip()]
                                    metrics_res = adapter.calculate_ocr_metrics_for_region(
                                        predicted_text=ocr.raw_text,
                                        ground_truth_text=gt_input,
                                        known_misspellings=misspells_list,
                                    )
                                    st.write(
                                        f"**CER**: `{metrics_res['cer_percentage']}%` | **WER**: `{metrics_res['wer_percentage']}%` | **Exact Match**: `{metrics_res['exact_match']}`"
                                    )
                                    st.write(
                                        f"**Substitutions**: `{metrics_res['substitutions']}` | **Insertions**: `{metrics_res['insertions']}` | **Deletions**: `{metrics_res['deletions']}`"
                                    )
                                    if metrics_res["unwanted_corrections"]:
                                        st.error(f"Unwanted Auto-Corrections: {metrics_res['unwanted_corrections']}")
                                else:
                                    st.warning("Enter ground truth text first.")

                        with b_c2:
                            if (
                                st.button("💾 Save as Benchmark Fixture", key=f"btn_save_{reg.region_id}")
                                and gt_input.strip()
                                and reg.crop_image_path
                            ):
                                misspells_list = [m.strip() for m in known_misspells.split(",") if m.strip()]
                                t_img, t_gt = adapter.save_as_benchmark_fixture(
                                    crop_image_path=reg.crop_image_path,
                                    ground_truth_text=gt_input,
                                    sample_id=f"fixture_{reg.region_id.lower().replace('-', '_')}",
                                    known_misspellings=misspells_list,
                                )
                                st.success(f"Saved benchmark fixture to `{t_gt.name}`!")

                    st.divider()
            else:
                st.info("No OCR results in this run.")

        # -------------------------------------------------------------------
        # Tab 5: Diagrams
        # -------------------------------------------------------------------
        with tabs[4]:
            st.subheader("Diagram Extraction (Module 10)")
            st.caption("Visual observation of drawn shapes, labels, and connections (strictly without grading).")

            if res.diagram_results:
                for reg, diag in res.diagram_results:
                    st.markdown(f"#### Diagram `{reg.region_id}` (Page {reg.page_number})")
                    d_col1, d_col2 = st.columns([1.1, 1.2])

                    with d_col1:
                        if reg.crop_image_path and Path(reg.crop_image_path).exists():
                            st.image(
                                reg.crop_image_path, caption=f"Diagram Crop: {reg.region_id}", use_container_width=True
                            )

                    with d_col2:
                        st.write(f"- **Diagram Type**: `{diag.diagram_type_guess}`")
                        st.write(f"- **Visual Legibility**: `{diag.visual_quality.legibility}`")
                        st.write(f"- **Label Clarity**: `{diag.visual_quality.label_clarity}`")

                        st.markdown("**Observed Labels**:")
                        for lbl in diag.labels:
                            st.write(f"  - `{lbl.text}` (Uncertain: {lbl.uncertain})")

                        st.markdown("**Observed Components**:")
                        for comp in diag.components:
                            st.write(f"  - `{comp.type}`: *{comp.label or comp.description}*")

                        if diag.relationships:
                            st.markdown("**Relationships**:")
                            for rel in diag.relationships:
                                st.write(f"  - `{rel.from_component}` → `{rel.to_component}` ({rel.relationship_type})")

                    with st.expander("🔍 Raw Diagram Extraction JSON"):
                        st.json(diag.model_dump())

                    st.divider()
            else:
                st.info("No diagram regions identified or analyzed.")

        # -------------------------------------------------------------------
        # Tab 6: Reconstruction
        # -------------------------------------------------------------------
        with tabs[5]:
            st.subheader("Answer Reconstruction (Module 11)")
            st.caption("Reassembles multi-page continuous answers while preserving exact immutable raw OCR.")

            if res.canonical_answers:
                for ans in res.canonical_answers:
                    st.markdown(f"### Question `{ans.question_id}` (Pages {ans.source_pages})")
                    st.write(
                        f"**Word Count**: `{ans.word_count}` | **Constituent Segments**: `{len(ans.segments)}` | **Diagrams Attached**: `{len(ans.diagrams)}`"
                    )

                    st.markdown("**Reconstructed Immutable Raw Text**:")
                    st.code(ans.raw_text, language="text")

                    if ans.segments:
                        with st.expander(f"Constituent Segments for {ans.question_id}"):
                            for seg in ans.segments:
                                st.write(f"- **Page {seg.page_number} ({seg.region_id})**: {seg.raw_text[:80]}...")

                    st.divider()
            else:
                st.info("No reconstructed answers available.")

        # -------------------------------------------------------------------
        # Tab 7: Final JSON
        # -------------------------------------------------------------------
        with tabs[6]:
            st.subheader("📦 Final Canonical Structured JSON")
            st.caption("Standard Pydantic model serialization of CanonicalStructuredAnswer.")

            if res.canonical_answers:
                canonical_export = [ans.model_dump() for ans in res.canonical_answers]
                json_str = json.dumps(canonical_export, indent=2)

                # Download Button
                st.download_button(
                    label="💾 Download Canonical Structured JSON",
                    data=json_str,
                    file_name=f"submission_{res.submission_id}_canonical.json",
                    mime="application/json",
                    type="primary",
                )

                json_view_mode = st.radio("JSON Format View", options=["Pretty JSON", "Raw JSON"], horizontal=True)

                if json_view_mode == "Pretty JSON":
                    st.json(canonical_export)
                else:
                    st.code(json_str, language="json")

                # Additional debug downloads
                st.divider()
                st.write("**Additional Debug Exports**")
                dbg_col1, dbg_col2, dbg_col3 = st.columns(3)

                if res.ocr_results:
                    ocr_export = [o.model_dump() for _, o in res.ocr_results]
                    dbg_col1.download_button(
                        "Download OCR Results JSON",
                        json.dumps(ocr_export, indent=2),
                        f"sub_{res.submission_id}_ocr.json",
                        "application/json",
                    )

                if res.diagram_results:
                    diag_export = [d.model_dump() for _, d in res.diagram_results]
                    dbg_col2.download_button(
                        "Download Diagram Results JSON",
                        json.dumps(diag_export, indent=2),
                        f"sub_{res.submission_id}_diagrams.json",
                        "application/json",
                    )

                if res.segmentation_results:
                    seg_export = [s.model_dump() for s in res.segmentation_results]
                    dbg_col3.download_button(
                        "Download Segmentation JSON",
                        json.dumps(seg_export, indent=2),
                        f"sub_{res.submission_id}_segmentation.json",
                        "application/json",
                    )

        # -------------------------------------------------------------------
        # Tab 8: Runtime Metrics
        # -------------------------------------------------------------------
        with tabs[7]:
            st.subheader("Runtime & Hardware Utilization")
            r_c1, r_c2 = st.columns(2)

            with r_c1:
                st.markdown("**Host Hardware**")
                st.write(f"- **CPU**: `{hw.cpu.model}` ({hw.cpu.physical_cores}C/{hw.cpu.logical_cores}T)")
                st.write(
                    f"- **RAM Total**: `{hw.system_ram_total_gb} GB` (Available: `{hw.system_ram_available_gb} GB`)"
                )
                st.write(f"- **GPU**: `{gpu_name}` (VRAM: `{hw.gpu.vram_total_gb if hw.gpu else 0.0} GB`)")
                st.write(f"- **OS**: `{hw.os_info}` | **Python**: `{hw.python_version}`")

            with r_c2:
                st.markdown("**Active Pipeline Profile**")
                st.write(f"- **Model Profile**: `{selected_model_id}`")
                st.write(f"- **Quantization**: `{selected_model.quantization if selected_model else 'N/A'}`")
                st.write(f"- **Provider**: `{selected_model.provider if selected_model else 'N/A'}`")
                st.write(f"- **Total Duration**: `{res.total_duration_ms:.1f} ms`")

        # -------------------------------------------------------------------
        # Tab 9: Pipeline Events
        # -------------------------------------------------------------------
        with tabs[8]:
            st.subheader("Timestamped Pipeline Event Stream")
            for evt in res.events:
                st.text(evt)


if __name__ == "__main__":
    main()
