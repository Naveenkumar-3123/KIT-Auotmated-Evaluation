/** STYLE: EvalAI setup progress — lightweight numbered steps show forward momentum without reading as a checkout flow. */
import { Check } from "lucide-react";

const labels = ["Answer papers", "Answer key", "Key review", "Assessment details", "Evaluation rules"];
interface ConfigureProgressProps { activeStep: number; onSelectStep: (step: number) => void; }

export function ConfigureProgress({ activeStep, onSelectStep }: ConfigureProgressProps) {
  return <nav aria-label="Configuration progress" className="overflow-x-auto rounded-2xl border border-white/70 bg-white/48 px-3 py-3 backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.04]">
    <ol className="flex min-w-[860px] items-center justify-between gap-2">
      {labels.map((label, index) => {
        const step = index + 1;
        const complete = activeStep > step;
        const active = activeStep === step || (activeStep > 5 && step === 5);
        return <li key={label} className="flex min-w-0 flex-1 items-center gap-2.5"><button type="button" onClick={() => complete && onSelectStep(step)} disabled={!complete} aria-current={active ? "step" : undefined} className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-extrabold transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] ${complete ? "bg-[#5b9a78] text-white" : active ? "bg-[#171b32] text-white shadow-[0_6px_14px_rgba(23,27,50,0.16)] dark:bg-[#9aa8ff] dark:text-[#151827]" : "border border-slate-200 bg-white/75 text-slate-400 dark:border-white/10 dark:bg-white/5"}`}>{complete ? <Check className="h-3.5 w-3.5" /> : step}</button><span className={`whitespace-nowrap text-[11px] font-semibold tracking-[-0.012em] ${active ? "text-[#171827] dark:text-white" : complete ? "text-[#4f8f70] dark:text-[#98d1af]" : "text-slate-400 dark:text-slate-500"}`}>{label}</span>{index < labels.length - 1 && <span className={`ml-auto h-px flex-1 ${complete ? "bg-[#8fc7aa]" : "bg-slate-200 dark:bg-white/10"}`} />}</li>;
      })}
    </ol>
  </nav>;
}
