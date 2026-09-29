# EvalAI — Project Proposal

**Full-Stack AI Answer-Sheet Evaluation System**
Tagline: *Automated, Teacher-Verified Grading of Handwritten Answer Sheets*
Version: 1.0 · Status: working prototype (single-PC, fully local) · Runtime: Python ≥3.11, Node/pnpm

---

## 1. Executive Summary

EvalAI is an AI-powered evaluation platform that converts **scanned handwritten answer sheets (PDFs)** into **verified, auditable marks**. It reads a student's handwriting with a locally hosted vision-language model, maps each answer region to the correct question, grades it against a teacher's answer key, and proposes marks — **every mark is reviewed by the teacher before it becomes final**.

The system is built around one non-negotiable principle:

> **The AI proposes, deterministic code enforces policy, and the teacher decides. Nothing is ever silently graded.**

Unlike cloud-dependent OCR/grading services, EvalAI runs **100% on local hardware** (a single RTX 3060 12 GB PC), so student data never leaves the institution. The platform is designed for universities and coaching centres that need faster, consistent, and auditable marking without surrendering final authority to an algorithm.

---

## 2. Problem Statement

Manual evaluation of handwritten answer papers is slow, inconsistent, and expensive:

| Pain point | Consequence |
|---|---|
| **Time** — 3–5 minutes per script × hundreds of students | Marking cycles take days; feedback is delayed for students. |
| **Inconsistency** — the same answer scores differently across markers | Students lose faith in fairness; appeals rise. |
| **Scalability** — every extra batch costs more markers | Institutions cap enrollment or cut assessment quality. |
| **No traceability** — marks live in spreadsheets | When a student disputes a score, there is no evidence trail. |
| **Privacy risk** — cloud AI tools require uploading student handwriting | Many institutions cannot legally do this. |
| **Subjective drift** — partial credit and penalties are applied inconsistently | Internal marking audits fail; moderation becomes manual. |

EvalAI addresses all six: it automates the mechanical 80% while preserving human judgement for the consequential 20%.

---

## 3. Objectives

1. **Parse** any scanned answer-sheet PDF into individual, question-attributed answers.
2. **Grade** each answer semantically against an official answer key, applying deterministic marking policy (word count, mandatory terms, diagram requirements).
3. **Verify** every AI mark with an independent blind second pass; disagreements are escalated, not averaged away.
4. **Gate** every result through a teacher review/approval screen so no mark is final without human sign-off.
5. **Run entirely on-premise** with zero student data leaving the local machine.
6. **Survive failure** — the pipeline is checkpointed, idempotent, and resumable; crashes, restarts, and power cuts never lose progress or double-grade.
7. **Remain auditable** — every mark is traceable to its rubric, prompt version, model version, and review decision.

---

## 4. Scope

### In scope
- Upload of answer keys and student answer-sheet PDFs (single or batch).
- Answer-key parsing into structured rubrics (question text, expected answer, concepts, marks).
- Teacher configuration of marking policy per question/assessment.
- Handwriting OCR, diagram detection, question-region segmentation and mapping.
- AI semantic evaluation, blind verification, risk scoring, and teacher review.
- Results dashboard with per-question marks, feedback, transcriptions, and processing evidence.
- Analytics (per-student, per-question, cohort-level).

### Out of scope (explicit non-goals)
- Fully autonomous "final" grading with no human gate — **deliberately excluded**.
- Cloud/hosted model dependency — the architecture assumes local inference.
- MCQ/OMR bubble-sheet auto-scoring (the pipeline targets free-response handwritten answers).
- Proctoring, plagiarism detection, or LMS integration beyond auth.

---

## 5. System Concept — How It Works

EvalAI is organised as a **12-stage, checkpointed pipeline** (implemented as a LangGraph state machine). Each stage is idempotent, so the job can be re-run or resumed safely.

```
 1. Validate        PDF exists, rubrics well-formed — bad input never reaches the AI.
 2. Render PDF      Each page rendered to a high-resolution image.
 3. Preprocess      Deskew, denoise, contrast (CLAHE), resolution-normalise.
 4. Segment         Split each page into answer regions (whitespace/ink analysis).
 5. Map questions   Attach each region to a question number (3-layer cascade, §5.2).
 6. OCR             Verbatim transcription of every region.
 7. Diagrams        Detect/extract student diagrams where present.
 8. Reconstruct     Merge a question's regions/pages into one canonical answer.
 9. Rules engine    Deterministic penalties: word count, missing diagrams, mandatory terms.
10. Evaluation      AI grades semantic correctness vs the answer key.
11. Verification    A second, "blind" AI pass re-grades independently; disagreements raise flags.
12. Risk & review   Risk engine decides: auto-approve, or hold for teacher review.
```

After stage 12, marks land in the **teacher review panel** → the teacher approves or overrides → results are finalised into the Results read-model.

### 5.1 The AI agents (specialised prompts around one local VLM)
Each capability is a versioned system prompt plus a strict output schema:
- **OCR agent** — "transcribe, never interpret": verbatim handwriting transcription. Faithfulness over readability; any uncertainty is flagged, never "helpfully corrected".
- **Diagram agent** — detects and describes student diagrams so missing figures can be penalised deterministically.
- **Semantic-mapping agent** — assigns unmatched answer regions to questions by content.
- **Evaluation agent** — grades one question's reconstructed answer against the rubric, criterion by criterion, never inventing criteria and never exceeding the maximum.
- **Verification agent** — an *independent blind marker*: it never sees the first grader's marks, forcing a genuine second opinion.

> Prompts live under `src/answer_eval/prompts/templates/<task>/base.txt` and are version-controlled — the authoritative text is in the repo, never inlined in code.

### 5.2 Mapping answers to questions (the hard problem with scans)
Students' scans rarely carry machine-readable question numbers, so EvalAI uses a **three-layer cascade**, each layer running only if the previous is inconclusive, with every fallback flagged for review:
1. **Margin anchors** — ink scan of the left margin + OCR finds question numbers written at the margin (most reliable when present).
2. **Header anchors** — for phone scans without a margin, OCR the top band of each answer block where students re-write the number.
3. **Semantic mapping (AI)** — the VLM matches each unmatched region's transcription against the *unanswered* questions by content; always flagged for review.

---

## 6. Design Principles

1. **Human-in-the-loop by design** — teacher approval is a workflow gate, not an afterthought. The AI never finalises a mark alone.
2. **Deterministic policy beats model judgement** — word-count penalties, mandatory terms, and diagram requirements are enforced in code, not asked of the LLM, so they are reproducible.
3. **Uncertainty is surfaced, never hidden** — any fallback, disagreement, or low-confidence OCR raises a review flag rather than silently guessing.
4. **Privacy first** — all inference is local; no student handwriting or results leave the machine.
5. **Fail-safe durability** — every stage checkpoints; the system resumes after crashes instead of restarting from zero.
6. **Single-PC operability** — the whole system (API, worker, model, database) runs on one machine, lowering the barrier for institutions.

---

## 7. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| AI runtime | **Ollama + Qwen3-VL 4B** | Local vision-language model for OCR, mapping, and grading. |
| Orchestration | **LangGraph** | 12-stage pipeline as a stateful, checkpointed graph. |
| Backend API | **FastAPI** (Python ≥3.11) | Uploads, configuration, results, teacher review. |
| Storage | **Supabase Postgres** + local file storage | Jobs, results, review decisions, evidence. |
| Queue / leases | Postgres-backed job store (Redis optional) | Workers claim jobs with leases + heartbeats. |
| Frontend | **React + Vite + TypeScript + pnpm** | Teacher workspace: Configure → Evaluation → Results → Analytics. |
| Auth | **Supabase JWT** | Teachers see only their own assessments (row-level ownership). |
| Image processing | OpenCV, PyMuPDF, Pillow, NumPy | Render → preprocess → segment. |
| Config | `config/*.yaml` + `.env` | Settings, models, preprocessing, runtime profiles. |
| Quality | ruff, mypy, pytest | Lint, type-check, test. |

---

## 8. Repository Layout (conceptual)

```
src/answer_eval/
├── agents/            # OCR, diagram, reconstruction (perceptual agents around the VLM)
├── answerkey/         # Answer-key parsing and structured rubric extraction
├── api/               # FastAPI app + routers (answer_keys, assessments, reviews, results)
├── grading/           # Evaluation, verification, rules, confidence, strictness
├── jobs/              # Postgres job/lease store, worker, perception persistence
├── processing/        # PDF render, image preprocess, segmentation, question mapping
├── prompts/templates/ # Versioned system prompts per task
├── inference/         # Ollama provider (OpenAI-compatible client)
├── workflow/          # LangGraph pipeline graph (the 12 stages)
├── db/repositories/   # Data access (results, reviews, answer keys)
├── benchmark/         # Accuracy benchmarks (handwriting, parsing)
└── ...                # core, models, runtime, storage, services

UserInterface_answerpaper_eval/ocr-accuracy-evaluator/   # React + Vite teacher workspace
config/                                                # settings, models, preprocessing, profiles
docs/                                                   # system overview, project context, setup
tests/                                                  # unit + integration tests
```

---

## 9. How the Teacher Uses It (user journey)

1. **Sign in** — Supabase auth; the teacher sees only their own assessments.
2. **Upload an answer key** — the system parses it into structured rubrics (question text, expected answer, concepts, marks). The teacher reviews/corrects the parse (the "teacher-review path").
3. **Upload student answer sheets** — one or a batch of scanned PDFs.
4. **Configure marking policy** — per-question word counts, mandatory terms, diagram requirements; mark maxima; save and finalise the assessment.
5. **Enqueue evaluation** — a durable job is created; a worker claims it with a lease and runs the 12-stage pipeline, checkpointing as it goes.
6. **Review results** — the Results screen shows proposed marks, per-criterion feedback, OCR transcriptions, and a five-tab "Processing Details" drawer (Original, Preprocessed, Segments, OCR, Evaluation Data).
7. **Approve / override** — the teacher confirms or edits each mark; approved results are finalised.
8. **Analytics** — cohort and per-question performance trends.

---

## 10. Verification & Quality Assurance

- **Deterministic policy tests** — word-count and diagram penalties are unit-tested against fixed inputs.
- **End-to-end pipeline tests** — a full run from PDF → results is exercised on fixtures.
- **Regression on a real submission** — the platform is validated against a known student submission (`23CSE019`) and its official answer key, producing verifiable marks (a manual reference score was cross-checked against the software's output).
- **Schema-validated AI output** — every model response is parsed against a Pydantic schema; invalid JSON is retried, and persistent truncation is escalated rather than guessed around.
- **Idempotency & crash-recovery tests** — the job/lease store is tested for reclaim, retry, and resume semantics.

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Handwriting OCR inaccuracy (4B model) | Region-level confidence flags; upgrade path to an 8B model benchmarked before switching; teacher reviews transcriptions alongside marks. |
| Model output truncation on long questions | Structured-JSON retry with a larger token budget (e.g. 8192) and a tolerant salvage layer that recovers complete question objects from truncated output. |
| Stale rubric snapshots reused on re-run | Fresh assessment runs re-resolve policy snapshots; correctness is verified by checking per-question maxima in logs and database. |
| Corrupted uploads (encoding-damaged PDFs) | Validate PDF integrity early and surface a clear ingestion error instead of blank-page garbage downstream. |
| Memory pressure crashing local inference | Headroom tuning (context/token budget) and restart-safe checkpoints so no work is lost. |
| Over-trust in AI marks | Teacher approval gate + blind verification + risk scoring; deterministic policy for objective penalties. |

---

## 12. Future Enhancements (Roadmap)

- **Handwriting accuracy upgrade** — benchmark and adopt an 8B vision model where hardware allows.
- **Early ingestion validation** — detect corrupted/encoding-damaged PDFs at upload with a clear error.
- **Rubric drift guard** — automated detection of stale policy snapshots on re-runs.
- **Cohort analytics expansion** — per-cohort and per-question trend dashboards.
- **Multi-subject templates** — reusable preprocessing/segmentation profiles by subject and paper layout.
- **Optional multi-worker scaling** — Redis-backed queue for institutions that outgrow one machine.

---

## 13. Deliverables

1. **EvalAI backend** (`src/answer_eval/`) — FastAPI control plane, 12-stage LangGraph pipeline, Postgres job store, local Ollama inference.
2. **Teacher web app** (`UserInterface_answerpaper_eval/…`) — React/Vite workspace: Configure → Evaluation → Results → Analytics, with the review gate and processing-evidence drawer.
3. **Configuration & prompts** (`config/`, `src/answer_eval/prompts/`) — versioned settings and system prompts.
4. **Tests & benchmarks** (`tests/`, `benchmark/`) — unit, integration, end-to-end, and accuracy benchmarks.
5. **Documentation** (`docs/`) — system overview, project context, and setup guides.

---

## 14. Conclusion

EvalAI automates the repetitive work of reading and grading handwritten answer sheets while keeping the teacher firmly in control. By combining a local vision-language model, a deterministic rules engine, independent blind verification, and a mandatory teacher-approval gate, it delivers faster, more consistent, and fully auditable marking — without compromising student privacy or human accountability. The system has been exercised end-to-end on real submissions against official answer keys, demonstrating that the marks it produces are verifiable and trustworthy.

---

*Repository references: pipeline in `src/answer_eval/workflow/`, agents in `src/answer_eval/agents/`, prompts in `src/answer_eval/prompts/templates/`, job/review system in `src/answer_eval/jobs/` and `src/answer_eval/api/`, technical overview in `docs/system-overview.md`.*
