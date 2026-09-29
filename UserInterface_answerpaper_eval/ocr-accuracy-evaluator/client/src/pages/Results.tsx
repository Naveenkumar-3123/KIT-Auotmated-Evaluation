/** STYLE: EvalAI results review — polished teacher-first score inspection with technical evidence deliberately kept secondary. */
import { useMemo, useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";
import { toast } from "sonner";
import { apiFetchObjectUrl } from "@/api/client";
import { listAssessments } from "@/api/assessments";
import { getAssessmentResults, getSubmissionResult, getSubmissionReviewRequest, submitReviewDecisions, type AssessmentResults, type ReviewDecision, type ReviewPendingQuestion, type SubmissionResultDetail } from "@/api/results";
import { getResolvedPolicies } from "@/api/policies";
import { fetchProcessingImageUrl, getProcessingDetails, type ProcessingDetails, type ProcessingImageKind, type ProcessingQuestion, type ProcessingRegion } from "@/api/processing";
import { AlertTriangle, ArrowLeft, ArrowRight, Award, BarChart3, BookOpenCheck, Braces, CheckCircle2, ChevronRight, Download, FileText, Filter, Layers3, Pencil, ScanLine, Search, UsersRound, X } from "lucide-react";
import { PreviewModal } from "@/components/evaluation/PreviewModal";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getClassSummary, resultStatusLabel, resultStatusTone, strictnessTone, type QuestionResult, type ResultClass, type ResultStatus, type StudentResult } from "@/components/results/results-data";

type StudentFilter = "all" | ResultStatus;
type SortKey = "roll" | "highest" | "lowest";

function StatusPill({ status }: { status: ResultStatus }) { return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${resultStatusTone[status]}`}><span className="h-1.5 w-1.5 rounded-full bg-current opacity-75" />{resultStatusLabel[status]}</span>; }

function MetricCard({ label, value, detail, icon: Icon, tone = "text-[#6d7fe7] bg-[#eef0ff]" }: { label: string; value: string; detail: string; icon: typeof UsersRound; tone?: string }) {
  const operationalDetail = detail === "Available in this demo" ? "Verified answer-sheet coverage" : detail === "Frontend mock score data" ? "Measured evaluation records" : detail === "Frontend mock result" ? "Recorded evaluation total" : detail;
  return <article className="results-evidence-surface rounded-[20px] border border-white/85 bg-white/72 p-4 shadow-[0_10px_24px_rgba(60,70,135,0.06)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.05]"><div className="flex items-start justify-between gap-3"><div><p className="type-overline text-slate-400 dark:text-slate-500">{label}</p><p className="font-mono mt-2 text-[22px] font-semibold leading-none tracking-[-0.06em] text-[#171827] dark:text-white">{value}</p><p className="mt-2 text-[12px] font-medium text-slate-500 dark:text-slate-400">{operationalDetail}</p></div><span className={`flex h-9 w-9 items-center justify-center rounded-xl ${tone}`}><Icon className="h-[17px] w-[17px]" /></span></div></article>;
}

function ResultsHome({ onSelect, classes }: { onSelect: (resultClass: ResultClass) => void; classes: ResultClass[] }) {
  return <div className="space-y-5"><section className="ocr-focus-frame relative overflow-hidden rounded-[26px] border border-white/85 bg-[linear-gradient(108deg,rgba(255,255,255,0.93),rgba(249,251,255,0.7)_56%,rgba(255,253,241,0.7))] p-6 shadow-[0_18px_42px_rgba(60,70,135,0.09)] sm:p-8"><div className="max-w-[720px]"><p className="type-overline text-[#7182ef]">Evaluation results</p><h1 className="type-page-title mt-3 text-[#171827] dark:text-white">View assessment results.</h1><p className="type-body mt-3 max-w-[650px] text-slate-600 dark:text-slate-300">Choose a class to review student scores, question-level evaluation, and supporting evidence.</p><span className="mt-5 block h-px w-[220px] bg-[linear-gradient(90deg,#7788ff,transparent)] opacity-70" /></div></section><section><div className="mb-4 flex items-end justify-between gap-4"><div><p className="type-overline text-[#7182ef]">Completed assessments</p><h2 className="type-section-title mt-1 text-[#171827] dark:text-white">Ready for teacher review</h2></div><p className="type-metadata text-slate-500 dark:text-slate-400">{classes.length} result sets available</p></div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{classes.map((resultClass) => { const summary = getClassSummary(resultClass); return <button key={resultClass.id} type="button" onClick={() => onSelect(resultClass)} className="group relative min-h-[222px] overflow-hidden rounded-[23px] border border-white/85 bg-white/72 p-5 text-left shadow-[0_13px_28px_rgba(60,70,135,0.08)] backdrop-blur-xl transition-all duration-200 hover:-translate-y-1 hover:border-[#cbd4ff] hover:shadow-[0_20px_36px_rgba(60,70,135,0.14)] focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/[0.05]"><div className="flex items-start justify-between"><span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#eef1ff] text-[#687ae5] dark:bg-[#8797ff]/15 dark:text-[#aeb7ff]"><BookOpenCheck className="h-5 w-5" /></span><span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${resultClass.completionStatus === "complete" ? "bg-[#e8f7ef] text-[#4f8f70]" : "bg-[#fff2df] text-[#b57626]"}`}>{resultClass.completionStatus === "complete" ? "Evaluation complete" : "Partially complete"}</span></div><p className="type-card-title mt-6 text-[#171827] dark:text-white">{resultClass.className}</p><p className="mt-1 text-[14px] font-medium text-slate-600 dark:text-slate-300">{resultClass.subject}</p><div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[12px] font-medium text-slate-500 dark:text-slate-400"><span>{summary.evaluated} students evaluated</span><span>{resultClass.totalMarks} marks</span></div><span className="type-button absolute bottom-5 right-5 inline-flex items-center gap-1 text-[#6477e4]">View Results <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" /></span></button>; })}</div></section></div>;
}

function ClassResults({ resultClass, onBack, onStudent }: { resultClass: ResultClass; onBack: () => void; onStudent: (student: StudentResult) => void }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StudentFilter>("all");
  const [sort, setSort] = useState<SortKey>("roll");
  const summary = getClassSummary(resultClass);
  const students = useMemo(() => resultClass.students.filter((student) => student.rollNumber.toLowerCase().includes(query.toLowerCase()) && (filter === "all" || student.status === filter)).sort((left, right) => sort === "highest" ? right.totalScore - left.totalScore : sort === "lowest" ? left.totalScore - right.totalScore : left.rollNumber.localeCompare(right.rollNumber)), [filter, query, resultClass.students, sort]);
  return <div className="space-y-5"><section className="rounded-[26px] border border-white/85 bg-white/72 p-6 shadow-[0_16px_36px_rgba(60,70,135,0.08)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.05] sm:p-7"><button type="button" onClick={onBack} className="type-button inline-flex items-center gap-1.5 text-[#6477e4] hover:text-[#4358ca] focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-[#7788ff]"><ArrowLeft className="h-4 w-4" />All Results</button><div className="mt-5 flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div><p className="type-overline text-[#7182ef]">Assessment results</p><h1 className="type-page-title mt-2 text-[#171827] dark:text-white">{resultClass.className}</h1><p className="mt-1 text-[15px] font-medium text-slate-600 dark:text-slate-300">{resultClass.subject}</p><p className="mt-3 text-[13px] font-medium text-slate-500 dark:text-slate-400">{summary.evaluated} student answer sheets evaluated</p></div><button type="button" onClick={() => toast("Export preparation only", { description: "CSV, Excel, and PDF export will be connected to the results service later." })} className="type-button inline-flex items-center justify-center gap-2 rounded-full border border-[#dce2ff] bg-white/75 px-4 py-2.5 text-[#5366d4] shadow-sm hover:bg-white dark:border-white/10 dark:bg-white/[0.06] dark:text-[#b8c0ff]"><Download className="h-4 w-4" />Export Results</button></div></section><section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Students evaluated" value={`${summary.evaluated} / ${summary.total}`} detail="Available in this demo" icon={UsersRound} /><MetricCard label="Class average" value={`${summary.average.toFixed(1)} / 100`} detail="Frontend mock score data" icon={BarChart3} tone="text-[#6a7ee1] bg-[#eef0ff]" /><MetricCard label="Highest score" value={`${summary.highest} / 100`} detail="Across evaluated students" icon={Award} tone="text-[#a3742f] bg-[#fff4e4]" /><MetricCard label="Needs review" value={String(summary.reviewCount)} detail="Teacher attention requested" icon={AlertTriangle} tone="text-[#b57626] bg-[#fff2df]" /></section><section className="rounded-[26px] border border-white/85 bg-white/72 shadow-[0_16px_36px_rgba(60,70,135,0.08)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.05]"><div className="flex flex-col gap-3 border-b border-[#edf0ff] p-4 dark:border-white/10 md:flex-row md:items-center md:justify-between"><label className="relative block md:w-[290px]"><span className="sr-only">Search roll number</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search roll number..." className="h-10 w-full rounded-xl border border-[#e4e8ff] bg-white/80 pl-10 pr-3 text-[13px] font-medium text-[#171827] outline-none transition focus:border-[#aab6ff] focus:ring-2 focus:ring-[#b6c0ff]/30 dark:border-white/10 dark:bg-white/[0.05] dark:text-white" /></label><div className="flex flex-wrap gap-2"><label className="relative"><span className="sr-only">Filter results</span><Filter className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" /><select value={filter} onChange={(event) => setFilter(event.target.value as StudentFilter)} className="h-10 appearance-none rounded-xl border border-[#e4e8ff] bg-white/80 py-0 pl-8 pr-8 text-[12px] font-semibold text-slate-600 outline-none focus:border-[#aab6ff] dark:border-white/10 dark:bg-white/[0.05] dark:text-slate-300"><option value="all">All results</option><option value="completed">Completed</option><option value="needs-review">Needs Review</option><option value="teacher-modified">Teacher Modified</option></select></label><select aria-label="Sort results" value={sort} onChange={(event) => setSort(event.target.value as SortKey)} className="h-10 rounded-xl border border-[#e4e8ff] bg-white/80 px-3 text-[12px] font-semibold text-slate-600 outline-none focus:border-[#aab6ff] dark:border-white/10 dark:bg-white/[0.05] dark:text-slate-300"><option value="roll">Roll Number</option><option value="highest">Highest Score</option><option value="lowest">Lowest Score</option></select></div></div><div className="hidden md:block"><div className="grid grid-cols-[1.35fr_.8fr_.72fr_1fr_.5fr] gap-4 border-b border-[#edf0ff] px-5 py-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400 dark:border-white/10"><span>Roll number</span><span>Score</span><span>Percentage</span><span>Status</span><span className="text-right">Action</span></div>{students.length ? students.map((student) => <div key={student.id} className="grid grid-cols-[1.35fr_.8fr_.72fr_1fr_.5fr] items-center gap-4 border-b border-[#f0f2ff] px-5 py-4 last:border-b-0 dark:border-white/[0.06]"><button type="button" onClick={() => onStudent(student)} className="text-left text-[14px] font-semibold text-[#171827] hover:text-[#586ae0] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:text-white">{student.rollNumber}</button><span className="text-[13px] font-semibold text-[#171827] dark:text-white">{student.totalScore} / {student.maxScore}</span><span className="text-[13px] font-medium text-slate-500 dark:text-slate-400">{student.totalScore}%</span><span><StatusPill status={student.status} /></span><button type="button" onClick={() => onStudent(student)} className="type-button justify-self-end text-[#6477e4] hover:text-[#4358ca] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff]">View</button></div>) : <EmptyStudentSearch />}</div><div className="space-y-3 p-4 md:hidden">{students.length ? students.map((student) => <article key={student.id} className="rounded-2xl border border-[#e8ebff] bg-white/85 p-4 dark:border-white/10 dark:bg-white/[0.04]"><div className="flex items-start justify-between gap-3"><div><p className="text-[14px] font-semibold text-[#171827] dark:text-white">{student.rollNumber}</p><p className="mt-1 text-[13px] font-medium text-slate-500 dark:text-slate-400">Score {student.totalScore} / {student.maxScore} · {student.totalScore}%</p></div><StatusPill status={student.status} /></div><button type="button" onClick={() => onStudent(student)} className="type-button mt-4 inline-flex items-center gap-1 text-[#6477e4]">View Result <ArrowRight className="h-3.5 w-3.5" /></button></article>) : <EmptyStudentSearch />}</div></section></div>;
}

function EmptyStudentSearch() { return <div className="p-8 text-center"><p className="text-[14px] font-semibold text-[#171827] dark:text-white">No matching students</p><p className="mt-1 text-[13px] text-slate-500 dark:text-slate-400">Try another roll number or result status.</p></div>; }

function StrictnessPill({ strictness }: { strictness: QuestionResult["strictness"] }) { return <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${strictnessTone[strictness]}`}>Strictness: {strictness}</span>; }

/** Teacher review panel: approve AI-proposed marks when a paper is waiting_for_review. */
function ReviewPanel({ assessmentId, submissionId, onResolved, onPendingChange }: { assessmentId: string; submissionId: string; onResolved: () => void; onPendingChange?: (pending: Record<string, ReviewPendingQuestion> | null) => void }) {
  const [pending, setPending] = useState<Record<string, ReviewPendingQuestion> | null>(null);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const resolvedRef = useRef(false);

  useEffect(() => {
    let alive = true;
    let timer = 0;
    const load = () => {
      getSubmissionReviewRequest(assessmentId, submissionId)
        .then((data) => {
          if (alive) {
            const awaiting = data.review_request?.awaiting_review ?? {};
            setPending(awaiting);
            onPendingChange?.(awaiting);
          }
        })
        .catch(() => {
          // The endpoint 404s once the job is no longer active (completed or
          // failed) — the review loop is over, refresh the read-model.
          if (alive && !resolvedRef.current) {
            resolvedRef.current = true;
            setPending(null);
            onPendingChange?.(null);
            onResolved();
          }
        });
    };
    load();
    timer = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [assessmentId, submissionId, onResolved]);

  const entries = Object.entries(pending ?? {});
  if (!entries.length) return null;

  const proposedTotal = entries.reduce((sum, [, q]) => sum + (Number(q.proposed_marks) || 0), 0);
  const proposedMax = entries.reduce((sum, [, q]) => sum + (Number(q.maximum_marks) || 0), 0);
  const decisionFor = (qid: string, q: ReviewPendingQuestion): ReviewDecision => {
    const raw = overrides[qid]?.trim();
    const value = raw ? Number.parseFloat(raw) : Number.NaN;
    return Number.isFinite(value) ? { approved: true, final_marks: value } : { approved: true, final_marks: Number(q.proposed_marks ?? 0) };
  };
  const submit = async (decisions?: Record<string, ReviewDecision>) => {
    setBusy(true);
    try {
      const payload = decisions ?? Object.fromEntries(entries.map(([qid, q]) => [qid, decisionFor(qid, q)]));
      await submitReviewDecisions(assessmentId, submissionId, payload);
      toast.success("Review submitted — finalising marks…");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not submit the review.");
    } finally {
      setBusy(false);
    }
  };
  const acceptAll = () => setAccepted(Object.fromEntries(entries.map(([qid]) => [qid, true])));

  return <section className="rounded-[22px] border border-[#f3ddb8] bg-[#fff8ec] p-5 shadow-[0_10px_24px_rgba(150,110,40,0.08)] dark:border-[#b57626]/30 dark:bg-[#b57626]/10"><div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start"><div><p className="type-overline text-[#b57626]">Teacher review required</p><h2 className="type-section-title mt-1 text-[#171827] dark:text-white">Approve AI-proposed marks</h2><p className="type-support mt-1 max-w-[640px] text-slate-600 dark:text-slate-300">Question numbers on this scan could not be read confidently, so answers were mapped by header anchors and content. Accept the AI marks as-is, or type a correction — your decision is final either way.</p></div><div className="flex shrink-0 flex-col items-start gap-2 lg:items-end"><p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#b57626]">AI proposes (pending questions)</p><p className="font-mono text-[26px] font-semibold leading-none tracking-[-0.06em] text-[#171827] dark:text-white">{proposedTotal.toFixed(1)} <span className="text-[15px] text-slate-400">/ {proposedMax.toFixed(0)}</span></p><div className="flex flex-wrap gap-2"><button type="button" onClick={() => { acceptAll(); void submit(Object.fromEntries(entries.map(([qid, q]) => [qid, { approved: true, final_marks: Number(q.proposed_marks ?? 0) }]))); }} disabled={busy} className="type-button rounded-full border border-[#e7d5a8] bg-white/85 px-4 py-2 text-[#8a6420] shadow-sm hover:bg-white disabled:opacity-60 dark:border-white/10 dark:bg-white/[0.06] dark:text-[#e8d9ae]">Accept all AI marks</button><button type="button" onClick={() => void submit()} disabled={busy} className="type-button rounded-full bg-[#171b32] px-4 py-2 text-white shadow-sm hover:bg-[#24294a] disabled:opacity-60 dark:bg-[#9aa8ff] dark:text-[#151827]">{busy ? "Submitting…" : "Approve & finalise"}</button></div></div></div><div className="mt-4 space-y-2">{entries.map(([qid, q]) => { const isAccepted = Boolean(accepted[qid]); return <div key={qid} className="flex flex-col gap-3 rounded-[16px] border border-white/85 bg-white/80 px-4 py-3 dark:border-white/10 dark:bg-white/[0.06] sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="text-[13px] font-semibold text-[#171827] dark:text-white">Question {qid.replace(/^Q/i, "")}</p><p className="font-mono text-[13px] font-semibold text-[#8a6420] dark:text-[#e8d9ae]">AI proposes {q.proposed_marks ?? 0} / {q.maximum_marks ?? 0}</p>{isAccepted && <span className="inline-flex items-center gap-1 rounded-full bg-[#e8f7ef] px-2 py-0.5 text-[11px] font-semibold text-[#4f8f70]"><CheckCircle2 className="h-3 w-3" /> Accepted</span>}</div><p className="mt-1 line-clamp-2 text-[12px] font-medium text-slate-500 dark:text-slate-400">{q.feedback || (q.reasons ?? []).join(" · ") || "Mapped without a confident question number — flagged for verification."}</p></div><div className="flex shrink-0 items-center gap-2"><button type="button" onClick={() => setAccepted((prev) => ({ ...prev, [qid]: !prev[qid] }))} className={`type-button rounded-full px-3 py-2 text-[12px] font-semibold ${isAccepted ? "bg-[#e8f7ef] text-[#4f8f70]" : "border border-[#e7d5a8] bg-white/85 text-[#8a6420] hover:bg-white dark:border-white/10 dark:bg-white/[0.06] dark:text-[#e8d9ae]"}`}>{isAccepted ? "Accepted" : "Accept"}</button><input type="number" min={0} max={q.maximum_marks ?? undefined} step="0.5" value={overrides[qid] ?? ""} onChange={(event) => setOverrides((prev) => ({ ...prev, [qid]: event.target.value }))} placeholder="Override" className="w-full rounded-xl border border-[#e4e8ff] bg-white px-3 py-2 text-[13px] text-[#171827] outline-none focus:border-[#7788ff] sm:w-[120px] dark:border-white/10 dark:bg-white/10 dark:text-white" /></div></div>; })}</div></section>;
}

function StudentResults({ resultClass, student, onBack, onReviewResolved }: { resultClass: ResultClass; student: StudentResult; onBack: () => void; onReviewResolved: () => void }) {
  const [selectedQuestion, setSelectedQuestion] = useState<QuestionResult | null>(null);
  const [showEvidence, setShowEvidence] = useState(false);
  const [showAnswerSheet, setShowAnswerSheet] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pendingReview, setPendingReview] = useState<Record<string, ReviewPendingQuestion> | null>(null);
  const [strictnessByQ, setStrictnessByQ] = useState<Record<number, QuestionResult["strictness"]>>({});
  // Resolved policies drive the strictness pill for AI-proposed (pending) questions,
  // which have no read-model row yet.
  useEffect(() => {
    let cancelled = false;
    getResolvedPolicies(resultClass.id)
      .then((payload) => {
        if (cancelled) return;
        const map: Record<number, QuestionResult["strictness"]> = {};
        for (const p of payload.policies ?? []) {
          map[p.question_number] = normalizeStrictness(p.strictness_level);
        }
        setStrictnessByQ(map);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [resultClass.id]);
  const loadAnswerSheet = () => {
    if (pdfUrl || pdfLoading) return;
    setPdfLoading(true);
    setPdfError(null);
    apiFetchObjectUrl(`/assessments/submissions/${student.id}/pdf`)
      .then((url) => setPdfUrl(url))
      .catch((error: unknown) => setPdfError(error instanceof Error ? error.message : "Could not load the answer sheet."))
      .finally(() => setPdfLoading(false));
  };
  const isAwaitingReview = student.status === "needs-review";
  const pendingByQid = useMemo(() => {
    const map: Record<string, ReviewPendingQuestion> = {};
    for (const [qid, q] of Object.entries(pendingReview ?? {})) map[qid.replace(/^Q/i, "")] = q;
    return map;
  }, [pendingReview]);
  // While the paper waits for review the recorded total is 0 — show what the
  // AI proposes instead: real marks for auto-approved questions + proposals.
  // Pending questions have NO read-model rows yet, so merge them in here.
  const mergedQuestionResults = useMemo(() => {
    const rows: QuestionResult[] = student.questionResults.map((q) => {
      const pendingQ = pendingByQid[String(q.number)];
      return pendingQ ? { ...q, marksAwarded: Number(pendingQ.proposed_marks) || 0 } : q;
    });
    for (const [qid, q] of Object.entries(pendingByQid)) {
      const num = Number(qid.replace(/^Q/i, "")) || 0;
      if (!rows.some((row) => row.number === num)) {
        rows.push({
          id: `${student.id}-q${qid}`,
          number: num,
          questionText: "Awaiting your approval — AI-proposed marks.",
          marksAwarded: Number(q.proposed_marks) || 0,
          maxMarks: Number(q.maximum_marks) || 0,
          strictness: strictnessByQ[num] ?? "moderate",
          studentAnswer: "",
          expectedPoints: [],
          evaluation: q.feedback || (q.reasons ?? []).join(" · "),
          needsReview: true,
        });
      }
    }
    return rows.sort((a, b) => a.number - b.number);
  }, [student.questionResults, student.id, pendingByQid, strictnessByQ]);
  const displayTotal = mergedQuestionResults.reduce((sum, q) => sum + q.marksAwarded, 0);
  const reviewedQuestions = mergedQuestionResults.filter((question) => question.needsReview).length;
  return <div className="space-y-5"><section className="rounded-[26px] border border-white/85 bg-[linear-gradient(108deg,rgba(255,255,255,0.93),rgba(249,251,255,0.7)_56%,rgba(255,253,241,0.7))] p-6 shadow-[0_18px_42px_rgba(60,70,135,0.09)] sm:p-7"><button type="button" onClick={onBack} className="type-button inline-flex items-center gap-1.5 text-[#6477e4] hover:text-[#4358ca] focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-[#7788ff]"><ArrowLeft className="h-4 w-4" />{resultClass.className} Results</button><div className="mt-5 flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div><p className="type-overline text-[#7182ef]">Student result</p><h1 className="type-page-title mt-2 text-[#171827] dark:text-white">{student.rollNumber}</h1><p className="mt-1 text-[15px] font-medium text-slate-600 dark:text-slate-300">{resultClass.subject} · {resultClass.className}</p><div className="mt-3"><StatusPill status={student.status} /></div></div><div className="rounded-[20px] border border-[#dce2ff] bg-white/85 px-5 py-4 text-left shadow-sm dark:border-white/10 dark:bg-white/[0.05] sm:text-right"><p className="type-overline text-[#7484e6]">Total score</p><p className="mt-2 text-[31px] font-semibold leading-none tracking-[-0.07em] text-[#171827] dark:text-white">{displayTotal} <span className="text-[17px] tracking-[-0.03em] text-slate-400">/ {student.maxScore}</span></p></div></div></section><section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label={isAwaitingReview ? "AI-proposed total" : "Total score"} value={`${displayTotal} / ${student.maxScore}`} detail={isAwaitingReview ? "Awaiting your review approval" : "Recorded evaluation total"} icon={Award} /><MetricCard label="Questions" value={`${mergedQuestionResults.length} / ${mergedQuestionResults.length}`} detail="Evaluation complete" icon={CheckCircle2} tone="text-[#4f8f70] bg-[#e8f7ef]" /><MetricCard label="Review required" value={String(reviewedQuestions)} detail={reviewedQuestions ? "Check marked question" : "No question flags"} icon={AlertTriangle} tone={reviewedQuestions ? "text-[#b57626] bg-[#fff2df]" : "text-[#4f8f70] bg-[#e8f7ef]"} /><MetricCard label="Evaluation status" value={resultStatusLabel[student.status]} detail="Teacher-facing state" icon={BookOpenCheck} tone="text-[#6a7ee1] bg-[#eef0ff]" /></section>{student.status === "needs-review" && <ReviewPanel assessmentId={resultClass.id} submissionId={student.id} onResolved={onReviewResolved} onPendingChange={setPendingReview} />}<section className="flex justify-end"><button type="button" onClick={() => setShowEvidence(true)} className="type-button inline-flex items-center gap-2 rounded-full border border-[#cfd6ff] bg-white px-4 py-2 text-[13px] font-semibold text-[#5366d4] shadow-sm hover:bg-[#fdfdff] dark:border-white/10 dark:bg-white/[0.06] dark:text-[#b8c0ff]"><ScanLine className="h-4 w-4" />View Processing Details</button></section><section><div className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><p className="type-overline text-[#7182ef]">Question-level result</p><h2 className="type-section-title mt-1 text-[#171827] dark:text-white">Marks and evaluation explanation</h2></div><p className="type-support text-slate-500 dark:text-slate-400">Select a question to inspect the full answer and marking key.</p></div><div className="space-y-3">{mergedQuestionResults.map((question) => <article key={question.id} className="rounded-[22px] border border-white/85 bg-white/72 p-5 shadow-[0_10px_24px_rgba(60,70,135,0.06)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.05]"><div className="flex flex-col justify-between gap-4 sm:flex-row"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="type-overline text-[#7182ef]">Question {question.number}</p><StrictnessPill strictness={question.strictness} />{question.needsReview && <span className="inline-flex rounded-full bg-[#fff2df] px-2.5 py-1 text-[11px] font-semibold text-[#b57626]">Needs Review</span>}</div><h3 className="mt-3 text-[15px] font-semibold tracking-[-0.022em] text-[#171827] dark:text-white">{question.questionText}</h3><p className="mt-2 max-w-[760px] text-[13px] font-medium leading-5 text-slate-600 dark:text-slate-300">{question.evaluation}</p></div><div className="flex shrink-0 items-center justify-between gap-4 sm:flex-col sm:items-end">{(() => { const pendingQ = pendingByQid[String(question.number)]; return pendingQ ? (<><p className="text-[24px] font-semibold leading-none tracking-[-0.06em] text-[#b57626]">{pendingQ.proposed_marks ?? 0} <span className="text-[15px] tracking-[-0.02em] text-slate-400">/ {question.maxMarks}</span></p><span className="rounded-full bg-[#fff2df] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-[#b57626]">AI proposed</span></>) : (<p className="text-[24px] font-semibold leading-none tracking-[-0.06em] text-[#171827] dark:text-white">{question.marksAwarded} <span className="text-[15px] tracking-[-0.02em] text-slate-400">/ {question.maxMarks}</span></p>); })()}<button type="button" onClick={() => setSelectedQuestion(question)} className="type-button inline-flex items-center gap-1 text-[#6477e4] hover:text-[#4358ca] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff]">View Details <ChevronRight className="h-3.5 w-3.5" /></button></div></div></article>)}</div></section><section className="flex flex-col gap-3 rounded-[22px] border border-white/85 bg-white/65 p-4 shadow-[0_10px_24px_rgba(60,70,135,0.05)] backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between dark:border-white/10 dark:bg-white/[0.04]"><div><p className="text-[14px] font-semibold text-[#171827] dark:text-white">Document and evidence</p><p className="mt-1 text-[12px] font-medium text-slate-500 dark:text-slate-400">Answer-sheet preview and processing details remain secondary to the marking decision.</p></div><div className="flex flex-wrap gap-2"><button type="button" onClick={() => { setShowAnswerSheet(true); loadAnswerSheet(); }} className="type-button inline-flex items-center gap-2 rounded-full border border-[#dce2ff] bg-white/75 px-4 py-2.5 text-[#5366d4] shadow-sm hover:bg-white dark:border-white/10 dark:bg-white/[0.06] dark:text-[#b8c0ff]"><FileText className="h-4 w-4" />View Answer Sheet</button><button type="button" onClick={() => setShowEvidence(true)} className="type-button inline-flex items-center gap-2 rounded-full bg-[#171b32] px-4 py-2.5 text-white shadow-sm hover:bg-[#24294a] dark:bg-[#9aa8ff] dark:text-[#151827]"><Layers3 className="h-4 w-4" />View Processing Details</button></div></section><PreviewModal open={showAnswerSheet} onClose={() => setShowAnswerSheet(false)} title={`${student.rollNumber} answer sheet`} subtitle={pdfError ?? (pdfUrl ? "Original uploaded answer sheet." : pdfLoading ? "Loading answer sheet…" : "No answer-sheet file available.")} fileName={`${student.rollNumber}.pdf`} contentUrl={pdfUrl} /><QuestionDetailDrawer question={selectedQuestion} onClose={() => setSelectedQuestion(null)} /><TechnicalEvidenceDrawer open={showEvidence} student={student} onClose={() => setShowEvidence(false)} /></div>;
}

function QuestionDetailDrawer({ question, onClose }: { question: QuestionResult | null; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draftMark, setDraftMark] = useState("");
  const [note, setNote] = useState("");
  if (!question) return null;
  const saveDraft = () => { toast("Mark change prepared", { description: "This frontend prototype does not persist teacher overrides yet." }); setEditing(false); setNote(""); };
  return <div className="fixed inset-0 z-50"><button type="button" onClick={onClose} aria-label="Close question details" className="absolute inset-0 bg-[#151827]/35 backdrop-blur-sm" /><aside role="dialog" aria-modal="true" aria-label={`Question ${question.number} evaluation details`} className="absolute inset-y-0 right-0 flex w-full max-w-[680px] flex-col overflow-y-auto border-l border-white/70 bg-[#fbfcff] p-5 shadow-[-24px_0_70px_rgba(30,35,80,0.2)] dark:border-white/10 dark:bg-[#202437] sm:p-7"><div className="flex items-start justify-between gap-4"><div><p className="type-overline text-[#7484e6]">Question {question.number}</p><h2 className="type-page-title mt-2 text-[#171827] dark:text-white">Evaluation details</h2><p className="mt-2 text-[13px] font-medium text-slate-500 dark:text-slate-400">Inspect the answer, key points, and allocated marks.</p></div><button type="button" onClick={onClose} className="rounded-full border border-slate-200 bg-white p-2 text-slate-500 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/5 dark:text-slate-300"><X className="h-4 w-4" /></button></div><div className="mt-6 grid gap-3 sm:grid-cols-3"><MetricCard label="Student score" value={`${question.marksAwarded} / ${question.maxMarks}`} detail="Awarded marks" icon={Award} /><article className="rounded-[20px] border border-white/85 bg-white/72 p-4 shadow-[0_10px_24px_rgba(60,70,135,0.06)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.05]"><p className="type-overline text-slate-400">Strictness</p><div className="mt-3"><StrictnessPill strictness={question.strictness} /></div><p className="mt-3 text-[12px] font-medium text-slate-500 dark:text-slate-400">Configured marking rule</p></article><article className="rounded-[20px] border border-white/85 bg-white/72 p-4 shadow-[0_10px_24px_rgba(60,70,135,0.06)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.05]"><p className="type-overline text-slate-400">Review state</p><p className="mt-3 text-[14px] font-semibold text-[#171827] dark:text-white">{question.needsReview ? "Needs Review" : "Ready"}</p><p className="mt-3 text-[12px] font-medium text-slate-500 dark:text-slate-400">Teacher confirmation available</p></article></div><DetailSection label="Question" body={question.questionText} /><DetailSection label="Student answer" body={question.studentAnswer} /><section className="mt-5 rounded-[20px] border border-white/85 bg-white/72 p-5 shadow-[0_10px_24px_rgba(60,70,135,0.06)] dark:border-white/10 dark:bg-white/[0.05]"><p className="type-overline text-[#7484e6]">Expected answer / key points</p><ul className="mt-3 space-y-2">{question.expectedPoints.map((point) => <li key={point} className="flex gap-2 text-[13px] font-medium leading-5 text-slate-600 dark:text-slate-300"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#5c9c77]" />{point}</li>)}</ul></section><DetailSection label="AI evaluation" body={question.evaluation} /><section className="mt-5 rounded-[20px] border border-[#dce2ff] bg-[#f8f9ff] p-5 dark:border-white/10 dark:bg-white/[0.04]"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[14px] font-semibold text-[#171827] dark:text-white">Teacher mark override</p><p className="mt-1 text-[12px] font-medium text-slate-500 dark:text-slate-400">Prepare a corrected mark. Saving is intentionally local to this prototype.</p></div><button type="button" onClick={() => { setEditing((value) => !value); setDraftMark(String(question.marksAwarded)); }} className="type-button inline-flex items-center gap-2 rounded-full border border-[#cfd6ff] bg-white px-3.5 py-2 text-[#5366d4] hover:bg-[#fdfdff] dark:border-white/10 dark:bg-white/[0.06] dark:text-[#b8c0ff]"><Pencil className="h-3.5 w-3.5" />Edit Mark</button></div>{editing && <div className="mt-4 grid gap-3 border-t border-[#e4e8ff] pt-4 dark:border-white/10"><label className="text-[12px] font-semibold text-[#171827] dark:text-white">Awarded marks <span className="font-medium text-slate-400">/ {question.maxMarks}</span><input value={draftMark} onChange={(event) => setDraftMark(event.target.value)} inputMode="numeric" className="mt-2 block h-10 w-full rounded-xl border border-[#dfe4ff] bg-white px-3 text-[13px] outline-none focus:border-[#aab6ff] focus:ring-2 focus:ring-[#b6c0ff]/30 dark:border-white/10 dark:bg-white/[0.05]" /></label><label className="text-[12px] font-semibold text-[#171827] dark:text-white">Reason for change <span className="font-medium text-slate-400">optional</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add a teacher note..." className="mt-2 min-h-[82px] w-full rounded-xl border border-[#dfe4ff] bg-white p-3 text-[13px] outline-none focus:border-[#aab6ff] focus:ring-2 focus:ring-[#b6c0ff]/30 dark:border-white/10 dark:bg-white/[0.05]" /></label><div className="flex justify-end gap-2"><button type="button" onClick={() => setEditing(false)} className="type-button rounded-full px-3.5 py-2 text-slate-500 hover:bg-white">Cancel</button><button type="button" onClick={saveDraft} className="type-button rounded-full bg-[#171b32] px-4 py-2 text-white dark:bg-[#9aa8ff] dark:text-[#151827]">Save Draft</button></div></div>}</section></aside></div>;
}

function DetailSection({ label, body }: { label: string; body: string }) { return <section className="mt-5 rounded-[20px] border border-white/85 bg-white/72 p-5 shadow-[0_10px_24px_rgba(60,70,135,0.06)] dark:border-white/10 dark:bg-white/[0.05]"><p className="type-overline text-[#7484e6]">{label}</p><p className="mt-3 text-[13px] font-medium leading-6 text-slate-600 dark:text-slate-300">{body}</p></section>; }

/** Real processing evidence: pipeline artifacts + grading telemetry. */
function ArtifactGallery({ submissionId, kind, files, emptyTitle, emptyDescription }: { submissionId: string; kind: ProcessingImageKind; files: string[]; emptyTitle: string; emptyDescription: string }) {
  const [urls, setUrls] = useState<Array<{ file: string; url: string }>>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (files.length === 0) return;
    let cancelled = false;
    const created: Array<{ file: string; url: string }> = [];
    (async () => {
      for (const file of files) {
        try {
          const url = await fetchProcessingImageUrl(submissionId, kind, file);
          if (cancelled) {
            URL.revokeObjectURL(url);
            continue;
          }
          created.push({ file, url });
          setUrls([...created]);
        } catch {
          if (!cancelled) setFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
      for (const item of created) URL.revokeObjectURL(item.url);
    };
  }, [submissionId, kind, files]);
  if (files.length === 0) {
    return <EvidencePlaceholder icon={kind === "segments" ? Layers3 : FileText} title={emptyTitle} description={emptyDescription} />;
  }
  return (
    <div className="space-y-3">
      {urls.map(({ file, url }) => (
        <figure key={file} className="overflow-hidden rounded-[18px] border border-[#e4e8ff] bg-white shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
          <img src={url} alt={file} className="max-h-[540px] w-full bg-white object-contain" loading="lazy" />
          <figcaption className="border-t border-[#eef0ff] px-3 py-2 font-mono text-[11px] text-slate-500 dark:border-white/10 dark:text-slate-400">{file}</figcaption>
        </figure>
      ))}
      {urls.length < files.length && !failed && <p className="type-support text-slate-400">Loading artifacts…</p>}
    </div>
  );
}


function EvaluationEvidence({ questions }: { questions: Record<string, ProcessingQuestion> }) {
  const entries = Object.entries(questions).sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }));
  if (entries.length === 0) {
    return <EvidencePlaceholder icon={Braces} title="No grading data recorded" description="Grading telemetry appears here after the evaluation pipeline produces marks for this paper." />;
  }
  return (
    <div className="space-y-2">
      {entries.map(([qid, q]) => (
        <article key={qid} className="rounded-[18px] border border-[#e4e8ff] bg-white p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[13px] font-semibold text-[#171827] dark:text-white">{qid}</p>
            <span className="rounded-full bg-[#eef0ff] px-2 py-0.5 text-[11px] font-semibold text-[#6374da]">{q.proposed_marks ?? "—"} / {q.maximum_marks ?? "—"} marks</span>
            {q.risk_level && <span className="rounded-full bg-[#fff2df] px-2 py-0.5 text-[11px] font-medium text-[#b57626]">risk: {q.risk_level}</span>}
            {q.teacher_decision && <span className="rounded-full bg-[#e8f7ef] px-2 py-0.5 text-[11px] font-medium text-[#4f8f70]">teacher: {q.teacher_decision.approved ? "approved" : "pending"}{q.teacher_decision.final_marks != null ? ` · ${q.teacher_decision.final_marks}` : ""}</span>}
          </div>
          {q.feedback && <p className="mt-2 text-[13px] leading-5 text-slate-600 dark:text-slate-300">{q.feedback}</p>}
          {(q.reasons ?? []).length > 0 && <p className="mt-1 text-[12px] font-medium text-slate-500 dark:text-slate-400">Review reasons: {(q.reasons ?? []).join(" · ")}</p>}
        </article>
      ))}
    </div>
  );
}


function TechnicalEvidenceDrawer({ open, student, onClose }: { open: boolean; student: StudentResult; onClose: () => void }) {
  const [details, setDetails] = useState<ProcessingDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setDetails(null);
    setError(null);
    getProcessingDetails(student.id)
      .then((payload) => {
        if (!cancelled) setDetails(payload);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load processing details.");
      });
    return () => {
      cancelled = true;
    };
  }, [open, student.id]);
  if (!open) return null;
  const artifacts = details?.artifacts;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" onClick={onClose} aria-label="Close processing details" className="absolute inset-0 bg-[#151827]/35 backdrop-blur-sm" />
      <section role="dialog" aria-modal="true" aria-label="Technical evidence" className="relative z-10 flex max-h-[calc(100dvh-32px)] w-full max-w-[920px] flex-col overflow-hidden rounded-[28px] border border-white/80 bg-[#fbfcff] shadow-[0_30px_80px_rgba(30,35,80,0.28)] dark:border-white/10 dark:bg-[#202437]">
        <div className="flex items-start justify-between gap-4 border-b border-[#edf0ff] p-5 dark:border-white/10 sm:p-7">
          <div>
            <p className="type-overline text-[#7484e6]">Technical evidence</p>
            <h2 className="type-page-title mt-2 text-[#171827] dark:text-white">Processing details</h2>
            <p className="mt-2 text-[13px] font-medium text-slate-500 dark:text-slate-400">
              {student.rollNumber}
              {details?.job ? ` · job ${details.job.status ?? "unknown"} · stage ${details.job.current_stage ?? "—"}` : ""}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-full border border-slate-200 bg-white p-2 text-slate-500 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/5 dark:text-slate-300"><X className="h-4 w-4" /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-7">
          {error ? (
            <EvidencePlaceholder icon={AlertTriangle} title="Could not load processing details" description={error} />
          ) : !details ? (
            <p className="type-support text-slate-400">Loading processing details…</p>
          ) : (
            <Tabs defaultValue="original">
              <TabsList className="max-w-full overflow-x-auto bg-[#eef0ff] dark:bg-white/[0.06]">
                <TabsTrigger value="original" className="text-[12px]">Original</TabsTrigger>
                <TabsTrigger value="preprocessed" className="text-[12px]">Preprocessed</TabsTrigger>
                <TabsTrigger value="segments" className="text-[12px]">Segments</TabsTrigger>
                <TabsTrigger value="ocr" className="text-[12px]">OCR</TabsTrigger>
                <TabsTrigger value="evaluation" className="text-[12px]">Evaluation Data</TabsTrigger>
              </TabsList>
              <TabsContent value="original" className="mt-5">
                <ArtifactGallery submissionId={student.id} kind="original" files={artifacts?.original ?? []} emptyTitle="Original page renders unavailable" emptyDescription="Rendered page images are written when the evaluation pipeline processes this PDF." />
              </TabsContent>
              <TabsContent value="preprocessed" className="mt-5">
                <ArtifactGallery submissionId={student.id} kind="preprocessed" files={artifacts?.preprocessed ?? []} emptyTitle="Preprocessed pages unavailable" emptyDescription="Deskewed, contrast-normalised page images appear here after preprocessing runs." />
              </TabsContent>
              <TabsContent value="segments" className="mt-5">
                <ArtifactGallery submissionId={student.id} kind="segments" files={artifacts?.segments ?? []} emptyTitle="No segment crops" emptyDescription="Per-question region crops written by the segmentation stage appear here." />
              </TabsContent>
              <TabsContent value="ocr" className="mt-5">
                <OcrEvidence regions={details.regions ?? []} />
              </TabsContent>
              <TabsContent value="evaluation" className="mt-5">
                <EvaluationEvidence questions={details.questions} />
              </TabsContent>
            </Tabs>
          )}
        </div>
      </section>
    </div>
  );
}

function OcrEvidence({ regions }: { regions: ProcessingRegion[] }) {
  const withText = regions.filter((region) => (region.ocr?.raw_text ?? "").length > 0);
  if (withText.length === 0) {
    return <EvidencePlaceholder icon={ScanLine} title="No OCR text recorded yet" description="Per-region OCR transcription appears here once an evaluation job completes on this build — the worker now persists regions and OCR into the evidence tables." />;
  }
  return (
    <div className="space-y-2">
      {withText.map((region) => (
        <article key={region.region_id} className="rounded-[18px] border border-[#e4e8ff] bg-white p-4 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[13px] font-semibold text-[#171827] dark:text-white">{region.question_id ?? "Unmapped region"}</p>
            <span className="rounded-full bg-[#eef0ff] px-2 py-0.5 text-[11px] font-medium text-[#6374da]">P{region.page_number} · {region.region_type}</span>
            {(region.ocr?.flags ?? []).map((flag) => <span key={flag} className="rounded-full bg-[#fff2df] px-2 py-0.5 text-[11px] font-medium text-[#b57626]">{flag}</span>)}
            <span className="ml-auto text-[11px] text-slate-400">{region.ocr?.word_count ?? 0} words</span>
          </div>
          <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-xl bg-[#f7f8ff] p-3 font-mono text-[12px] leading-5 text-slate-700 dark:bg-white/[0.06] dark:text-slate-200">{region.ocr?.raw_text}</pre>
          {(region.ocr?.uncertain_spans ?? []).length > 0 && (
            <p className="mt-2 text-[12px] font-medium text-[#b57626]">Uncertain: {(region.ocr?.uncertain_spans ?? []).map((u) => String(u?.text ?? "")).filter(Boolean).join(", ")}</p>
          )}
        </article>
      ))}
    </div>
  );
}

function EvidencePlaceholder({ icon: Icon, title, description }: { icon: typeof FileText; title: string; description: string }) { return <div className="flex min-h-[250px] flex-col items-center justify-center rounded-[20px] border border-dashed border-[#c9d2ff] bg-[linear-gradient(135deg,#f7f8ff,#eef1ff)] p-6 text-center dark:border-[#8797ff]/30 dark:bg-white/[0.04]"><span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-[#7182ef] shadow-sm dark:bg-white/10"><Icon className="h-6 w-6" /></span><p className="mt-4 text-[15px] font-semibold text-[#171827] dark:text-white">{title}</p><p className="mt-2 max-w-[420px] text-[13px] leading-5 text-slate-500 dark:text-slate-400">{description}</p></div>; }

/** Map the read-model's per-question record into the Results domain shape. */
/** The backend stores strictness per question; normalise any unknown value. */
function normalizeStrictness(level: string | null | undefined): QuestionResult["strictness"] {
  const value = String(level ?? "").toLowerCase();
  if (value === "lenient" || value === "strict") return value;
  return "moderate";
}

function detailToQuestionResults(detail: SubmissionResultDetail): QuestionResult[] {
  return (detail?.questions ?? []).map((question, index) => {
    const raw = String(question.question_id ?? "").replace(/^Q/i, "");
    const number = Number.parseInt(raw, 10) || index + 1;
    const breakdown = (question.breakdown ?? {}) as Record<string, unknown>;
    const feedback = typeof breakdown.feedback === "string" ? breakdown.feedback : "";
    const notes = Array.isArray(question.criteria) && question.criteria.length > 0
      ? question.criteria
          .map((c) => String((c as Record<string, unknown>)?.reason ?? (c as Record<string, unknown>)?.criterion_id ?? ""))
          .filter(Boolean)
          .join(" · ")
      : "Recorded without a criteria breakdown.";
    return {
      id: `${detail.submission_id}-q${question.question_id}`,
      number,
      questionText: "Evaluation record — question text is linked from the answer key.",
      marksAwarded: question.final_marks,
      maxMarks: question.maximum,
      strictness: normalizeStrictness(question.strictness_level),
      studentAnswer: "",
      expectedPoints: [],
      evaluation: feedback || notes,
      needsReview: question.source === "review",
    };
  });
}

/** Map the assessment results read-model into the Results domain shape. */
function toResultClass(data: AssessmentResults): ResultClass {
  return {
    id: data.assessment_id,
    className: data.title,
    subject: `${data.question_count} questions · pass ${data.pass_percentage}%`,
    totalStudents: data.summary.total,
    totalMarks: data.total_marks,
    completedAt: "",
    completionStatus:
      data.summary.completed === data.summary.total && data.summary.total > 0
        ? "complete"
        : "partial",
    students: data.students.map((student) => ({
      id: student.submission_id,
      rollNumber: student.roll_number,
      totalScore: student.total,
      maxScore: student.maximum,
      status: student.teacher_modified
        ? ("teacher-modified" as ResultStatus)
        : student.status === "waiting_for_review" || student.status === "failed"
          ? ("needs-review" as ResultStatus)
          : ("completed" as ResultStatus),
      questionResults: [],
    })),
  };
}

export default function Results() {
  const [location, setLocation] = useLocation();
  const parts = location.split("/").filter(Boolean);
  const classId = parts[1];
  const studentId = parts[2];

  // Milestone 17: real incremental results, polled every 5s (#70/#73).
  const [liveResults, setLiveResults] = useState<AssessmentResults | null>(null);
  // Per-student question-level detail from the read-model, fetched when the
  // student route is open so marks + criteria render in the Results page.
  const [questionDetail, setQuestionDetail] = useState<SubmissionResultDetail | null>(null);
  // Bumped when the teacher-review loop resolves so the read-model detail is
  // refetched immediately (the job completed between polls).
  const [detailNonce, setDetailNonce] = useState(0);
  useEffect(() => {
    if (!classId) return;
    let alive = true;
    const load = async () => {
      try {
        const data = await getAssessmentResults(classId);
        if (alive) setLiveResults(data);
      } catch {
        /* keep last known state on transient errors */
      }
    };
    void load();
    const timer = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [classId]);

  useEffect(() => {
    if (!classId || !studentId) {
      setQuestionDetail(null);
      return;
    }
    let alive = true;
    getSubmissionResult(classId, studentId)
      .then((data) => {
        if (alive) setQuestionDetail(data);
      })
      .catch(() => {
        if (alive) setQuestionDetail(null);
      });
    return () => {
      alive = false;
    };
  }, [classId, studentId, detailNonce]);

  // Results home: list every assessment that has uploaded papers, hydrated
  // through the results read-model so cards show real totals (single fetch per
  // assessment — classroom-sized lists stay cheap).
  const [homeResults, setHomeResults] = useState<ResultClass[]>([]);
  useEffect(() => {
    if (classId) return;
    let alive = true;
    const load = async () => {
      try {
        const assessments = await listAssessments();
        const detailed = await Promise.all(
          assessments
            .filter((assessment) => assessment.student_count > 0)
            .map((assessment) => getAssessmentResults(assessment.id).catch(() => null)),
        );
        if (alive) {
          setHomeResults(
            detailed
              .filter((data): data is AssessmentResults => data !== null)
              .map(toResultClass),
          );
        }
      } catch {
        /* keep last known state on transient errors */
      }
    };
    void load();
    const timer = window.setInterval(load, 10000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [classId]);

  const live: ResultClass[] = useMemo(() => {
    if (liveResults) return [toResultClass(liveResults)];
    return homeResults;
  }, [homeResults, liveResults]);

  const resultClass = live.find((item) => item.id === classId) ?? null;
  const student = resultClass?.students.find((item) => item.id === studentId) ?? null;
  const detailedStudent =
    student && questionDetail
      ? { ...student, questionResults: detailToQuestionResults(questionDetail) }
      : student;

  const content = resultClass && detailedStudent ? <StudentResults resultClass={resultClass} student={detailedStudent} onBack={() => setLocation(`/results/${resultClass.id}`)} onReviewResolved={() => setDetailNonce((nonce) => nonce + 1)} /> : resultClass ? <ClassResults resultClass={resultClass} onBack={() => setLocation("/results")} onStudent={(selected) => setLocation(`/results/${resultClass.id}/${selected.id}`)} /> : <ResultsHome onSelect={(selected) => setLocation(`/results/${selected.id}`)} classes={live} />;
  return <div className="results-workspace">{content}</div>;
}
