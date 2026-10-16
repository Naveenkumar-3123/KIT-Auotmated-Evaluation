/**
 * STYLE: Reference-led soft glass intake — assessment preparation is presented as a polished onboarding surface, not a raw test control.
 */
import { FileImage, FileUp, Play, ScanLine, Sparkles } from "lucide-react";
import { ChangeEvent, useRef, useState } from "react";
import { toast } from "sonner";

interface DocumentIntakeProps { onLoadText: (text: string) => void; }

export function DocumentIntake({ onLoadText }: DocumentIntakeProps) {
  const [documentName, setDocumentName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectDocument = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setDocumentName(file.name);
    if (file.type.startsWith("text/") || /\.(txt|csv|json)$/i.test(file.name)) {
      try {
        onLoadText(await file.text());
        toast("Answer sheet loaded", { description: "Its text is ready for the student-answer review panel." });
      } catch {
        toast("Could not read the selected text file");
      }
    } else {
      toast("Answer sheet staged", { description: "Connect the document-reading service to prepare this file for evaluation." });
    }
    event.target.value = "";
  };

  return (
    <section className="relative overflow-hidden rounded-2xl border border-white/85 bg-white/62 p-4 shadow-[0_12px_30px_rgba(60,70,135,0.08)] backdrop-blur-xl dark:border-white/10 dark:bg-[#202334]/75 sm:p-5">
      <div className="pointer-events-none absolute right-0 top-0 h-32 w-56 bg-[radial-gradient(circle_at_top_right,rgba(147,161,255,0.22),transparent_70%)]" />
      <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#eef1ff] text-[#697ce7] dark:bg-[#7284ef]/15 dark:text-[#b3bdff]"><FileImage className="h-5 w-5" /></span><div><p className="type-overline text-[#6779e6] dark:text-[#aeb8ff]">Assessment input</p><h2 className="type-section-title mt-1.5 text-[#171827] dark:text-white">Add the question paper, marking scheme, and student answer sheet to begin evaluation.</h2><p className="type-support mt-1.5 max-w-[580px] text-slate-500 dark:text-slate-400">{documentName ? `${documentName} is staged for assessment review.` : "Upload an image, PDF, or text file. Text files can populate the student-answer panel immediately."}</p></div></div>
        <div className="flex flex-wrap gap-2"><button type="button" onClick={() => inputRef.current?.click()} className="type-button inline-flex items-center gap-1.5 rounded-full bg-[#171b32] px-3.5 py-2.5 text-white transition-colors hover:bg-[#30386d] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:bg-[#9aa8ff] dark:text-[#151827]"><FileUp className="h-3.5 w-3.5" />Upload Answer Sheet</button><button type="button" onClick={() => toast("Evaluation service ready to connect", { description: "Add your grading service to evaluate staged answer sheets." })} className="type-button inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white/80 px-3.5 py-2.5 text-slate-600 transition-colors hover:bg-[#f0f2ff] hover:text-[#5668dc] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/5 dark:text-slate-200"><Play className="h-3.5 w-3.5" />Evaluate</button><input ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv,.json" className="hidden" onChange={selectDocument} /></div>
      </div>
      <div className="relative mt-4 grid gap-2 sm:grid-cols-3"><div className="flex items-center gap-2 rounded-xl border border-white/80 bg-white/72 px-3 py-2 text-[12px] font-medium tracking-[-0.012em] text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"><Sparkles className="h-3.5 w-3.5 text-[#7889ef]" />Prepare assessment</div><div className="flex items-center gap-2 rounded-xl border border-white/80 bg-white/72 px-3 py-2 text-[12px] font-medium tracking-[-0.012em] text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"><ScanLine className="h-3.5 w-3.5 text-[#5a9878]" />Evaluate responses</div><div className="flex items-center gap-2 rounded-xl border border-white/80 bg-white/72 px-3 py-2 text-[12px] font-medium tracking-[-0.012em] text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"><span className="grid h-3.5 w-3.5 place-items-center rounded bg-[#fff2d8] text-[9px] text-[#bf8122]">3</span>Review results</div></div>
    </section>
  );
}
