"""Streamlit views for Modules 12-18: grading workspace (direct grading + jobs).

Rendered by tools/test_ui/app.py when the user selects the
"Grading & Workflow" workspace. All heavy lifting lives in
tools/test_ui/grading_adapter.py which is Streamlit-free and unit-tested.
"""

import json
import sys
import time
import uuid
from pathlib import Path

import streamlit as st

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
if str(WORKSPACE_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from answer_eval.grading.strictness.engine import StrictnessEngine  # noqa: E402
from tools.test_ui.grading_adapter import (  # noqa: E402
    SAMPLE_ANSWER_TEXT,
    SAMPLE_RUBRIC,
    GradingJobsController,
    build_grading_provider,
    mock_state_hook,
    run_direct_grading,
)


@st.cache_resource
def get_controller() -> GradingJobsController:
    """Singleton controller: durable SQLite store + queue + embedded worker."""
    return GradingJobsController()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def render_grading_workspace() -> None:
    controller = get_controller()

    with st.sidebar:
        st.title("🎯 Grading Workspace")
        st.caption("Developer Test UI — Modules 12–18")
        st.divider()

        st.subheader("Embedded Worker")
        if controller.worker_running:
            st.success(f"● Running — `{controller.worker_id}`")
        else:
            st.warning("○ Stopped")

        if "answer_text" not in st.session_state:
            st.session_state["answer_text"] = SAMPLE_ANSWER_TEXT
        if "rubric_json" not in st.session_state:
            st.session_state["rubric_json"] = json.dumps(SAMPLE_RUBRIC, indent=2)

        if st.button("🗑️ Clear Grading Results", width="stretch"):
            st.session_state["graded"] = None
            st.session_state["grading_error"] = None
            st.rerun()

        with st.expander("📖 What this tests", expanded=False):
            st.markdown(
                """
                **Direct Grading tab** — Modules 12–16 synchronously:
                deterministic rules → strictness policy → semantic evaluator →
                blind verifier → comparator → risk engine.

                **Jobs tab** — Modules 17–18 asynchronously:
                durable job store + queue + embedded worker running the full
                LangGraph workflow, incl. human-review interrupt/resume.
                """
            )

    st.header("🎯 Grading & Workflow — Developer Test UI")
    st.caption(
        "Rules → strictness → evaluation → blind verification → comparison → risk → "
        "**auto-approve / human review**; orchestrated by LangGraph and executed by queue workers."
    )

    tab_direct, tab_jobs = st.tabs(["🎯 Direct Grading (M12–16)", "⚙️ Jobs, Queue & Workers (M17–18)"])
    with tab_direct:
        _render_direct_grading_tab()
    with tab_jobs:
        _render_jobs_tab(controller)


# ---------------------------------------------------------------------------
# Tab 1 — Direct grading playground (Modules 12-16)
# ---------------------------------------------------------------------------
def _render_direct_grading_tab() -> None:
    col_answer, col_rubric = st.columns(2)

    with col_answer:
        st.subheader("Student Answer (untrusted input)")
        res = st.session_state.get("pipeline_result")
        canonical_answers = getattr(res, "canonical_answers", []) or []
        if canonical_answers:
            options = {a.question_id: a.raw_text for a in canonical_answers}
            pick = st.selectbox(
                "Load a reconstructed answer from a perception run:", list(options), key="pick_canonical"
            )
            if st.button("⬅ Use Selected Answer"):
                st.session_state["answer_text"] = options[pick]
                st.rerun()
        st.text_area("Answer text", key="answer_text", height=280)

    with col_rubric:
        st.subheader("Rubric / Answer Key")
        r1, r2 = st.columns(2)
        if r1.button("📄 Load Sample Rubric"):
            st.session_state["rubric_json"] = json.dumps(SAMPLE_RUBRIC, indent=2)
            st.rerun()
        if r2.button("✅ Validate Rubric Only"):
            try:
                from tools.test_ui.grading_adapter import validate_rubric_dict

                validate_rubric_dict(json.loads(st.session_state["rubric_json"]))
                st.success("Valid — would pass pre-LLM validation.")
            except Exception as e:
                st.error(f"Invalid rubric: {e}")
        st.text_area("Rubric JSON", key="rubric_json", height=220)

        strictness = st.slider(
            "Strictness score (overrides rubric)",
            0,
            100,
            int(json.loads(st.session_state["rubric_json"]).get("strictness", 60)),
            help="Module 13 maps this to a versioned StrictnessPolicy.",
            key="strictness_slider",
        )
        with st.expander("🔍 Strictness Policy Explorer (M13)", expanded=False):
            st.json(StrictnessEngine.build(strictness).model_dump())

    st.divider()

    mock_mode = st.radio(
        "Grading model",
        ["Real (Ollama qwen3-vl)", "Mock (instant, deterministic)"],
        horizontal=True,
        key="grading_model_radio",
    )

    if st.button(
        "▶ Grade Answer  (rules → strictness → evaluator → verifier → comparator → risk)",
        type="primary",
        use_container_width=True,
    ):
        _run_direct_grading_clicked(mock_mode.startswith("Mock"), strictness)

    if st.session_state.get("grading_error"):
        st.error(f"Grading failed: {st.session_state['grading_error']}")

    graded = st.session_state.get("graded")
    if graded:
        _render_graded_result(graded)


def _run_direct_grading_clicked(mock_mode: bool, strictness: int) -> None:

    try:
        rubric_dict = json.loads(st.session_state["rubric_json"])
    except json.JSONDecodeError as e:
        st.session_state["graded"] = None
        st.session_state["grading_error"] = f"Rubric is not valid JSON: {e}"
        return

    rubric_dict["strictness"] = int(strictness)
    answer_text = st.session_state["answer_text"]

    provider = build_grading_provider(mock_mode, answer_text=answer_text, rubric=rubric_dict)
    try:
        with st.spinner("Running Modules 12–16 (evaluator + blind verifier may take ~1 min on real model)..."):
            graded = run_direct_grading(provider, answer_text, rubric_dict, submission_id="SUB-DEV-UI")
        st.session_state["graded"] = graded.model_dump(mode="json")
        st.session_state["grading_error"] = None
    except Exception as e:
        st.session_state["graded"] = None
        st.session_state["grading_error"] = f"{type(e).__name__}: {e}"


def _render_graded_result(g: dict) -> None:
    marks, risk, comp = g["marks"], g["risk"], g["comparison"]
    st.subheader(f"📊 Grading Result — {g['question_id']}` ({g['schema_version']})`")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Final Marks", f"{marks['final_proposed_marks']} / {marks['maximum_marks']}")
    m2.metric("Criteria Total", marks["criteria_total"])
    m3.metric("Deterministic Penalty", marks["deterministic_penalty"])
    m4.metric("Risk Level", str(risk["risk_level"]).upper())
    m5.metric("Auto Approve", "YES ✅" if risk["auto_approve"] else "NO 🧑‍🏫")

    if risk["auto_approve"]:
        st.success("✅ **AUTO APPROVED** — low risk, all hard validations passed, no mandatory triggers.")
    else:
        reasons = "\n".join(f"- {r}" for r in risk.get("review_reasons", [])) or "- (see flags)"
        st.warning(f"🧑‍🏫 **HUMAN REVIEW REQUIRED**\n{reasons}")

    # ------------------------------------------------------------- rule facts
    rr = g["rule_result"]
    wc = rr["word_count"]
    with st.expander("🧮 Deterministic Rule Engine Facts (M12)", expanded=False):
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Word Count", wc["actual"], f"min {wc['minimum']} → effective {wc['effective_minimum']}")
        f2.metric("Within Requirement", wc["within_requirement"], f"deficit {wc['deficit']}")
        kw = rr["keywords"]
        f3.write(f"**Keywords matched**: {kw['matched'] or '—'}")
        f3.write(f"**Missing optional**: {kw['missing_optional'] or '—'}")
        mt = rr["mandatory_terms"]
        f4.write(f"**Mandatory matched**: {mt['matched'] or '—'}")
        f4.write(f"**Mandatory missing**: {mt['missing'] or '—'}")
        dg = rr["diagram"]
        rv = rr["rubric_validation"]
        c1, c2 = st.columns(2)
        c1.write(f"**Diagram**: required={dg['required']} present={dg['present']}")
        c1.write(f"**Answer flags**: empty={rr['answer_empty']} too_short={rr['answer_too_short']}")
        c2.write(
            f"**Rubric arithmetic**: valid={rv['valid']} (criteria {rv['criteria_total']} / max {rv['question_maximum']})"
        )
        for p in rr["deterministic_penalties"]:
            c2.warning(f"Penalty `{p['penalty_type']}`: -{p['marks']} ({p['reason']})")

    # --------------------------------------------------------------- criteria
    st.markdown("**Criterion-level semantic evaluation (M14)** — evidence verified against the canonical answer:")
    rows = []
    for c in g["evaluation"]["criteria"]:
        rows.append(
            {
                "ID": c["criterion_id"],
                "Criterion": c["criterion"],
                "Status": c["status"],
                "Match": c["match_type"],
                "Marks": f"{c['proposed_marks']:g}/{c['maximum_marks']:g}",
                "Evidence": len(c["student_evidence"]),
                "All Verified": all(e.get("verified_in_answer") for e in c["student_evidence"])
                if c["student_evidence"]
                else "n/a",
            }
        )
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        for c in g["evaluation"]["criteria"]:
            with st.expander(
                f"[{c['criterion_id']}] {c['criterion']} — {c['status']} · {c['proposed_marks']:g}/{c['maximum_marks']:g}"
            ):
                st.caption(f"Match type: `{c['match_type']}`")
                st.write(c["reason"])
                for ev in c["student_evidence"]:
                    badge = "✅ verified" if ev.get("verified_in_answer") else "⚠️ UNVERIFIED"
                    st.markdown(
                        f"> {ev['quote']}\n>\n> — {badge} (segment: `{ev.get('segment_id')}`, page: `{ev.get('page_number')}`)"
                    )
    else:
        st.info("No criteria returned.")

    for cid in g["evaluation"].get("missing_concepts", []):
        st.error(f"Missing concept: {cid}")
    for con in g["evaluation"].get("contradictions", []):
        st.error(
            f"Contradiction on {con.get('criterion_id')}: supports {con.get('supporting_evidence')} vs "
            f"{con.get('contradicting_evidence')}"
        )

    # ------------------------------------------------------------- comparison
    st.markdown("**Blind Verification & Comparison (M15)**")
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Evaluator Total", comp["evaluator_total"])
    b2.metric("Verifier Total", comp["verifier_total"])
    b3.metric("Difference", comp["total_difference"])
    b4.metric("Agreement Rate", f"{comp['criterion_agreement_rate'] * 100:.0f}%")
    if comp.get("major_disagreement"):
        st.error("Major disagreement detected — routed to human review.")
        for d in comp.get("criterion_disagreements", []):
            st.write(f"- `{d['criterion_id']}`: evaluator {d['evaluator_marks']:g} vs verifier {d['verifier_marks']:g}")
    else:
        st.success("Evaluator and independent verifier agree criterion-by-criterion.")

    # ------------------------------------------------------------------- risk
    sig = risk.get("signals", {})
    nonzero = {k: v for k, v in sig.items() if v}
    st.markdown(f"**Risk Engine (M16)** — `{risk['risk_policy_version']}`, score `{risk['risk_score']:.2f}`")
    if nonzero:
        st.caption("Non-zero signals: " + ", ".join(f"{k}={v:.2f}" for k, v in nonzero.items()))
    st.caption(f"Hard validations passed: {risk.get('hard_validations_passed', True)}")

    with st.expander("⚙️ Versions / Provenance", expanded=False):
        st.json(g["versions"])
    st.download_button(
        "💾 Download GradedAnswer JSON",
        data=json.dumps(g, indent=2),
        file_name=f"graded_{g['submission_id']}_{g['question_id']}.json",
        mime="application/json",
    )


# ---------------------------------------------------------------------------
# Tab 2 — Jobs, queue & workers (Modules 17-18)
# ---------------------------------------------------------------------------
def _render_jobs_tab(controller: GradingJobsController) -> None:
    st.subheader("Embedded Worker Control")
    wc1, wc2 = st.columns([1, 2])
    worker_provider = wc1.radio(
        "Worker model",
        ["Real (Ollama — full pipeline)", "Mock (skips perception)"],
        key="worker_provider_radio",
    )
    checkpoint_db = wc2.text_input(
        "LangGraph checkpoint DB (SQLite path)",
        value="",
        placeholder="e.g. data/dev_checkpoints.sqlite — empty = in-memory checkpoints",
        key="checkpoint_db_input",
        help="Durable checkpoints let interrupted/review jobs resume across UI restarts.",
    )
    b1, b2 = st.columns(2)
    if controller.worker_running:
        if b1.button("⏹ Stop Worker", width="stretch"):
            controller.stop_worker()
            st.rerun()
    else:
        if b1.button("▶ Start Worker", type="primary", width="stretch"):
            real = worker_provider.startswith("Real")
            factory = lambda: build_grading_provider(not real, answer_text=SAMPLE_ANSWER_TEXT)  # noqa: E731
            hook = None if real else mock_state_hook(SAMPLE_ANSWER_TEXT)
            try:
                controller.start_worker(factory, checkpoint_db=checkpoint_db.strip() or None, initial_state_hook=hook)
            except Exception as e:
                st.error(f"Worker failed to start: {e}")
            st.rerun()
    caption = (
        "**Real mode** runs the complete LangGraph pipeline (PDF → perception → OCR → grading) against Ollama."
        if worker_provider.startswith("Real")
        else "**Mock mode** injects a pre-computed canonical answer so the workflow jumps straight to grading."
    )
    st.caption(caption)

    # ------------------------------------------------------------ submit form
    st.divider()
    st.subheader("Submit Evaluation Job")
    s1, s2 = st.columns([1, 2])
    default_sub = st.session_state.get("ui_submission_id") or f"SUB-{uuid.uuid4().hex[:6].upper()}"
    submission_id = s1.text_input("Submission ID (idempotency key)", value=default_sub, key="ui_submission_id")
    default_pdf = st.session_state.get("uploaded_pdf_path") or ""
    pdf_path = s2.text_input("PDF path (server-side)", value=default_pdf, key="ui_pdf_path")
    st.text_area(
        "Rubrics JSON (question_id → rubric)",
        value=json.dumps({"Q4": SAMPLE_RUBRIC}, indent=2),
        height=200,
        key="ui_job_rubrics",
    )
    if st.button("📤 Submit Job", type="primary"):
        try:
            rubrics = json.loads(st.session_state["ui_job_rubrics"])
            job, created = controller.submit(submission_id.strip(), pdf_path.strip(), rubrics)
            st.session_state["selected_job_id"] = job.job_id
            if created:
                st.success(f"Queued `{job.job_id}` for `{submission_id}` — poll the dashboard below.")
            else:
                st.warning(f"Duplicate submit ignored — active job `{job.job_id}` already exists (idempotency).")
        except Exception as e:
            st.error(f"Submit failed: {type(e).__name__}: {e}")

    # ----------------------------------------------------------- job dashboard
    st.divider()
    st.subheader("Job Dashboard")
    auto = st.toggle("Auto-refresh (1.5s)", value=False, key="jobs_autorefresh")
    if auto:
        time.sleep(1.5)
        st.rerun()

    rows = controller.job_summaries()
    if not rows:
        st.info("No jobs yet — start the worker and submit one above.")
        return

    st.dataframe(rows, width="stretch", hide_index=True)
    job_ids = [r["job_id"] for r in rows]
    default_idx = 0
    sel_prev = st.session_state.get("selected_job_id")
    if sel_prev in job_ids:
        default_idx = job_ids.index(sel_prev)
    selected = st.selectbox("Inspect job", job_ids, index=default_idx, key="selected_job_select")
    st.session_state["selected_job_id"] = selected
    _render_job_detail(controller, selected)


def _render_job_detail(controller: GradingJobsController, job_id: str) -> None:
    status = controller.status(job_id)
    job = controller.store.get_job(job_id)
    if not status or job is None:
        st.warning("Job disappeared from the store.")
        return

    st.markdown(f"#### `{job_id}` → submission `{status['submission_id']}`")
    j1, j2, j3, j4 = st.columns(4)
    j1.metric("Status", status["status"].replace("_", " ").title())
    j2.metric("Stage", status["stage"])
    j3.metric("Attempt", f"{status['attempt']}")
    j4.metric("Worker", status["worker_id"] or "—")
    st.progress(
        status["progress_percent"] / 100.0,
        text=f"{status['progress_percent']}% ({status['progress']['completed']}/{status['progress']['total']} stages)",
    )

    meta = (
        f"Created `{status['created_at']}` · Started `{status['started_at'] or '—'}` · "
        f"Heartbeat `{status['heartbeat_at'] or '—'}`"
    )
    st.caption(meta)

    if job.failures:
        with st.expander(f"⚠️ Failure history ({len(job.failures)})", expanded=status["status"] == "failed"):
            for f in job.failures:
                kind = "PERMANENT" if f.permanent else "retryable"
                st.write(
                    f"- `[{f.timestamp[:19]}]` **{f.exception_type}** at `{f.stage}` (attempt {f.attempt}, {kind}): {f.message}"
                )

    state = status["status"]
    if state == "waiting_for_review":
        _render_review_panel(controller, job)
    elif state == "completed":
        _render_completed_result(controller, job)
    elif state == "failed":
        st.error("💀 Job exhausted retries / hit a permanent error — retained in dead-letter state for inspection.")
    elif state == "retrying":
        st.info("🔁 Retry scheduled (bounded exponential backoff).")


def _render_review_panel(controller: GradingJobsController, job) -> None:
    st.info("🧑‍🏫 This job is **WAITING FOR HUMAN REVIEW** — apply teacher decisions to resume it.")
    decisions: dict[str, dict] = {}
    for qid, rubric in (job.rubrics or {}).items():
        max_m = float(rubric.get("maximum_marks", 10) or 10)
        with st.expander(f"{qid} (max {max_m:g})", expanded=True):
            approved = st.checkbox(f"Approve {qid}", value=True, key=f"ap_{job.job_id}_{qid}")
            final_marks = st.number_input(
                f"Final marks for {qid}",
                min_value=0.0,
                max_value=max_m,
                step=0.5,
                disabled=not approved,
                key=f"fm_{job.job_id}_{qid}",
            )
            notes = st.text_input("Reviewer notes", key=f"nt_{job.job_id}_{qid}")
            decisions[qid] = {
                "approved": approved,
                "final_marks": float(final_marks) if approved else None,
                "reviewer_notes": notes or None,
            }
    if st.button("✔ Apply Review & Resume Job", type="primary"):
        try:
            updated = controller.review(job.job_id, decisions)
            st.success(f"Job `{updated.job_id}` re-queued with teacher decisions.")
            time.sleep(0.5)
            st.rerun()
        except Exception as e:
            st.error(f"Review failed: {type(e).__name__}: {e}")


def _render_completed_result(controller: GradingJobsController, job) -> None:
    result = controller.result(job.submission_id)
    if not result:
        st.warning("No stored result found for this submission.")
        return
    st.success("✅ Job completed — final result summary (no raw chain-of-thought is ever exposed):")
    questions = result.get("questions", {})
    if questions:
        qrows = []
        for qid, q in questions.items():
            qrows.append(
                {
                    "Question": qid,
                    "Final Marks": f"{q['final_marks']:g}/{q['maximum_marks']:g}",
                    "Criteria Total": q["criteria_total"],
                    "Penalty": q["deterministic_penalty"],
                    "Auto Approve": q["auto_approve"],
                    "Risk": q["risk_level"],
                }
            )
        st.dataframe(qrows, width="stretch", hide_index=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Proposed Marks", result.get("total_proposed_marks", 0))
    c2.write(f"Auto approved: {result.get('auto_approved', [])}")
    c3.write(f"Human reviewed: {result.get('human_reviewed', [])}")
    with st.expander("Raw result summary JSON", expanded=False):
        st.json(result)
