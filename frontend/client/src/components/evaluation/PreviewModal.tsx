import { createPortal } from "react-dom";
import { FileText, X } from "lucide-react";

export function PreviewModal({ open, onClose, title, subtitle, fileName, contentUrl }: { open: boolean; onClose: () => void; title: string; subtitle: string; fileName: string; contentUrl?: string | null }) {
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button type="button" onClick={onClose} aria-label="Close preview" className="fixed inset-0 bg-[#151827]/40 backdrop-blur-sm" />
      <section role="dialog" aria-modal="true" aria-label={title} className="relative z-10 flex max-h-[90vh] w-full max-w-[820px] flex-col overflow-hidden rounded-[28px] border border-white/80 bg-[#fdfdff] p-5 shadow-[0_30px_80px_rgba(30,35,80,0.32)] dark:border-white/10 dark:bg-[#222638] sm:p-7">
        <div className="flex items-start justify-between gap-5">
          <div>
            <p className="type-overline text-[#7484e6]">Document preview</p>
            <h2 className="type-page-title mt-2 text-[#171827] dark:text-white">{title}</h2>
            <p className="type-support mt-2 text-slate-500 dark:text-slate-400">{subtitle}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-full border border-slate-200 bg-white p-2 text-slate-500 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"><X className="h-4 w-4" /></button>
        </div>
        {contentUrl ? (
          <iframe src={contentUrl} title={title} className="mt-6 min-h-[380px] flex-1 rounded-[20px] border border-dashed border-[#c9d2ff] bg-white dark:border-[#8797ff]/30" />
        ) : (
          <div className="mt-6 flex min-h-[230px] items-center justify-center rounded-[20px] border border-dashed border-[#c9d2ff] bg-[linear-gradient(135deg,#f7f8ff,#eef1ff)] p-6 text-center dark:border-[#8797ff]/30 dark:bg-white/[0.04]">
            <div>
              <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-[#7182ef] shadow-sm dark:bg-white/10"><FileText className="h-6 w-6" /></span>
              <p className="mt-4 text-[15px] font-semibold text-[#171827] dark:text-white">Document preview placeholder</p>
              <p className="mt-2 max-w-[330px] text-[13px] leading-5 text-slate-500 dark:text-slate-400">The document will appear here once preview rendering is connected to the file service.</p>
            </div>
          </div>
        )}
        <div className="mt-5 rounded-xl border border-[#e4e8ff] bg-[#f8f9ff] px-4 py-3 text-[13px] text-slate-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-300">
          <span className="font-semibold text-[#171827] dark:text-white">File: </span>{fileName}
        </div>
      </section>
    </div>,
    document.body
  );
}
