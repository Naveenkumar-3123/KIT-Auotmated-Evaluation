# EvalAI — Answer Sheet Evaluation System

**Automated, teacher-verified grading of handwritten answer sheets.**

EvalAI turns scanned handwritten answer sheets (PDFs) into verified, auditable marks. It reads a
student's handwriting with a locally hosted vision-language model, maps each answer region to the
correct question, grades it against a teacher's answer key, and proposes marks — **every mark is
reviewed by the teacher before it becomes final.**

> **The AI proposes, deterministic code enforces policy, and the teacher decides.
> Nothing is ever silently graded.**

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
- [Developer Test UI](#developer-test-ui)
- [Known Limitations](#known-limitations)
- [Further Reading](#further-reading)

---

## Why

Grading handwritten answer sheets by hand is slow, inconsistent, and hard to audit. EvalAI is built
around a simple premise: **AI grading is only trustworthy when it is verifiable.** So the system
keeps a complete evidence trail — every page render, every region crop, every OCR transcription,
and two independent grading passes that must not silently disagree.

Everything runs **fully locally** on a single PC. No student data leaves the machine.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| AI runtime | **Ollama** + **Qwen3-VL 4B** (vision-language) | Local handwriting understanding. No data leaves the machine. |
| Orchestration | **LangGraph** | 12-stage pipeline as a stateful graph with durable checkpoints — a crash never loses progress. |
| Backend API | **FastAPI** (Python ≥ 3.11) | Uploads, configuration, results, teacher review. |
| Durable storage | **PostgreSQL** + local file storage | Jobs, results, review decisions, evidence. |
| Queue / leases | PostgreSQL-backed job store (Redis optional) | Single-PC friendly; workers claim jobs with leases and heartbeats. |
| Frontend | **React 19 + Vite + TypeScript** | Teacher workspace: Configure → Evaluation → Results. |
| Auth | **Supabase JWT** | Teachers only see their own assessments (row-level checks on every endpoint). |

---


## The Pipeline

The pipeline is a LangGraph state machine with 12 stages. Each stage is idempotent (safe to re-run)
and its output is checkpointed, so a restart resumes exactly where it stopped.

```
 1. Validate        PDF exists, rubrics well-formed — bad input never reaches the AI.
 2. Render PDF      Each page rendered to a high-resolution image.
 3. Preprocess      Deskew, denoise, contrast (CLAHE), resolution-normalise.
 4. Segment         Split each page into answer regions (whitespace/ink analysis).
 5. Map questions   Attach each region to a question number (see below).
 6. OCR             Verbatim transcription of every region.
 7. Diagrams        Detect/extract student diagrams where present.
 8. Reconstruct     Merge a question's regions/pages into one canonical answer.
 9. Rules engine    Deterministic penalties: word count, missing diagrams, mandatory terms.
10. Evaluation      AI grades semantic correctness vs the answer key.
11. Verification    A second, "blind" AI pass re-grades independently;
                    disagreements between the two passes raise review flags.
12. Risk & review   Risk engine decides: auto-approve, or hold for the teacher.
```

After the pipeline, marks land in the **teacher review panel** → teacher approves or overrides →
results are finalised into the Results read-model.

### Roles of the AI agents

Each stage's AI behaviour is a versioned system prompt under
`src/answer_eval/prompts/templates/<task>/base.txt`. Two conventions matter most:

- **OCR agent — "transcribe, never interpret."** It copies text exactly as written and preserves
  spelling mistakes. A "helpful" correction by the OCR would corrupt the grading evidence.
- **Verification agent — blind re-grade.** It is explicitly told it has *not* seen the first
  grader's marks and must evaluate from scratch. Two independent passes that disagree become a
  review flag rather than a silent choice.

---


## Question Mapping

Students' scans rarely have machine-readable question numbers, so mapping uses a **three-layer
cascade**. Each layer runs only if the previous one is inconclusive, and every fallback is flagged
for teacher review:

1. **Margin anchors** — ink scan of the left margin + OCR of that strip finds question numbers
   written at the margin. Most reliable when present.
2. **Header anchors** — when the margin yields nothing (typical for phone scans), the system OCRs
   the top band of each answer block, where students usually re-write the number.
3. **Semantic mapping (AI)** — as a last resort, the VLM matches each unmatched region's
   transcription against the *unanswered* questions from the answer key. A paragraph about PCA is
   matched to the PCA question. Always flagged → routed to review.

A deterministic tail-assignment and a sequential fallback sit below these, and are flagged too.

---

## Repository Layout

```
src/answer_eval/
├── workflow/        LangGraph pipeline definition and state
├── agents/          OCR, diagram, reconstruction agents
├── prompts/         Versioned system prompts (templates/<task>/base.txt)
├── processing/      PDF rendering, image preprocessing, segmentation, mapping
├── answerkey/       Answer-key parsing (LaTeX / MathML / multi-page)
├── grading/         Rules, evaluation, blind verification, confidence, risk
├── inference/       Provider abstraction (Ollama, vLLM)
├── jobs/            Worker loop, Postgres job store, perception persistence
├── api/routers/     FastAPI endpoints (assessments, answer_keys, reviews, ...)
├── db/              Repositories and schema access
└── storage/         Local file storage provider

UserInterface_answerpaper_eval/ocr-accuracy-evaluator/
└── client/          React + Vite teacher workspace

config/              settings.yaml, models.yaml, preprocessing.yaml, runtime_profiles.yaml

## Getting Started

### Prerequisites

- Python **≥ 3.11**
- **Node ≥ 20** with **pnpm** (`pnpm@10.4.1` is pinned via `packageManager`)
- **PostgreSQL** — a local instance, or a Supabase project
- **Ollama** with the vision model pulled:
  ```bash
  ollama pull qwen3-vl:4b
  ```

### 1. Backend

```bash
git clone https://github.com/blank157/intern.git
cd intern

python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -e ".[api,workflow,dev]"

cp .env.example .env      # Windows:  copy .env.example .env
# then edit .env and fill in Supabase / Postgres credentials
```

Apply the database schema:

```bash
python scripts/apply_migrations.py
```

### 2. Frontend

```bash
cd UserInterface_answerpaper_eval/ocr-accuracy-evaluator
pnpm install
pnpm dev                             # http://localhost:3000
```

Set the public Supabase values in `UserInterface_answerpaper_eval/ocr-accuracy-evaluator/.env.local`
(`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`) before starting the dev server. That file is
git-ignored — never commit real keys.

## Configuration

Configuration lives in two places.

**`config/*.yaml`** — model profiles, preprocessing and runtime settings:

| File | Contents |
|---|---|
| `settings.yaml` | OCR and pipeline settings, including the `ocr:` section |
| `models.yaml` | Available vision models and their profiles |
| `runtime_profiles.yaml` | Runtime/hardware profiles |
| `preprocessing.yaml` | Deskew, CLAHE, border-cleanup parameters |

**Environment (`.env`)** — copy `.env.example`. The keys that matter most:

| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Public project settings (`VITE_*` variants go to the frontend) |
| `SUPABASE_SERVICE_ROLE_KEY` | **Backend only** — never expose to the browser |
| `DATABASE_URL` | Direct Postgres connection (use port `6543` pooler for serverless) |
| `API_HOST` / `API_PORT` | API bind address (default `127.0.0.1:8300`) |
| `API_ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `WORKER_TOKEN` | Shared token workers use to register and claim jobs |
| `AI_PROVIDER` / `OLLAMA_BASE_URL` | Inference backend (default `ollama` at `localhost:11434/v1`) |
| `VISION_MODEL` | Vision model tag (default `qwen3-vl:4b`) |
| `STORAGE_LOCAL_ROOT` | Local object storage root (default `data/storage`) |

> `.env` and `.env.local` are git-ignored. Never commit real credentials.

---

## Running the Tests

```bash
pytest                      # all tests
pytest tests/unit           # unit tests only
pytest -m "not slow"        # skip slow tests
```

Pytest markers: `gpu`, `model`, `integration`, `slow`. Configuration lives in `pyproject.toml`
(`pythonpath = ["src", "."]`), so no extra setup is needed.

Linting and type checks:

```bash
ruff check .
mypy src
```

---

## Developer Test UI

A **Streamlit** interface for inspecting each perception stage on real answer-sheet PDFs — page
renders, preprocessing, segmentation overlays, verbatim OCR beside the crop, diagrams, and
multi-page reconstruction. It also computes **CER/WER** against hand-entered ground truth and can
export golden fixtures for regression tests.

```bash
streamlit run tools/test_ui/app.py     # http://localhost:8501
```

It binds to `127.0.0.1`, has no auth or grading logic, and stores uploads under
`temp/test_ui/<session_id>/`. See [`tools/test_ui/README.md`](tools/test_ui/README.md) for the
full walkthrough.

---

## Known Limitations

Honest list of what is not production-hardened yet:

- **Answer-key parsing on dense scans** — batch parsing is in place; a tolerant JSON-salvage layer
  recovers complete question objects from truncated model output, but very dense pages still need
  tuning.
- **Handwriting OCR accuracy** — currently a 4B-parameter local model. An 8B upgrade path exists and
  is benchmarked before switching.
- **Single-PC scope** — designed and tested on one machine (RTX 3060 12 GB), not multi-tenant.
- **Windows UTF-8 caveat** — the API worker needs `PYTHONUTF8=1` (see above).

---

## Further Reading

- [`proposal.md`](proposal.md) — project proposal and design rationale
- [`docs/system-overview.md`](docs/system-overview.md) — end-to-end technical walkthrough
- [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md) — project context
- [`tools/test_ui/README.md`](tools/test_ui/README.md) — developer test UI guide

---

*Evaluation agents and their authoritative prompts live in `src/answer_eval/prompts/templates/`,
the pipeline in `src/answer_eval/workflow/`, and the job/review system in `src/answer_eval/jobs/`
and `src/answer_eval/api/`.*



### 3. Run the API and worker

> **⚠️ Windows:** launch the API worker with `PYTHONUTF8=1`. The default `cp1252` codec makes
> `structlog` crash on non-ASCII rubric text with a `UnicodeEncodeError`.
> ```powershell
> $env:PYTHONUTF8 = "1"
> ```

The API listens on `API_PORT` (default `8300`). Workers register with the API using
`WORKER_TOKEN`, claim jobs with leases, and heartbeat while processing.

---

supabase/migrations/ Schema, job store, and RLS policies
tools/test_ui/       Streamlit developer test UI (see below)
scripts/             Operational + diagnostic scripts
tests/unit/          Unit tests      tests/integration/  Integration tests
```

---
