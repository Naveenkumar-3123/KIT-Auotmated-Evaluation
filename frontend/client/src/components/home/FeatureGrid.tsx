/**
 * STYLE: Reference-led staggered cards — clean white capability cards form a deliberate OCR cluster beneath a small scanning companion.
 */
import { FileScan, FileText, ShieldCheck } from "lucide-react";
const features = [
  { icon: FileScan, label: "Answer analysis", title: "Understand answers", description: "Read handwritten or typed responses and associate each answer with the correct question.", tone: "bg-[#fff6df] text-[#c98a1d]" },
  { icon: FileText, label: "AI evaluation", title: "Evaluate responses", description: "Assess student answers against the answer key, rubric, and allocated marks.", tone: "bg-[#eef1ff] text-[#6578e7]" },
  { icon: ShieldCheck, label: "Teacher review", title: "Review results", description: "Review marks, evaluation details, and responses that need teacher attention.", tone: "bg-[#edf9f3] text-[#508d70]" },
];

export function FeatureGrid() {
  return (
    <section aria-label="Core capabilities" className="relative z-10 mt-3 w-full max-w-none px-0 sm:mt-4">
      <div className="relative pt-6">
        <div className="grid gap-4 sm:grid-cols-3 sm:items-start lg:gap-5">
          {features.map((feature, index) => {
            const Icon = feature.icon;
            return (
              <article key={feature.title} className={`scan-rule relative min-h-[230px] rounded-[18px] border border-white/95 bg-white/92 p-6 shadow-[0_16px_34px_rgba(60,70,135,0.12)] backdrop-blur-xl transition-transform duration-200 hover:-translate-y-1 dark:border-white/10 dark:bg-[#222638]/92 ${index === 1 ? "sm:min-h-[262px]" : "sm:mt-9"}`} style={{ fontFamily: "Inter, sans-serif", fontSize: "16px", fontWeight: 500, lineHeight: 1.18, letterSpacing: "-0.2px" }}>
                <span className={`inline-flex h-8 w-8 items-center justify-center rounded-xl ${feature.tone} dark:bg-white/10 dark:text-[#b5bfff]`}><Icon className="h-4 w-4" /></span>
                <h2 className="mt-5 text-[16px] font-medium leading-[1.18] tracking-[-0.2px] text-[#171827] dark:text-white">{feature.title}</h2>
                <p className="mt-2.5 max-w-[255px] text-[16px] font-medium leading-[1.18] tracking-[-0.2px] text-slate-600 dark:text-slate-300">{feature.description}</p>
                <p className="type-overline mt-5 text-slate-400 dark:text-slate-500">{feature.label}</p>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
