/** STYLE: EvalAI guide — the uploaded EvalBot mascot gives concise, contextual setup guidance without becoming a chat surface. */
const assistantUrl = "/manus-storage/evalbot-guide_70c167ba.png";

interface GuideBotProps { message: string; detail: string; }

export function GuideBot({ message, detail }: GuideBotProps) {
  return <aside aria-label="EvalAI setup guidance" className="relative min-h-[330px] overflow-hidden rounded-[24px] border border-white/85 bg-[linear-gradient(145deg,rgba(255,255,255,0.88),rgba(244,246,255,0.62))] p-5 shadow-[0_14px_34px_rgba(60,70,135,0.09)] backdrop-blur-xl dark:border-white/10 dark:bg-[#222638]/75 lg:min-h-full">
    <div className="relative z-20 max-w-[230px] rounded-2xl border border-white/90 bg-white/88 px-3.5 py-3 shadow-[0_10px_24px_rgba(67,76,139,0.12)] backdrop-blur dark:border-white/10 dark:bg-[#292d42]/88">
      <p className="type-overline text-[#7484e6]">EvalAI guide</p>
      <p className="mt-1.5 text-[13px] font-semibold leading-[1.35] tracking-[-0.018em] text-[#171827] dark:text-white">{message}</p>
      <p className="mt-2 text-[11px] font-medium leading-4 text-slate-500 dark:text-slate-400">{detail}</p>
    </div>
    <div className="ocr-focus-frame pointer-events-none absolute -bottom-2 left-1/2 h-[290px] w-[290px] -translate-x-1/2 overflow-hidden opacity-95 sm:bottom-0 lg:bottom-auto lg:top-[62%] lg:h-[340px] lg:w-[340px] lg:-translate-y-1/2"><img src={assistantUrl} alt="EvalBot assessment guide" className="absolute bottom-0 left-1/2 h-[250px] w-[250px] -translate-x-1/2 scale-[1.15] object-contain mix-blend-multiply drop-shadow-[0_20px_26px_rgba(56,65,125,0.18)] lg:h-[310px] lg:w-[310px] lg:scale-[1.18]" /></div>
  </aside>;
}
