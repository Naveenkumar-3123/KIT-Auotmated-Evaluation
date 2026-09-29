# EvalAI — Project Context Handoff

*Read this first. It explains what the project is, how it works, how to run it,
its current state, and lessons learned — so a fresh session can be productive
immediately. Last updated: 2026-09-21.*

---

## 1. What this project is

**EvalAI** — an AI-powered, fully-local answer-paper evaluation system. It takes
**scanned handwritten answer sheets** (PDFs), reads the student's handwriting, grades
it against a teacher's **answer key**, and proposes marks. **Every mark is reviewed by
the teacher before it becomes final** — teacher approval is a built-in gate in the
workflow, not an afterthought.

Design philosophy: *the AI proposes, deterministic code enforces policy, and the
teacher decides. Nothing is ever silently graded.*

The full narrative technical overview lives in `docs/system-overview.md` — the best
prose description of the system; read it alongside this file.

---

## 2. Technology stack

| Layer | Technology | Notes |
|---|---|---|
| AI runtime | **Ollama + Qwen3-VL 4B** (vision-language model) | Runs 100% locally on one PC (RTX 3060 12 GB). No student data leaves the machine. |
| Orchestration | **LangGraph** | 12-stage evaluation pipeline as a stateful graph with durable checkpoints (SQLite or Postgres). |
| Backend API | **FastAPI** (Python ≥3.11) | Uploads, configuration, results, teacher review. |
| Storage | **Supabase Postgres** + local file storage (`data/storage/`) | Jobs, results, review decisions, evidence. Auth via **Supabase JWT**; row-level ownership checks on every endpoint. |
| Queue/leases | Postgres-backed job store (`src/answer_eval/jobs/pg_store.py`) | Workers claim jobs with leases + heartbeats (Redis optional, not required). |
| Frontend | **React + Vite + TypeScript + pnpm** | Teacher workspace: Configure → Evaluation → Results. |
| Image processing | OpenCV (headless), PyMuPDF, Pillow, NumPy | PDF render → preprocess → segment. |
| Config | `config/*.yaml` (settings, models, preprocessing, runtime profiles) + `.env` | |
| Quality | ruff (line-length 120, py311), mypy, pytest | pytest `pythonpath=["src","."]`, asyncio_mode auto. |

Key `.env` values: `AI_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434/v1`,
`VISION_MODEL=qwen3-vl:4b`, `API_PORT=8300`, `STORAGE_LOCAL_ROOT=data/storage`,
Supabase URL/keys, `WORKER_TOKEN` (shared secret workers use to register/claim jobs).

---

## 3. Repository layout

```
d:\answer paper eval\
├── src\answer_eval\            # Python package (hatchling, packages=["src/answer_eval"])
│   ├── agents\                 # ocr\, diagram\, reconstruction\ (perceptual agents around the VLM)
│   ├── answerkey\              # answer-key parsing (parser.py, converters for DOCX etc.)
│   ├── api\                    # FastAPI app + routers\ (answer_keys, assessments, ...)
│   ├── grading\                # confidence\, evaluation\, rules\, strictness\, verification\
│   ├── jobs\                   # pg_store.py (Postgres job/lease store), worker.py, perception_persist.py (NEW)
│   ├── processing\             # image\ (preprocess), pdf\, segmentation\ (segmenter.py), mapping\
│   ├── prompts\templates\      # versioned system prompts per task: ocr, segmentation, evaluation,
│   │                           #   verification, diagram, diagram_evaluation, math_evaluation, semantic_mapping
│   ├── inference\              # ollama_provider.py (OpenAI-compatible client to Ollama)
│   ├── workflow\               # LangGraph pipeline graph
│   ├── db\repositories\        # results.py etc. (data access)
│   ├── benchmark\, core\, hardware\, ingestion\, models\, runtime\, services\, storage\
├── UserInterface_answerpaper_eval\ocr-accuracy-evaluator\   # the frontend workspace (pnpm)
│   ├── client\src\api\ (answerKeys.ts, results.ts, processing.ts NEW)
│   ├── client\src\pages\ (Configure.tsx, Results.tsx), components\configure\UploadStep.tsx
│   ├── server\, shared\, patches\
├── supabase\                   # DB migrations (apply with scripts/apply_migrations.py)
├── tests\unit\, tests\integration\   # extensive suite (~50 test files)
├── scripts\                    # diagnostics & smoke tests (see §8)
├── config\                     # settings.yaml, models.yaml, preprocessing.yaml, runtime_profiles.yaml
├── docs\                       # system-overview.md, supabase-setup.md, PROJECT-CONTEXT.md (this file)
├── data\                       # runtime artifacts (uploads, preprocessed pages, storage) — untracked by design
├── benchmarks\, models\, tools\, temp\
├── pyproject.toml, .env, .env.example
```


---

## 4. The evaluation pipeline (per answer sheet)

LangGraph state machine, 12 stages, each **idempotent and checkpointed** — a crash or
restart resumes exactly where it stopped:

```
 1. Validate        PDF exists, rubrics well-formed — bad input never reaches the AI.
 2. Render PDF      Each page rendered to a high-resolution image.
 3. Preprocess      Deskew, denoise, contrast (CLAHE), resolution-normalise.
 4. Segment         Split each page into answer regions (whitespace/ink analysis).
 5. Map questions   Attach each region to a question number (three-layer cascade, §5).
 6. OCR             Verbatim transcription of every region.
 7. Diagrams        Detect/extract student diagrams where present.
 8. Reconstruct     Merge a question's regions/pages into one canonical answer.
 9. Rules engine    Deterministic penalties: word count, missing diagrams, mandatory terms.
10. Evaluation      AI grades semantic correctness vs the answer key.
11. Verification    Second "blind" AI pass re-grades independently; disagreements → review flags.
12. Risk & review   Risk engine decides: auto-approve, or hold for the teacher.
```

After the pipeline: marks land in the **teacher review panel** → teacher
approves/overrides → results finalise into the Results read-model.

---

## 5. Question→region mapping (the hard part with scans)

Student sheets rarely have machine-readable question numbers, so mapping is a
**three-layer cascade** (each layer only runs if the previous is inconclusive; every
fallback is flagged for teacher review):

1. **Margin anchors** — ink scan of the left margin + OCR of the strip finds question
   numbers written at the margin (most reliable when present).
2. **Header anchors** — OCR of the top band of each answer block (typical for phone
   scans where students re-write the question number).
3. **Semantic mapping (AI)** — last resort: the VLM compares each unmatched region's
   transcription against the *unanswered* questions from the key and assigns by
   content (e.g. a paragraph about PCA → the PCA question). Always flagged
   `semantic_mapping` → routed to review. Never invents question/region ids.
4. Below that: a strictly guard-limited deterministic tail-assignment + sequential
   fallback, both flagged.

### The agents (same local VLM, specialised prompts + schemas)

- **OCR Agent** — "transcribe, never interpret." Exact verbatim transcription of one
  cropped region; faithfulness > readability (grading compares meaning, so OCR
  "corrections" would distort evidence).
- **Diagram agents** — detect/extract diagrams; separate diagram-evaluation prompt.
- **Evaluation agent** — grades against the key; never invents criteria or marks;
  "wrong final answer ≠ zero correct working; correct final answer ≠ full marks alone."
- **Verification agent** — a blind, independent re-grade ("you have NOT been given any
  other grader's result"); disagreements raise review flags.
- **Semantic mapper** — question assignment by content (layer 3 above).

Prompt templates: `src/answer_eval/prompts/templates/<task>/base.txt`, versioned —
the authoritative text is in the repo, not inline strings.

---

## 6. Jobs, workers, review flow

- Postgres-backed job store with **leases + heartbeats** (`jobs/pg_store.py`,
  `jobs/worker.py`). Workers register with a shared `WORKER_TOKEN`.
- A recent fix (commit `8fa003e`) stopped **a remote worker claiming jobs it cannot
  run** — worker capability matching exists; don't regress it.
- `jobs/perception_persist.py` (+ `tests/unit/test_perception_persist.py`) is a
  **new, untracked** addition persisting perception artifacts (pages, segments,
  OCR transcriptions) so the UI can show processing evidence.
- `GET /assessments/submissions/{id}/processing` serves everything; the Results page
  "View Processing Details" drawer shows five tabs: Original, Preprocessed, Segments,
  OCR, Evaluation Data.
- Teacher review: approval gate → teacher approves/overrides → results finalise.

---

## 7. Database (Supabase) & frontend

- Migrations in `supabase\`; apply with `python scripts/apply_migrations.py`
  (needs `DATABASE_URL` from `.env`). See `docs/supabase-setup.md`.
- Auth = Supabase JWT; every endpoint enforces row-level ownership (teachers only
  see their own assessments).
- Frontend root: `UserInterface_answerpaper_eval/ocr-accuracy-evaluator/` (pnpm
  workspace: `client/`, `server/`, `shared/`, `patches/`).
- Teacher flow: **Configure → Evaluation → Results**.
- Frontend env: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE_URL`
  (empty = same-origin `/api` proxy in dev).

---

## 8. How to run / test (Windows machine)

```powershell
# Backend deps
pip install -e ".[all]"          # or needed extras: workflow, api, docparse, benchmark...

# Tests (pythonpath=src; asyncio auto)
python -m pytest tests -m "not gpu and not model" -x -q     # unit, no GPU/model needed
python -m pytest tests/unit -x -q

# API + worker — IMPORTANT on Windows: PYTHONUTF8=1
$env:PYTHONUTF8="1"
uvicorn ... (API on port 8300; worker via src/answer_eval/jobs/worker.py)
```

**Known Windows caveat (critical):** the API worker **must** be launched with
`PYTHONUTF8=1`. structlog writes non-ASCII rubric text; the default cp1252 codec
crashes the worker with `UnicodeEncodeError`. Same reason ad-hoc Python snippets
should be run as `python -X utf8 ...`.

Diagnostics/smoke: `scripts/smoke_e2e.py`, `scripts/smoke_m3_http.py`,
`scripts/smoke_m6_http.py`, `scripts/check_db_state.py`, `scripts/diag_db.py`,
`scripts/diag_segmentation.py`, `scripts/enqueue_assessment.py`,
`scripts/apply_migrations.py`.

pytest markers: gpu / model / integration / slow (e.g. `-m "not gpu and not model"`).

---

## 9. Current state (as of 2026-09-21, commit 8fa003e on main)

Recent history:

```
8fa003e fix: evaluations failed because a remote worker claimed jobs it cannot run
ebb1698 fix(segmentation): correct region recognition - non-overlapping bands and rule-robust margin anchors
2548402 feat: add answer paper evaluation system - UI, backend, jobs, and tests
ff8f6ad feat: complete answer sheet perception pipeline with Qwen3-VL Ollama integration
```

**Uncommitted working-tree changes (in-flight work, do not lose):**
- Modified: `src/answer_eval/answerkey/parser.py`,
  `api/routers/{answer_keys,assessments}.py`, `db/repositories/results.py`,
  `inference/ollama_provider.py`, `jobs/{pg_store,worker}.py`,
  `processing/segmentation/segmenter.py`,
  `tests/unit/{test_answerkey_parser,test_segmentation}.py`, plus frontend files
  in §7, and new untracked `jobs/perception_persist.py` +
  `tests/unit/test_perception_persist.py` + `client/src/api/processing.ts`.
- Answer-key parsing on dense scans: batch parsing is in place; a **tolerant JSON
  salvage layer** now recovers complete question objects from truncated model output.
- Handwriting OCR: currently the 4B local model; an **8B upgrade path exists** and is
  benchmarked before switching (benchmark extras: jiwer, rapidfuzz).

---

## 10. Prior-session incident — corrupted PDF uploads (context + warning)

A user uploaded two PDFs for manual evaluation: a student's scanned answer paper
(`23CSE019.pdf`, 10 scanned pages) and an answer key (`answer key 2m.pdf`, 14 pages).
Both were **irreversibly corrupted**: every byte ≥ 0x80 had been replaced with the
UTF-8 replacement character `EF BF BD` (≈2.0M occurrences in the paper, ≈193k in the
key) — the files had passed through a UTF-8 text-encoding layer at some point.

Findings:
- No recoverable images/text: the paper's JPEG scans had zero valid JPEG markers;
  the key's FlateDecode streams all failed zlib (`incorrect header check`).
- The only salvage was **uncompressed accessibility metadata** in the key:
  169 MathML equation fragments (saved to `key_mathml.txt`), showing the key is about
  **SVMs** (`wᵀx + b = 0`, distance formula, support vectors C1(2,10), C2(5,8)).
- Evaluation was **impossible**; the user was told to re-upload intact originals.

Lesson for the ingestion pipeline: uploads may arrive corrupted like this. A cheap
validation (detect high `EF BF BD` density / broken PDF headers early) would give a
clean error message instead of blank-page garbage downstream. Consider adding such a
check to `src/answer_eval/ingestion/` (`test_ingestion_zipscan.py` there covers
zip-bomb protection — this would be a sibling concern).

Scratch files from that session are untracked and safe to delete:
`answer_key.txt`, `answer_paper.txt`, `key_mathml.txt`, `pages_paper\`,
`pages_key\`, `img_paper\`.

---

## 11. Conventions & gotchas summary

- Package layout: `src/answer_eval/...` (hatchling); tests in `tests/unit` and
  `tests/integration`; pytest `pythonpath=["src","."]`.
- Prompts are **files under version control** (`prompts/templates/<task>/base.txt`),
  versioned — update thoughtfully, never inline string prompts.
- Never award more than the rubric max; never invent criteria; teacher gate is sacred.
- Every fallback/uncertainty must be **flagged** for teacher review
  (`semantic_mapping`, `llm_assigned_by_content`, blind-verification disagreements).
- Pipeline stages are idempotent + checkpointed; preserve that property when editing.
- Windows: always `PYTHONUTF8=1` for API/worker; `python -X utf8` for ad-hoc scripts.
- Deps pinned loosely in `pyproject.toml` (PyMuPDF≥1.24, langgraph≥1.0, pydantic≥2.0,
  opencv-python-headless≥4.9, sympy≥1.12 for math grading, structlog for logging).
- `data/` and `temp/` contents are runtime artifacts, untracked by design.
