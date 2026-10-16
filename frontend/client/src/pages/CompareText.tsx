/**
 * STYLE: Reference-led soft glass workspace — assessment intake, answer review, and teacher-facing evidence share a calm, professional flow.
 */
import { BarChart3, Copy, FileText, Loader2, ScanText, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ComparisonSettings } from "@/components/compare/ComparisonSettings";
import { DifferenceViewer } from "@/components/compare/DifferenceViewer";
import { DocumentIntake } from "@/components/compare/DocumentIntake";
import { MetricCard } from "@/components/compare/MetricCard";
import { TextEditor } from "@/components/compare/TextEditor";
import { compareTexts, ComparisonResult, defaultComparisonSettings } from "@/lib/compare";

interface CompareTextProps { resetSignal: number; }

const sampleExpectedAnswer = "A random forest combines multiple decision trees trained on different samples and uses their collective output to improve reliability.";
const sampleStudentAnswer = "Random forests use many decision trees. Each tree gives an answer and the model uses the combined result.";

export default function CompareText({ resetSignal }: CompareTextProps) {
  const [reference, setReference] = useState("");
  const [prediction, setPrediction] = useState("");
  const [settings, setSettings] = useState(defaultComparisonSettings);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const clearEvaluation = useCallback((announce = true) => {
    setReference("");
    setPrediction("");
    setResult(null);
    setSettings(defaultComparisonSettings);
    setAnalyzing(false);
    if (announce) toast("Evaluation cleared", { description: "Assessment inputs and review notes were reset." });
  }, []);

  useEffect(() => {
    if (resetSignal > 0) clearEvaluation();
  }, [resetSignal, clearEvaluation]);

  const runEvaluation = () => {
    if (!reference.trim()) return toast("Expected answer is required", { description: "Add an answer key or marking scheme to continue." });
    if (!prediction.trim()) return toast("Student answer is required", { description: "Add a student response to continue." });
    setAnalyzing(true);
    window.setTimeout(() => {
      setResult(compareTexts(reference, prediction, settings));
      setAnalyzing(false);
      toast("Review notes prepared", { description: "Answer alignment is ready for teacher review. Marks remain pending until grading is connected." });
    }, 280);
  };

  const loadExample = () => {
    setReference(sampleExpectedAnswer);
    setPrediction(sampleStudentAnswer);
    setResult(null);
    toast("Sample assessment loaded", { description: "Select Evaluate responses to prepare answer-review notes." });
  };

  const copyReview = async () => {
    if (!result) return;
    const summary = [
      "EvalAI Assessment Review",
      "Expected answer: supplied",
      "Student answer: supplied",
      "Review notes: prepared",
      "Marks awarded: pending teacher review",
    ].join("\n");
    try {
      await navigator.clipboard.writeText(summary);
      toast("Review summary copied");
    } catch {
      toast("Copy is unavailable", { description: "Try selecting the review text manually." });
    }
  };

  return (
    <div className="mx-auto max-w-[1240px] space-y-4 pb-6">
      <section className="relative overflow-hidden rounded-[25px] border border-white/85 bg-[linear-gradient(110deg,rgba(255,255,255,0.9),rgba(247,249,255,0.72),rgba(255,253,243,0.65))] px-5 py-6 shadow-[0_15px_40px_rgba(63,73,139,0.08)] backdrop-blur dark:border-white/10 dark:bg-[#1c1f2e] sm:px-7">
        <div className="pointer-events-none absolute right-0 top-0 h-32 w-80 bg-[radial-gradient(circle_at_top_right,rgba(133,148,255,0.25),transparent_68%)]" />
        <div className="relative flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="type-overline inline-flex items-center gap-2 rounded-full border border-[#dbe0ff] bg-white/80 px-2.5 py-1 text-[#6274e7] dark:border-[#8797ff]/20 dark:bg-white/5 dark:text-[#b2bcff]"><Sparkles className="h-3 w-3" /> Answer evaluation</div>
            <h1 className="type-page-title mt-3 text-[#171827] dark:text-white">Evaluate every answer with context.</h1>
            <p className="type-body mt-3 max-w-2xl text-slate-600 dark:text-slate-300">Review student responses, awarded marks, and evaluation context against the configured marking scheme.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={loadExample} className="type-button rounded-full border border-slate-200 bg-white/85 px-3.5 py-2.5 text-slate-600 transition-colors hover:bg-white hover:text-[#5668dc] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/5 dark:text-slate-200">Load sample</button>
            <button type="button" onClick={() => clearEvaluation()} className="type-button rounded-full border border-slate-200 bg-white/85 px-3.5 py-2.5 text-slate-600 transition-colors hover:bg-[#fff3f2] hover:text-[#bc6262] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/5 dark:text-slate-200">Clear evaluation</button>
          </div>
        </div>
      </section>

      <DocumentIntake onLoadText={(text) => { setPrediction(text); setResult(null); }} />

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Total score" description="Available after grading" value={null} icon={FileText} accent="teal" />
        <MetricCard label="Questions evaluated" description="Awaiting assessment setup" value={null} icon={Sparkles} accent="periwinkle" />
        <MetricCard label="Review required" description="Answers needing attention" value={null} icon={BarChart3} accent="amber" />
        <MetricCard label="Evaluation progress" description="Assessment not started" value={null} icon={ScanText} accent="rose" />
        <article className="flex items-center gap-3 rounded-2xl border border-white/85 bg-white/70 p-4 shadow-[0_8px_20px_rgba(60,70,135,0.05)] backdrop-blur dark:border-white/10 dark:bg-[#1e2131]">
          <div className="grid h-14 w-14 shrink-0 place-items-center rounded-full bg-[#eef1ff] text-sm font-extrabold text-[#6275df] dark:bg-[#7587f2]/15 dark:text-[#b7c0ff]">—</div>
          <div><p className="type-meta text-slate-500 dark:text-slate-400">Final status</p><p className="type-section-title mt-1 text-slate-600 dark:text-slate-300">Not started</p><p className="type-support mt-1 text-slate-500 dark:text-slate-400">Add assessment inputs to begin.</p></div>
        </article>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <TextEditor title="Expected answer" description="Answer key or marking scheme" placeholder="Paste the expected answer or marking points here..." value={reference} onChange={(value) => { setReference(value); setResult(null); }} accent="periwinkle" />
        <TextEditor title="Student answer" description="Response for the selected question" placeholder="Paste a student answer here..." value={prediction} onChange={(value) => { setPrediction(value); setResult(null); }} accent="teal" />
      </section>

      <div className="grid gap-4 lg:grid-cols-[1fr_auto] lg:items-center">
        <ComparisonSettings settings={settings} onChange={(next) => { setSettings(next); setResult(null); }} />
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={copyReview} disabled={!result} className="type-button inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/85 px-3.5 py-3.5 text-slate-600 transition-colors hover:bg-[#f0f2ff] hover:text-[#5668dc] disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/5 dark:text-slate-200"><Copy className="h-4 w-4" />Copy review</button>
          <button type="button" disabled={!reference.trim() || !prediction.trim() || analyzing} onClick={runEvaluation} className="type-button inline-flex items-center gap-2 rounded-full bg-[#171b32] px-5 py-3.5 text-white shadow-[0_9px_20px_rgba(23,27,50,0.16)] transition-all duration-150 hover:-translate-y-px hover:bg-[#30386d] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:bg-[#9aa8ff] dark:text-[#151827]">{analyzing ? <><Loader2 className="h-4 w-4 animate-spin" />Preparing review...</> : <><ScanText className="h-4 w-4" />Evaluate responses</>}</button>
        </div>
      </div>

      <DifferenceViewer result={result} />

      <section className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <AssessmentSummary hasReview={Boolean(result)} />
        <ReviewQueue hasReview={Boolean(result)} />
      </section>
    </div>
  );
}

function AssessmentSummary({ hasReview }: { hasReview: boolean }) {
  const entries: Array<[string, string]> = [
    ["Question selected", "—"], ["Expected marks", "—"], ["Marks awarded", "—"], ["Teacher review", hasReview ? "Pending" : "—"], ["Feedback status", "—"], ["Result status", "Not published"],
  ];
  const rows = entries.reduce<Array<Array<[string, string]>>>((accumulator, entry, index) => {
    if (index % 2 === 0) accumulator.push([entry]); else accumulator[accumulator.length - 1].push(entry);
    return accumulator;
  }, []);
  return <article className="overflow-hidden rounded-2xl border border-white/85 bg-white/70 shadow-[0_8px_20px_rgba(60,70,135,0.05)] backdrop-blur dark:border-white/10 dark:bg-[#1e2131]"><div className="flex items-center gap-2 border-b border-slate-100 px-4 py-4 dark:border-white/10"><FileText className="h-4 w-4 text-[#7182ef]" /><div><h2 className="text-sm font-extrabold text-[#171827] dark:text-white">Assessment summary</h2><p className="text-xs font-medium text-slate-500 dark:text-slate-400">Marks and teacher review details appear here when grading is connected.</p></div></div><div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left"><thead className="bg-white/55 text-[10px] font-extrabold uppercase tracking-[0.12em] text-slate-500 dark:bg-white/[0.025] dark:text-slate-400"><tr><th className="px-4 py-3">Assessment detail</th><th className="px-4 py-3">Value</th><th className="px-4 py-3">Assessment detail</th><th className="px-4 py-3">Value</th></tr></thead><tbody className="text-xs font-semibold text-slate-600 dark:text-slate-300">{rows.map((row) => <tr key={row[0][0]} className="border-t border-slate-100 dark:border-white/[0.06]"><td className="px-4 py-3 text-slate-500 dark:text-slate-400">{row[0][0]}</td><td className="px-4 py-3 font-extrabold text-[#171827] dark:text-white">{row[0][1]}</td><td className="px-4 py-3 text-slate-500 dark:text-slate-400">{row[1]?.[0] ?? ""}</td><td className="px-4 py-3 font-extrabold text-[#171827] dark:text-white">{row[1]?.[1] ?? ""}</td></tr>)}</tbody></table></div></article>;
}

function ReviewQueue({ hasReview }: { hasReview: boolean }) {
  return <article className="rounded-2xl border border-white/85 bg-white/70 p-4 shadow-[0_8px_20px_rgba(60,70,135,0.05)] backdrop-blur dark:border-white/10 dark:bg-[#1e2131]"><div className="flex items-center gap-2"><BarChart3 className="h-4 w-4 text-[#7182ef]" /><div><h2 className="text-sm font-extrabold text-[#171827] dark:text-white">Teacher review queue</h2><p className="text-xs font-medium text-slate-500 dark:text-slate-400">Flagged answers and final checks will appear here.</p></div></div><div className="mt-9 flex min-h-32 flex-col items-center justify-center text-center"><p className="text-2xl font-extrabold text-slate-300 dark:text-slate-600">—</p><p className="mt-2 max-w-[220px] text-xs font-medium text-slate-500 dark:text-slate-400">{hasReview ? "Answer alignment notes are ready. Connect grading to allocate marks and flag answers for review." : "No evaluation yet. Upload an answer sheet and marking scheme to begin."}</p></div></article>;
}
