/** STYLE: EvalAI upload step — a generous glass dropzone, clear format rules, and honest frontend-only upload feedback. */
import { CheckCircle2, FileArchive, FileText, Trash2, UploadCloud } from "lucide-react";
import { ChangeEvent, DragEvent, useRef } from "react";
import { UploadState } from "./types";

interface UploadStepProps {
  heading: string;
  description: string;
  requirement: string;
  example: string;
  accept: string;
  acceptedLabel: string;
  upload: UploadState;
  completionDetail: string;
  /** Overrides for the busy card — e.g. the AI parse phase after the upload itself finished. */
  busyTitle?: string;
  busySublabel?: string;
  busyProgressPercent?: number;
  onChoose: (file: File) => void;
  onRemove: () => void;
}

export function UploadStep({ heading, description, requirement, example, accept, acceptedLabel, upload, completionDetail, busyTitle, busySublabel, busyProgressPercent, onChoose, onRemove }: UploadStepProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const choose = (event: ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; if (file) onChoose(file); event.target.value = ""; };
  const drop = (event: DragEvent<HTMLDivElement>) => { event.preventDefault(); const file = event.dataTransfer.files?.[0]; if (file) onChoose(file); };
  const icon = acceptedLabel === ".ZIP" ? FileArchive : FileText;
  const Icon = icon;
  return <section className="flex h-full flex-col rounded-[24px] border border-white/85 bg-white/64 p-5 shadow-[0_14px_34px_rgba(60,70,135,0.08)] backdrop-blur-xl dark:border-white/10 dark:bg-[#202334]/72 sm:p-6">
    <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between"><div><p className="type-overline text-[#7182ef]">Step</p><h2 className="type-section-title mt-1.5 text-[#171827] dark:text-white">{heading}</h2><p className="type-support mt-2 max-w-xl text-slate-500 dark:text-slate-400">{description}</p></div><div className="rounded-xl border border-[#dfe4ff] bg-[#f4f5ff] px-3 py-2 text-right dark:border-[#8797ff]/20 dark:bg-[#7587f2]/10"><p className="type-overline text-[#687ae7]">Required format</p><p className="mt-1 text-sm font-extrabold text-[#171827] dark:text-white">{acceptedLabel}</p></div></div>
    <div className="mt-5 rounded-2xl border border-[#e0e5ff] bg-[#f7f8ff]/75 p-4 dark:border-white/10 dark:bg-white/[0.035]"><p className="text-[12px] font-semibold text-[#171827] dark:text-white">{requirement}</p><p className="mt-1 font-mono text-[11px] text-[#687ae7]">Example: {example}</p></div>
    {upload.status === "complete" ? (
      <div className="mt-5 flex flex-col gap-3 rounded-2xl border border-[#b8ddc8] bg-[#f0faf4]/88 p-4 dark:border-[#589377]/30 dark:bg-[#4d916e]/10 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-[#5b9a78] text-white">
            <CheckCircle2 className="h-5 w-5" />
          </span>
          <div>
            <p className="text-sm font-extrabold text-[#171827] dark:text-white">{upload.name}</p>
            <p className="mt-0.5 text-xs font-medium text-[#4f8f70] dark:text-[#98d1af]">{completionDetail} · Upload complete</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="type-button rounded-xl border border-[#b8ddc8] bg-white/80 px-3.5 py-2 text-xs font-bold text-[#4f8f70] shadow-sm transition hover:bg-white dark:border-[#589377]/30 dark:bg-white/5 dark:text-[#98d1af]"
          >
            Change file
          </button>
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Delete ${upload.name}`}
            className="type-button inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-red-50/90 px-3.5 py-2 text-xs font-bold text-red-600 shadow-sm transition hover:bg-red-100 hover:text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete file
          </button>
        </div>
      </div>
    ) : (
      <div onDragOver={(event) => event.preventDefault()} onDrop={drop} className="mt-5 grid min-h-[250px] flex-1 place-items-center rounded-2xl border border-dashed border-[#bdc8ff] bg-[linear-gradient(135deg,rgba(246,248,255,0.9),rgba(255,255,255,0.75))] p-6 text-center dark:border-[#8797ff]/30 dark:bg-white/[0.025]">
        <div className="w-full max-w-sm mx-auto">
          {upload.status === "uploading" ? (
            <div className="flex flex-col items-center">
              <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#eef1ff] text-[#6679e7] dark:bg-[#7587f2]/15 dark:text-[#b7c0ff] animate-pulse">
                <UploadCloud className="h-6 w-6" />
              </span>
              <p className="mt-4 text-sm font-extrabold text-[#171827] dark:text-white">{busyTitle ?? `Uploading ${upload.name}`}</p>
              <div className="mx-auto mt-3.5 flex w-full max-w-[280px] items-center gap-3">
                <div className="h-3 flex-1 overflow-hidden rounded-full bg-[#dfe4ff]/80 dark:bg-white/10 p-[2px] shadow-inner">
                  <div className="h-full rounded-full bg-gradient-to-r from-[#6366f1] via-[#7486ed] to-[#818cf8] transition-all duration-300 ease-out shadow-sm" style={{ width: `${Math.min(100, Math.max(0, busyProgressPercent ?? 0))}%` }} />
                </div>
                <span className="text-xs font-bold font-mono text-[#6366f1] dark:text-[#a5b4fc] min-w-[38px] text-right">{Math.min(100, Math.max(0, Math.round(busyProgressPercent ?? 0)))}%</span>
              </div>
              <p className="mt-2.5 text-xs font-medium text-slate-500 dark:text-slate-400">{busySublabel ?? "Preparing your assessment files…"}</p>
              <button
                type="button"
                onClick={onRemove}
                className="mt-4 inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-white/90 px-3.5 py-1.5 text-xs font-bold text-red-600 shadow-sm transition hover:bg-red-50 dark:border-red-500/20 dark:bg-white/5 dark:text-red-300"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Cancel & Delete
              </button>
            </div>
          ) : (
            <>
              <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#eef1ff] text-[#6679e7] dark:bg-[#7587f2]/15 dark:text-[#b7c0ff]">
                <Icon className="h-6 w-6" />
              </span>
              <p className="mt-4 text-sm font-extrabold text-[#171827] dark:text-white">Drop your file here</p>
              <p className="mt-1 text-xs font-medium text-slate-500 dark:text-slate-400">or</p>
              <button type="button" onClick={() => inputRef.current?.click()} className="type-button mt-3 inline-flex items-center gap-2 rounded-full bg-[#171b32] px-4 py-2.5 text-white transition-colors hover:bg-[#30386d] dark:bg-[#9aa8ff] dark:text-[#151827]">
                <UploadCloud className="h-3.5 w-3.5" />
                Choose file
              </button>
            </>
          )}
        </div>
      </div>
    )}
    <input ref={inputRef} id="file-upload-input" data-testid="file-upload-input" type="file" className="hidden" accept={accept} onChange={choose} />
  </section>;
}
