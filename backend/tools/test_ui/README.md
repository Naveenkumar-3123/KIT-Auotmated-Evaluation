# Answer Sheet Perception Pipeline — Developer Test UI

A local developer testing interface for manually inspecting every stage of the **Modules 4–11 Perception Pipeline** on real handwritten student answer sheet PDFs.

---

## 🎯 Purpose

This is a **developer and debugging tool** to verify:
1. **Module 4**: PDF validation and high-resolution rendering.
2. **Module 5**: Conservative image preprocessing (deskew, CLAHE contrast, scanner border removal) and image quality signals.
3. **Module 6**: Document layout segmentation and question boundary detection.
4. **Module 9**: Exact verbatim OCR transcription (strictly zero spelling/grammar correction).
5. **Module 10**: Diagram observation (shapes, labels, connections without academic grading).
6. **Module 11**: Multi-page continuous answer reconstruction and provenance tracking.
7. **Canonical JSON**: Downloadable structured Pydantic serialization.
8. **Benchmarking**: Interactive CER/WER metric calculation and instant export of golden test fixtures.

> [!NOTE]
> This is **NOT** a production student/teacher dashboard. It contains no authentication, databases, or grading logic, and can be safely deleted or modified without affecting the perception pipeline.

---

## 🚀 Quick Start

### 1. Launch the Test UI

Run from the repository root:

```bash
streamlit run tools/test_ui/app.py
```

The UI will automatically open in your default browser at `http://localhost:8501`.

---

## 🧭 Workflow Walkthrough

```
1. Select Model Profile
   ├── Qwen3-VL 4B Q8 (Development)
   ├── Qwen3-VL 4B Q4 (Fast Dev)
   └── Qwen3-VL 30B (Large Local)
        │
2. Upload Answer Sheet PDF
   └── Displays file size, page count, and SHA-256 hash
        │
3. Configure Processing Options (Optional)
   ├── Render DPI (150, 200, 250, 300, 400)
   ├── Toggle Preprocessing (Deskew, CLAHE, Border cleanup)
   └── Select OCR Image Source (Preprocessed vs Original Scan)
        │
4. Click "Run Perception Pipeline"
        │
5. Inspect Intermediate Stages via Tabs
   ├── [Pages]: Original vs Preprocessed side-by-side + quality signals
   ├── [Segmentation]: Visual bounding boxes overlay & region crops
   ├── [Exact OCR]: Handwriting crops beside raw OCR + Ground Truth CER/WER tool
   ├── [Diagrams]: Observed components, labels, and relationships
   ├── [Reconstruction]: Grouped multi-page answers in reading order
   └── [Final JSON]: Pretty JSON preview & 1-click download
```

---

## 🔬 Developer Ground Truth & Benchmark Tool

In the **Exact OCR** tab:
1. View the handwriting crop alongside the extracted verbatim text.
2. Expand the **Developer Evaluation Tool**.
3. Type the true text into **Manual Ground Truth Transcription**.
4. Click **Calculate OCR Metrics** to inspect:
   - Character Error Rate (CER)
   - Word Error Rate (WER)
   - Substitutions, Insertions, Deletions
   - Unwanted spelling corrections (e.g. model "fixed" student's misspelling)
5. Click **Save as Benchmark Fixture** to immediately store the crop image and ground truth JSON inside `benchmarks/` for automated regression testing.

---

## ⚡ Execution Modes

| Mode | Description |
| :--- | :--- |
| **Standard Mode** | Connects to standalone `llama-server` on `http://127.0.0.1:8090` running Qwen3-VL GGUF models. |
| **Mock / Test Mode** | Toggled in the sidebar. Uses an in-memory mock inference provider for rapid UI and layout debugging without starting a local GPU server. |
| **OCR Only Mode** | Enabled in Advanced Options. Skips diagram extraction and multi-page reconstruction for fast OCR iteration. |

---

## 🔒 Security & Safe Temporary Storage

* **Localhost Binding**: Binds exclusively to `127.0.0.1`.
* **Isolated Temporary Storage**: Uploaded files and rendered crops are saved to `temp/test_ui/{session_id}/` using generated internal IDs to prevent path traversal.
* **Session Cleanup**: Click **Clear Current Session** in the sidebar to delete all temporary image files and reset state.
