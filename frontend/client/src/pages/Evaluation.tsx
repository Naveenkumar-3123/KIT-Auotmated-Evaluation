/** STYLE: EvalAI Evaluation — premium operational control center using measured glass cards, calm status color, and clear teacher-facing hierarchy.
 * Milestone 6: every view is backed by the real assessment/submission APIs — no mock evaluations or fake progress timers. */
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "wouter";
import { toast } from "sonner";
import {
  getAssessmentStatus,
  listAssessments,
  listStudents,
  startEvaluation,
  uploadAnswerPaper,
  type AssessmentStatusResponse,
} from "@/api/assessments";
import { getAnswerKey, type AnswerKeyPayload } from "@/api/answerKeys";
import { apiFetchObjectUrl } from "@/api/client";
import { ClassSelectionView } from "@/components/evaluation/ClassSelectionView";
import { CompletionView, type CompletionCounts } from "@/components/evaluation/CompletionView";
import {
  toAnswerSheet,
  toConfiguredEvaluation,
  type AnswerSheet,
  type ConfiguredEvaluation,
} from "@/components/evaluation/evaluation-data";
import { PreviewModal } from "@/components/evaluation/PreviewModal";
import { ProgressEvaluationView } from "@/components/evaluation/ProgressEvaluationView";
import { ReviewEvaluationView } from "@/components/evaluation/ReviewEvaluationView";
import { AnswerKeyPreviewModal } from "@/components/evaluation/AnswerKeyPreviewModal";

type EvaluationState = "choose" | "review" | "running" | "complete";
type PreviewTarget = { title: string; subtitle: string; fileName: string; contentUrl?: string | null } | null;

const EVALUABLE_STATUSES = new Set(["configured", "processing", "waiting_for_review"]);
const POLL_MS = 3000;

export default function Evaluation() {
  const [, setLocation] = useLocation();
  const [state, setState] = useState<EvaluationState>("choose");
  const [evaluations, setEvaluations] = useState<ConfiguredEvaluation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ConfiguredEvaluation | null>(null);
  const [sheets, setSheets] = useState<AnswerSheet[]>([]);
  const [preview, setPreview] = useState<PreviewTarget>(null);
  const [keyPayload, setKeyPayload] = useState<AnswerKeyPayload | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [starting, setStarting] = useState(false);
  const [completedCount, setCompletedCount] = useState(0);
  const [currentRoll, setCurrentRoll] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [finalCounts, setFinalCounts] = useState<CompletionCounts | null>(null);
  const pollTimer = useRef<number | null>(null);

  const refreshEvaluations = useCallback(async () => {
    try {
      const rows = await listAssessments();
      setEvaluations(rows.filter((row) => EVALUABLE_STATUSES.has(row.status)).map(toConfiguredEvaluation));
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load assessments");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshEvaluations();
  }, [refreshEvaluations]);

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const applyStatus = useCallback((status: AssessmentStatusResponse) => {
    const summary = status.summary;
    const mapped = status.students.map(toAnswerSheet);
    setSheets(mapped);
    setCompletedCount(summary.completed);
    const active = mapped.find((sheet) => sheet.status === "processing");
    setCurrentRoll(active?.rollNumber ?? null);
    const settled = summary.completed + summary.waiting_for_review + summary.failed;
    const denominator = Math.max(1, summary.total);
    setProgress(Math.min(100, Math.round((settled / denominator) * 100)));
    return { summary, settled };
  }, []);

  const runPolling = useCallback((assessment: ConfiguredEvaluation) => {
    stopPolling();
    pollTimer.current = window.setInterval(() => {
      void (async () => {
        try {
          const status = await getAssessmentStatus(assessment.id);
          const { summary } = applyStatus(status);
          if (summary.processing === 0 && summary.ready === 0) {
            stopPolling();
            setFinalCounts({
              total: summary.total,
              completed: summary.completed,
              waiting: summary.waiting_for_review,
              failed: summary.failed,
            });
            setState("complete");
          }
        } catch {
          /* transient network errors are tolerated; next tick retries */
        }
      })();
    }, POLL_MS);
  }, [applyStatus, stopPolling]);

  const choose = async (item: ConfiguredEvaluation) => {
    setSelected(item);
    setSheets([]);
    try {
      const roster = await listStudents(item.id);
      const mapped = roster.map(toAnswerSheet);
      setSheets(mapped);
      // Resume an already-running evaluation straight into live progress.
      const status = await getAssessmentStatus(item.id);
      applyStatus(status);
      if (status.status === "processing") {
        setState("running");
        runPolling(item);
        return;
      }
      setState("review");
    } catch (error) {
      toast.error("Could not load this assessment", { description: error instanceof Error ? error.message : undefined });
      setSelected(null);
      setState("choose");
    }
  };

  const viewSheet = async (sheet: AnswerSheet) => {
    if (!sheet.submissionId || !selected) return;
    setPreview({ title: `Answer Sheet · ${sheet.rollNumber}`, subtitle: "Original uploaded answer sheet", fileName: sheet.fileName });
    try {
      const url = await apiFetchObjectUrl(`/assessments/submissions/${sheet.submissionId}/pdf`);
      setPreview({ title: `Answer Sheet · ${sheet.rollNumber}`, subtitle: "Original uploaded answer sheet", fileName: sheet.fileName, contentUrl: url });
    } catch (error) {
      setPreview(null);
      toast.error("Could not open the paper", { description: error instanceof Error ? error.message : undefined });
    }
  };

  const viewKey = async () => {
    if (!selected) return;
    try {
      const status = await getAssessmentStatus(selected.id);
      if (!status.answer_key) {
        toast.error("No answer key found for this assessment");
        return;
      }
      const payload = await getAnswerKey(status.answer_key.id);
      setKeyPayload(payload);
    } catch (error) {
      toast.error("Could not load the parsed answer key", { description: error instanceof Error ? error.message : undefined });
    }
  };

  const addSheet = async (rollNumber: string, file: File) => {
    if (!selected) return;
    try {
      // The typed roll number is authoritative — rename so the backend parses it from the filename.
      const renamed = new File([file], `${rollNumber}.pdf`, { type: "application/pdf" });
      const result = await uploadAnswerPaper(selected.id, renamed);
      const roster = await listStudents(selected.id);
      setSheets(roster.map(toAnswerSheet));
      const addedRolls = result.students.filter((entry) => entry.status === "valid" || entry.status === "duplicate").map((entry) => entry.roll_number);
      toast("Answer sheet added", { description: `Added ${addedRolls.join(", ") || "submission"} — ready for evaluation.` });
    } catch (error) {
      toast.error("Upload rejected", { description: error instanceof Error ? error.message : undefined });
    }
  };

  const begin = async () => {
    if (!selected) return;
    setStarting(true);
    try {
      const started = await startEvaluation(selected.id);
      toast("Evaluation started", { description: `${started.submissions_queued} answer sheet${started.submissions_queued === 1 ? "" : "s"} queued across available computers.` });
      setConfirm(false);
      setCompletedCount(0);
      setCurrentRoll(null);
      setState("running");
      runPolling(selected);
    } catch (error) {
      toast.error("Could not start evaluation", { description: error instanceof Error ? error.message : undefined });
    } finally {
      setStarting(false);
    }
  };

  if (!selected || state === "choose") {
    return <ClassSelectionView classes={evaluations} onSelect={(item) => void choose(item)} onConfigure={() => setLocation("/configure")} />;
  }

  const beginDisabled =
    starting ||
    sheets.length === 0 ||
    !sheets.some(
      (sheet) =>
        sheet.status === "ready" ||
        sheet.rawStatus === "pending" ||
        sheet.rawStatus === "uploaded" ||
        sheet.rawStatus === "ready",
    );

  return (
    <>
      <PreviewModal open={Boolean(preview)} onClose={() => setPreview(null)} title={preview?.title ?? ""} subtitle={preview?.subtitle ?? ""} fileName={preview?.fileName ?? ""} contentUrl={preview?.contentUrl} />
      <AnswerKeyPreviewModal open={Boolean(keyPayload)} onClose={() => setKeyPayload(null)} payload={keyPayload} />
      {state === "review" && (
        <ReviewEvaluationView
          evaluation={selected}
          sheets={sheets}
          onBack={() => { setState("choose"); setSelected(null); }}
          onViewSheet={(sheet) => void viewSheet(sheet)}
          onViewKey={() => void viewKey()}
          onAddSheet={(rollNumber, file) => void addSheet(rollNumber, file)}
          onBegin={() => setConfirm(true)}
        />
      )}
      {state === "running" && (
        <ProgressEvaluationView
          evaluation={selected}
          sheets={sheets}
          completedCount={completedCount}
          currentRoll={currentRoll}
          progress={progress}
        />
      )}
      {state === "complete" && (
        <CompletionView
          evaluation={selected}
          counts={finalCounts ?? { total: sheets.length, completed: completedCount, waiting: 0, failed: 0 }}
          onResults={() => setLocation(`/results/${selected.id}`)}
          onBack={() => { setState("choose"); setSelected(null); }}
        />
      )}
      {confirm &&
        createPortal(
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            <button type="button" onClick={() => setConfirm(false)} className="fixed inset-0 bg-[#151827]/40 backdrop-blur-sm" aria-label="Cancel evaluation" />
            <section role="dialog" aria-modal="true" aria-label="Begin evaluation" className="relative z-10 w-full max-w-[440px] rounded-[26px] bg-white p-6 shadow-[0_30px_80px_rgba(30,35,80,0.32)] dark:bg-[#222638]">
              <p className="type-overline text-[#7182ef]">Ready to begin</p>
              <h2 className="type-section-title mt-2 text-[#171827] dark:text-white">Begin evaluation?</h2>
              <dl className="mt-5 space-y-3 rounded-2xl bg-[#f8f9ff] p-4 text-[13px] dark:bg-white/[0.04]">
                <div className="flex justify-between gap-4"><dt className="text-slate-500">Class</dt><dd className="font-semibold text-[#171827] dark:text-white">{selected.className}</dd></div>
                <div className="flex justify-between gap-4"><dt className="text-slate-500">Subject</dt><dd className="font-semibold text-[#171827] dark:text-white">{selected.subject}</dd></div>
                <div className="flex justify-between gap-4"><dt className="text-slate-500">Students</dt><dd className="font-semibold text-[#171827] dark:text-white">{sheets.length}</dd></div>
              </dl>
              <p className="mt-4 text-[13px] leading-5 text-slate-500 dark:text-slate-400">All answer sheets will be queued for evaluation against the locked answer key and policies. Results appear incrementally as each student completes.</p>
              <div className="mt-6 flex justify-end gap-2">
                <button type="button" onClick={() => setConfirm(false)} className="type-button rounded-full px-4 py-2.5 text-slate-500">Cancel</button>
                <button type="button" disabled={beginDisabled} onClick={() => void begin()} className="type-button rounded-full bg-[#171b32] px-4 py-2.5 text-white disabled:opacity-40 dark:bg-[#9aa8ff] dark:text-[#151827]">{starting ? "Queuing…" : "Begin Evaluation"}</button>
              </div>
            </section>
          </div>,
          document.body
        )}
    </>
  );
}

