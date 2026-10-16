/**
 * STYLE: Reference-led soft glass hero — EvalAI assessment introduction, grading assistant, and a calm premium open canvas.
 */
import { ArrowRight, CheckCircle2, ScanText } from "lucide-react";
import { useLocation } from "wouter";

const assistantUrl = "/manus-storage/evalbot-guide_70c167ba.png";

export function HeroSection() {
  const [, setLocation] = useLocation();
  return (
    <section className="relative min-h-[780px] overflow-hidden rounded-[25px] border border-white/85 bg-[linear-gradient(110deg,rgba(255,255,255,0.92),rgba(249,251,255,0.64)_55%,rgba(255,253,240,0.66))] px-7 py-11 shadow-[0_22px_55px_rgba(62,72,139,0.12)] dark:border-white/10 dark:bg-[linear-gradient(110deg,rgba(33,36,53,0.96),rgba(28,31,46,0.72))] sm:min-h-[438px] sm:px-11 sm:py-12 lg:min-h-[472px] lg:px-[8.5%]">
      <div className="pointer-events-none absolute inset-0 opacity-60 [background-image:radial-gradient(circle_at_21%_23%,rgba(162,178,255,0.22),transparent_18%),radial-gradient(circle_at_86%_76%,rgba(195,208,255,0.28),transparent_22%),linear-gradient(116deg,transparent_32%,rgba(141,155,241,0.11)_32.1%,transparent_32.3%)]" />
      <div className="relative max-w-[560px] pt-2 sm:pt-5">
        <div className="type-overline inline-flex items-center gap-2 rounded-full border border-[#dce1ff] bg-white/75 px-3 py-1.5 text-[#6475e3] shadow-sm dark:border-[#8695fc]/20 dark:bg-white/5 dark:text-[#b9c1ff]"><ScanText className="h-3.5 w-3.5" /> AI-powered assessment</div>
        <h1 className="type-display mt-6 max-w-[535px] text-[#171827] dark:text-white">Turn answer sheets into <span className="text-[#6376e8] dark:text-[#abb5ff]">meaningful results.</span></h1>
        <p className="type-body mt-6 max-w-[465px] text-slate-600 dark:text-slate-300">Evaluate handwritten and typed answers against your marking scheme with AI-assisted grading, review, and result generation.</p>
        <div className="mt-8 flex flex-wrap items-center gap-3"><button type="button" onClick={() => setLocation("/compare")} className="type-button inline-flex items-center gap-2 rounded-full bg-[#171b32] px-5 py-3.5 text-white shadow-[0_9px_20px_rgba(23,27,50,0.17)] transition-all duration-150 hover:-translate-y-px hover:bg-[#30386d] active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:bg-[#9aa8ff] dark:text-[#151827]">Start Evaluation <ArrowRight className="h-4 w-4" /></button><a href="#actions" className="type-button hidden rounded-full border border-slate-200 bg-white/75 px-5 py-3.5 text-slate-600 transition-colors hover:bg-white hover:text-[#171827] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] dark:border-white/10 dark:bg-white/5 dark:text-white sm:block">See How It Works</a></div>
        <div className="mt-7 hidden flex-wrap gap-x-4 gap-y-2 text-[12px] font-medium tracking-[-0.012em] text-slate-500 dark:text-slate-300 sm:flex">{["Upload papers", "Evaluate answers", "Review results"].map((item) => <span key={item} className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-[#589377]" />{item}</span>)}</div>
      </div>
      <div className="ocr-focus-frame pointer-events-none absolute bottom-0 right-[3%] h-[305px] w-[315px] overflow-hidden sm:right-[8%] sm:h-[350px] sm:w-[355px] lg:bottom-auto lg:left-[75%] lg:right-auto lg:top-1/2 lg:-translate-x-1/2 lg:-translate-y-1/2">
        <div className="absolute left-7 top-4 z-20 rounded-2xl border border-white/90 bg-white/90 px-3.5 py-2.5 shadow-[0_12px_30px_rgba(67,76,139,0.14)] backdrop-blur dark:border-white/10 dark:bg-[#292d42]/90"><p className="type-overline text-[#7484e6]">Your guide</p><p className="mt-1 text-[12px] font-semibold tracking-[-0.018em] text-[#171827] dark:text-white">Ready to evaluate some answers?</p></div>
        <img src={assistantUrl} alt="EvalBot, the AI assessment guide" className="absolute bottom-0 left-1/2 z-10 h-[292px] w-[292px] -translate-x-1/2 scale-[1.16] object-contain mix-blend-multiply drop-shadow-[0_24px_29px_rgba(56,65,125,0.2)] sm:h-[348px] sm:w-[348px]" />
        <div className="absolute bottom-6 right-0 z-20 rounded-2xl border border-white/90 bg-white/90 px-3.5 py-2.5 shadow-[0_12px_28px_rgba(67,76,139,0.15)] backdrop-blur dark:border-white/10 dark:bg-[#292d42]/90"><p className="type-overline text-slate-500 dark:text-slate-400">Evaluation engine</p><div className="mt-1.5 flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-emerald-500" /><span className="text-[12px] font-semibold tracking-[-0.015em] text-[#171827] dark:text-white">Ready to evaluate</span></div></div>
      </div>
    </section>
  );
}
