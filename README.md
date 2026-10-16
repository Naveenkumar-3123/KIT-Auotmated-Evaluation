# EvalAI / KIT Automated Paper Evaluation System

**Automated, teacher-verified grading of handwritten answer sheets.**

EvalAI turns scanned handwritten answer sheets (PDFs) into verified, auditable marks. It reads a student's handwriting with multimodal AI (Google Gemini Cloud API by default, or optional local vision models), maps each answer region to the correct question, grades it against a teacher's answer key, and proposes marks — **every mark is reviewed by the teacher before it becomes final.**

> **"The AI proposes, deterministic code enforces policy, and the teacher decides. Nothing is ever silently graded."**

---

## Table of Contents

- [Why](#why)
- [Tech Stack](#tech-stack)
- [The Pipeline](#the-pipeline)
- [Question Mapping](#question-mapping)
- [Repository Layout](#repository-layout)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Running the Tests](#running-the-tests)

---

## Why

Grading handwritten answer sheets by hand is slow, inconsistent, and hard to audit. EvalAI is built around a simple premise: **AI grading is only trustworthy when it is verifiable.** The system keeps a complete evidence trail — every page render, every region crop, every OCR transcription, and two independent grading passes that must not silently disagree.

The project runs out-of-the-box using **Google Gemini Flash / Flash-Lite API**, requiring **zero local model downloads or dedicated GPU hardware**. An embedded SQLite fallback ensures the system works immediately even if a local PostgreSQL instance is offline.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **AI Runtime** | **Google Gemini Multimodal API** (Cloud Default) | Low-latency handwriting perception, OCR transcription, mathematical step verification, and diagram grading. |
| **Alternative AI** | **Qwen-VL / Ollama / Local Transformers** | Optional local GPU inference support for fully air-gapped environments. |
| **Orchestration** | **LangGraph** | 12-stage pipeline as a stateful graph with durable checkpoints — a crash never loses progress. |
| **Backend API** | **FastAPI** (Python ≥ 3.11) | Uploads, configuration, background job worker, evaluation results, and teacher review endpoints (`backend/`). |
| **Durable Storage** | **PostgreSQL** + **SQLite Embedded Fallback** | Users, profiles, jobs, results, review decisions, and sandboxed content-addressed file storage. |
| **Frontend** | **React 19 + Vite + TypeScript + Tailwind CSS** | Interactive teacher workspace: Configure → Evaluation → Results (`frontend/`). |
| **Auth & Email** | **Native JWT + SMTP App Password** | Secure teacher registration, email verification, and JWT session management. |

---

## The Pipeline

The pipeline is a LangGraph state machine with 12 distinct stages. Each stage is idempotent and its output is checkpointed:

```
 1. Validate        PDF exists, rubrics well-formed — invalid input never reaches the AI.
 2. Render PDF      Each page rendered to a high-resolution image.
 3. Preprocess      Deskew, denoise, contrast (CLAHE), resolution-normalization.
 4. Segment         Split each page into answer regions (whitespace/ink analysis).
 5. Map questions   Attach each region to a question number via margin & semantic mapping.
 6. OCR             Verbatim handwriting transcription preserving original text.
 7. Diagrams        Detect and extract student diagrams where present.
 8. Reconstruct     Merge a question's regions/pages into one canonical answer.
 9. Rules engine    Deterministic penalties: word count, missing diagrams, mandatory terms.
10. Evaluation      AI grades semantic correctness vs the answer key criteria.
11. Verification    A second, blind AI pass re-grades independently; disagreements raise review flags.
12. Risk & review   Risk engine decides: auto-approve, or flag for instructor review.
```

After the pipeline completes, marks land in the **teacher review panel** → teacher approves or overrides → results are finalized.

---

## Question Mapping

Students' handwritten scans feature mixed answer sequences, margin annotations, and multi-page calculations. Mapping uses a robust cascade:

1. **Margin Scanning & Ruled Line Detection**: High-precision boundary alignment detecting printed question markers (e.g. `Q1`, `11(a)`) while filtering ruled answer sheet line numbering (`1..30`).
2. **Header Anchor Resolution**: Identifies section titles (e.g., `Part A`, `Part B`, `Question 12`) across complex multi-page spreads.
3. **Semantic Fallback**: Multimodal classification maps unlabelled regions based on topic context and mathematical formulas.

---

## Repository Layout

```
├── backend/
│   ├── answer_eval/
│   │   ├── api/routers/     FastAPI endpoints (assessments, answer_keys, reviews, auth)
│   │   ├── core/            Workflow graphs and execution state
│   │   ├── db/              Database pool, migrations, and SQLite fallback
│   │   ├── grading/         Rules, evaluation, blind verification, and risk engine
│   │   ├── inference/       Gemini multimodal API provider & local model adapters
│   │   ├── jobs/            Background worker loop and queue management
│   │   ├── processing/      PDF rendering, CLAHE preprocessing, segmentation, mapping
│   │   └── prompts/         Versioned prompt templates for OCR, diagram, and grading
│   ├── config/              settings.yaml, models.yaml, preprocessing.yaml
│   └── tests/               Unit and integration test suites
│
├── frontend/
│   ├── client/              React 19 + Vite workspace (Configure → Evaluation → Results)
│   │   ├── src/pages/       Configure.tsx, Evaluation.tsx, Results.tsx, Auth.tsx
│   │   └── src/components/  UI components and interactive viewers
│   ├── package.json         Frontend package configuration
│   └── vite.config.ts       Vite dev server and API proxy configuration
│
├── run_backend.py           FastAPI server launcher with automatic SQLite fallback
├── run_project.py           Interactive launcher for running backend & frontend together
├── pyproject.toml           Backend Python package configuration
└── .env.example             Template environment variables
```

---

## Getting Started

### Prerequisites

- **Python ≥ 3.11**
- **Node.js ≥ 20** (`npm` or `pnpm`)
- **Google Gemini API Key** (Get one from [Google AI Studio](https://aistudio.google.com/))

### 1. Backend Setup

```bash
# Clone the repository
git clone https://github.com/Naveenkumar-3123/KIT-Auotmated-Evaluation.git
cd KIT-Auotmated-Evaluation

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -e "./backend[api,workflow,dev]"

# Configure environment variables
cp .env.example .env
# Edit .env and paste your GEMINI_API_KEY:
# GEMINI_API_KEY=your_key_here

# Start the Backend Server (runs on port 8400)
python run_backend.py
```

*Note: If PostgreSQL is not installed locally, the backend automatically uses the embedded SQLite database at `data/evalai.db`.*

### 2. Frontend Setup

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite dev server (runs on port 3000)
npm run dev
```

Visit **`http://localhost:3000`** in your browser. All API calls to `/api` are automatically proxied to the backend on `http://127.0.0.1:8400`.

---

## Configuration

### `backend/config/settings.yaml`
Controls the active AI provider, model profile, OCR settings, and runtime safety margins:
```yaml
ai_provider: "gemini"
active_model_profile: "gemini_flash_lite_latest"
```

### Environment Variables (`.env`)
- `GEMINI_API_KEY`: API key for Google Gemini Multimodal models.
- `DATABASE_URL`: PostgreSQL connection URL (e.g. `postgresql://postgres:password@localhost:5432/evalai_db`).
- `JWT_SECRET`: Secret token for teacher session authentication.
- `API_PORT`: Backend port (default: `8400`).

---

## Running the Tests

```bash
# Backend unit tests
cd backend
pytest tests/unit

# Frontend type check
cd ../frontend
npm run check
```
