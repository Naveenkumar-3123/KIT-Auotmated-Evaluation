import { createPortal } from "react-dom";
import { AlertTriangle, X } from "lucide-react";
import type { AnswerKeyPayload } from "@/api/answerKeys";

export function AnswerKeyPreviewModal({ open, onClose, payload }: { open: boolean; onClose: () => void; payload: AnswerKeyPayload | null }) {
  if (!open || !payload) return null;
  const questions = payload.questions;
  const diagramCount = questions.reduce((sum, q) => sum + q.diagrams.length, 0);
  const warnings = questions.flatMap((q) => q.parser_uncertainties.map((w) => `Q${q.question_number}: ${w}`));
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button type="button" onClick={onClose} aria-label="Close answer key preview" className="fixed inset-0 bg-[#151827]/40 backdrop-blur-sm" />
      <section role="dialog" aria-modal="true" aria-label="Parsed answer key" className="relative z-10 flex max-h-[88vh] w-full max-w-[720px] flex-col overflow-hidden rounded-[28px] border border-white/80 bg-[#fdfdff] p-5 shadow-[0_30px_80px_rgba(30,35,80,0.32)] dark:border-white/10 dark:bg-[#222638] sm:p-7">
        <div className="flex items-start justify-between gap-5">
          <div>
            <p className="type-overline text-[#7484e6]">Locked grading source</p>
            <h2 className="type-page-title mt-2 text-[#171827] dark:text-white">Parsed answer key</h2>
            <p className="type-support mt-2 text-slate-500 dark:text-slate-400">{questions.length} questions · {diagramCount} diagram image{diagramCount === 1 ? "" : "s"} · v{payload.answer_key.version}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-full border border-slate-200 bg-white p-2 text-slate-500 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"><X className="h-4 w-4" /></button>
        </div>
        <div className="mt-5 flex-1 space-y-3 overflow-y-auto pr-1">
          {questions.map((question) => (
            <article key={question.id} className="rounded-[18px] border border-[#e8ebff] bg-white/85 p-4 dark:border-white/[0.08] dark:bg-white/[0.04]">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="type-overline text-[#7182ef]">Q{question.question_number}</p>
                <p className="text-[12px] font-semibold text-slate-500 dark:text-slate-400">Max {question.maximum_marks} marks · {question.answer_type}{question.diagrams.length > 0 ? ` · ${question.diagrams.length} diagram${question.diagrams.length === 1 ? "" : "s"}` : ""}</p>
              </div>
              <p className="mt-2 line-clamp-2 text-[13px] font-medium text-[#171827] dark:text-white">{question.question_text}</p>
              <p className="mt-1.5 line-clamp-3 text-[12px] leading-5 text-slate-500 dark:text-slate-400">{question.expected_answer_text}</p>
              {question.keywords.length > 0 && <p className="mt-2 text-[11px] font-medium text-[#6276e5]">Keywords: {question.keywords.join(", ")}</p>}
            </article>
          ))}
        </div>
        {warnings.length > 0 && (
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-[#f1dfc6] bg-[#fffaf4] px-4 py-3 text-[12px] text-[#8a642f] dark:border-[#b58a4e]/20 dark:bg-[#b58a4e]/10 dark:text-[#f0c987]">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{warnings.length} parser warning{warnings.length === 1 ? "" : "s"} — review them in the Configure flow before evaluating.</span>
          </div>
        )}
      </section>
    </div>,
    document.body
  );
}
