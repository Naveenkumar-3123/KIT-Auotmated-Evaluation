/** STYLE: EvalAI key review — teacher validates the AI-parsed answer key before it becomes the locked grading source. */
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeftRight,
  CheckCircle2,
  ChevronRight,
  FileQuestion,
  ImageIcon,
  Layers,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  deleteQuestionDiagram,
  fetchDiagramBlobUrl,
  reviewAnswerKey,
  uploadQuestionDiagram,
  type AnswerKeyDiagram,
  type AnswerKeyPayload,
  type QuestionOption,
  type QuestionReviewEdit,
} from "@/api/answerKeys";

interface AnswerKeyReviewStepProps {
  payload: AnswerKeyPayload;
  onConfirmed: (payload: AnswerKeyPayload) => void;
  onReupload: () => void;
}

const isFieldEmpty = (val: unknown): boolean => {
  if (val === undefined || val === null) return true;
  if (typeof val === "string") return val.trim() === "";
  if (typeof val === "number") return val <= 0 || isNaN(val);
  return false;
};

export function AnswerKeyReviewStep({ payload, onConfirmed, onReupload }: AnswerKeyReviewStepProps) {
  const [questions, setQuestions] = useState(payload.questions);
  const [saving, setSaving] = useState(false);
  const [diagramUrls, setDiagramUrls] = useState<Record<string, string>>({});
  // Track active option tab ('a' | 'b') for choice questions
  const [activeOptions, setActiveOptions] = useState<Record<number, string>>({});
  const [uploadingDiagramQ, setUploadingDiagramQ] = useState<string | null>(null);

  // Original question numbers mapped by question ID or ordinal
  const [originalQMap] = useState<Record<string, number>>(() => {
    const map: Record<string, number> = {};
    for (const q of payload.questions) {
      map[q.id || String(q.question_number)] = q.question_number;
    }
    return map;
  });

  // Track which fields have been confirmed / saved in valid state
  const [savedFieldSet, setSavedFieldSet] = useState<Set<string>>(() => {
    const set = new Set<string>();
    for (const q of payload.questions) {
      if (q.options && q.options.length > 0) {
        for (const opt of q.options) {
          const pfx = `q-${q.question_number}-opt-${opt.option_code.toLowerCase()}`;
          if (!isFieldEmpty(opt.question_text)) set.add(`${pfx}-statement`);
          if (!isFieldEmpty(opt.maximum_marks)) set.add(`${pfx}-marks`);
          if (!isFieldEmpty(opt.expected_answer_text)) set.add(`${pfx}-expected`);
        }
      } else {
        const pfx = `q-${q.question_number}`;
        if (!isFieldEmpty(q.question_text)) set.add(`${pfx}-statement`);
        if (!isFieldEmpty(q.maximum_marks)) set.add(`${pfx}-marks`);
        if (!isFieldEmpty(q.expected_answer_text)) set.add(`${pfx}-expected`);
      }
    }
    return set;
  });

  const [saveNotice, setSaveNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    setQuestions(payload.questions);
    // Initialize active option to 'a' for all choice questions
    const initialOpts: Record<number, string> = {};
    for (const q of payload.questions) {
      if (q.options && q.options.length > 0) {
        initialOpts[q.question_number] = q.options[0]?.option_code?.toLowerCase() || "a";
      }
    }
    setActiveOptions(initialOpts);
  }, [payload]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const next: Record<string, string> = {};
      for (const question of payload.questions) {
        for (const diagram of question.diagrams) {
          try {
            next[diagram.id] = await fetchDiagramBlobUrl(payload.answer_key.id, diagram.id);
          } catch {
            /* image preview is best-effort */
          }
        }
      }
      if (!cancelled) setDiagramUrls(next);
    };
    void load();
    return () => {
      cancelled = true;
      Object.values(diagramUrls).forEach((url) => URL.revokeObjectURL(url));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload]);

  const changeQuestionNumber = (currentQNum: number, newNum: number) => {
    if (isNaN(newNum) || newNum <= 0) return;
    setQuestions((current) =>
      current.map((q) => {
        if (q.question_number !== currentQNum) return q;
        return {
          ...q,
          question_number: newNum,
          diagrams: q.diagrams.map((d) => ({
            ...d,
            diagram_code: d.diagram_code.replace(new RegExp(`Q${currentQNum}`, "i"), `Q${newNum}`),
          })),
        };
      })
    );
    setActiveOptions((prev) => {
      const next = { ...prev };
      if (next[currentQNum]) {
        next[newNum] = next[currentQNum];
        delete next[currentQNum];
      }
      return next;
    });
  };

  const swapOptions = (questionNumber: number) => {
    setQuestions((current) =>
      current.map((q) => {
        if (q.question_number !== questionNumber || !q.options || q.options.length < 2) return q;
        const optA = q.options.find((o) => o.option_code.toLowerCase() === "a") || q.options[0];
        const optB = q.options.find((o) => o.option_code.toLowerCase() === "b") || q.options[1];

        const newOptA: QuestionOption = {
          ...optB,
          option_code: "a",
          option_title: `Option (A) - ${optB.question_text || optB.option_title}`.slice(0, 100),
        };
        const newOptB: QuestionOption = {
          ...optA,
          option_code: "b",
          option_title: `Option (B) - ${optA.question_text || optA.option_title}`.slice(0, 100),
        };

        const swappedDiagrams = q.diagrams.map((d) => {
          const code = d.option_code?.toLowerCase();
          if (code === "a") {
            return {
              ...d,
              option_code: "b",
              diagram_code: d.diagram_code.replace(/\(a\)/i, "(b)"),
            };
          } else if (code === "b") {
            return {
              ...d,
              option_code: "a",
              diagram_code: d.diagram_code.replace(/\(b\)/i, "(a)"),
            };
          }
          return d;
        });

        const updatedOptions = [newOptA, newOptB];
        const synchedExpected = `============================================================\nOPTION (a): ${newOptA.question_text || newOptA.option_title} (${newOptA.maximum_marks} Marks)\n============================================================\n\n${newOptA.expected_answer_text}\n\n============================================================\nOPTION (b): ${newOptB.question_text || newOptB.option_title} (${newOptB.maximum_marks} Marks)\n============================================================\n\n${newOptB.expected_answer_text}`;
        const synchedQuestion = `Option (a): ${newOptA.question_text} [OR] Option (b): ${newOptB.question_text}`;

        return {
          ...q,
          options: updatedOptions,
          diagrams: swappedDiagrams,
          question_text: synchedQuestion,
          expected_answer_text: synchedExpected,
        };
      })
    );
    toast("Swapped options", { description: `Swapped Option (A) and Option (B) for Q${questionNumber}.` });
  };

  const handleUploadDiagram = async (questionNumber: number, file: File, optionCode?: string) => {
    const uploadKey = `${questionNumber}-${optionCode || "main"}`;
    setUploadingDiagramQ(uploadKey);
    try {
      const res = await uploadQuestionDiagram(payload.answer_key.id, questionNumber, file, optionCode);
      const newDiagram = res.diagram;
      const blobUrl = URL.createObjectURL(file);
      setDiagramUrls((prev) => ({ ...prev, [newDiagram.id]: blobUrl }));
      setQuestions((current) =>
        current.map((q) => {
          if (q.question_number !== questionNumber) return q;
          return {
            ...q,
            diagrams: [...q.diagrams, newDiagram],
          };
        })
      );
      toast.success("Diagram attached", { description: `Successfully attached diagram ${newDiagram.diagram_code}.` });
    } catch (err: any) {
      toast.error("Failed to upload diagram", { description: err?.message || "Check file format and retry." });
    } finally {
      setUploadingDiagramQ(null);
    }
  };

  const handleDeleteDiagram = async (questionNumber: number, diagramId: string) => {
    try {
      await deleteQuestionDiagram(payload.answer_key.id, diagramId);
      setQuestions((current) =>
        current.map((q) => {
          if (q.question_number !== questionNumber) return q;
          return {
            ...q,
            diagrams: q.diagrams.filter((d) => d.id !== diagramId),
          };
        })
      );
      toast.success("Diagram removed", { description: "The diagram has been removed from this question." });
    } catch (err: any) {
      toast.error("Failed to delete diagram", { description: err?.message || "Please try again." });
    }
  };

  const setQuestionActiveOption = (qNum: number, optCode: string) => {
    setActiveOptions((prev) => ({ ...prev, [qNum]: optCode.toLowerCase() }));
  };

  const editSingleQuestion = (
    questionNumber: number,
    patch: Partial<{ questionText: string; expected: string; maxMarks: number; keywords: string }>,
  ) => {
    setQuestions((current) =>
      current.map((q) => {
        if (q.question_number !== questionNumber) return q;
        const updated = { ...q, ...patchMap(patch, q) };
        const pfx = `q-${questionNumber}`;
        if (patch.questionText !== undefined && isFieldEmpty(patch.questionText)) {
          setSavedFieldSet((prev) => {
            const next = new Set(prev);
            next.delete(`${pfx}-statement`);
            return next;
          });
        }
        if (patch.maxMarks !== undefined && isFieldEmpty(patch.maxMarks)) {
          setSavedFieldSet((prev) => {
            const next = new Set(prev);
            next.delete(`${pfx}-marks`);
            return next;
          });
        }
        if (patch.expected !== undefined && isFieldEmpty(patch.expected)) {
          setSavedFieldSet((prev) => {
            const next = new Set(prev);
            next.delete(`${pfx}-expected`);
            return next;
          });
        }
        return updated;
      }),
    );
  };

  const editOption = (questionNumber: number, optCode: string, patch: Partial<QuestionOption>) => {
    const pfx = `q-${questionNumber}-opt-${optCode.toLowerCase()}`;
    if (patch.question_text !== undefined && isFieldEmpty(patch.question_text)) {
      setSavedFieldSet((prev) => {
        const next = new Set(prev);
        next.delete(`${pfx}-statement`);
        return next;
      });
    }
    if (patch.maximum_marks !== undefined && isFieldEmpty(patch.maximum_marks)) {
      setSavedFieldSet((prev) => {
        const next = new Set(prev);
        next.delete(`${pfx}-marks`);
        return next;
      });
    }
    if (patch.expected_answer_text !== undefined && isFieldEmpty(patch.expected_answer_text)) {
      setSavedFieldSet((prev) => {
        const next = new Set(prev);
        next.delete(`${pfx}-expected`);
        return next;
      });
    }

    setQuestions((current) =>
      current.map((q) => {
        if (q.question_number !== questionNumber || !q.options) return q;
        const updatedOptions = q.options.map((opt) =>
          opt.option_code.toLowerCase() === optCode.toLowerCase() ? { ...opt, ...patch } : opt,
        );
        const optA = updatedOptions.find((o) => o.option_code.toLowerCase() === "a");
        const optB = updatedOptions.find((o) => o.option_code.toLowerCase() === "b");
        const synchedExpected =
          optA && optB
            ? `============================================================\nOPTION (a): ${optA.question_text || optA.option_title} (${optA.maximum_marks} Marks)\n============================================================\n\n${optA.expected_answer_text}\n\n============================================================\nOPTION (b): ${optB.question_text || optB.option_title} (${optB.maximum_marks} Marks)\n============================================================\n\n${optB.expected_answer_text}`
            : q.expected_answer_text;
        const synchedQuestion =
          optA && optB
            ? `Option (a): ${optA.question_text} [OR] Option (b): ${optB.question_text}`
            : q.question_text;
        return {
          ...q,
          options: updatedOptions,
          question_text: synchedQuestion,
          expected_answer_text: synchedExpected,
        };
      }),
    );
  };

  /**
   * Helper that evaluates field visual status:
   * 1. If empty => RED with "Required — Please fill in" indication.
   * 2. If filled, but not saved => RED/Rose warning border until user clicks Save.
   * 3. Once filled AND saved => NORMAL appearance (restored border & background).
   */
  const getFieldStatus = (fieldKey: string, currentValue: unknown) => {
    const empty = isFieldEmpty(currentValue);
    const isSaved = savedFieldSet.has(fieldKey);

    if (empty) {
      return {
        isRed: true,
        label: "Required — please fill in",
        classes:
          "border-2 border-red-500 bg-red-50/80 text-red-950 placeholder:text-red-400 focus:border-red-600 focus:ring-2 focus:ring-red-200 dark:bg-red-950/30 dark:border-red-500 dark:text-red-100 shadow-[0_0_12px_rgba(239,68,68,0.22)]",
      };
    }

    if (!isSaved) {
      return {
        isRed: true,
        label: "Filled — Click Save to confirm",
        classes:
          "border-2 border-rose-500 bg-rose-50/70 text-slate-900 focus:border-rose-600 focus:ring-2 focus:ring-rose-200 dark:bg-rose-950/20 dark:border-rose-500 dark:text-white shadow-[0_0_10px_rgba(244,63,94,0.18)]",
      };
    }

    return {
      isRed: false,
      label: null,
      classes:
        "border border-[#dfe4ff] bg-white/90 text-slate-900 focus:border-[#7788ff] dark:bg-white/5 dark:text-white",
    };
  };

  const handleSaveAndValidate = async (andConfirm = false) => {
    setSaving(true);
    setSaveNotice(null);

    const missingFields: string[] = [];
    const newlySaved = new Set<string>();

    for (const q of questions) {
      if (q.options && q.options.length > 0) {
        for (const opt of q.options) {
          const pfx = `q-${q.question_number}-opt-${opt.option_code.toLowerCase()}`;
          if (isFieldEmpty(opt.question_text)) {
            missingFields.push(`Q${q.question_number} Option (${opt.option_code.toUpperCase()}) Question Statement`);
          } else {
            newlySaved.add(`${pfx}-statement`);
          }
          if (isFieldEmpty(opt.maximum_marks)) {
            missingFields.push(`Q${q.question_number} Option (${opt.option_code.toUpperCase()}) Marks`);
          } else {
            newlySaved.add(`${pfx}-marks`);
          }
          if (isFieldEmpty(opt.expected_answer_text)) {
            missingFields.push(`Q${q.question_number} Option (${opt.option_code.toUpperCase()}) Expected Answer`);
          } else {
            newlySaved.add(`${pfx}-expected`);
          }
        }
      } else {
        const pfx = `q-${q.question_number}`;
        if (isFieldEmpty(q.question_text)) {
          missingFields.push(`Q${q.question_number} Question Statement`);
        } else {
          newlySaved.add(`${pfx}-statement`);
        }
        if (isFieldEmpty(q.maximum_marks)) {
          missingFields.push(`Q${q.question_number} Marks`);
        } else {
          newlySaved.add(`${pfx}-marks`);
        }
        if (isFieldEmpty(q.expected_answer_text)) {
          missingFields.push(`Q${q.question_number} Expected Answer`);
        } else {
          newlySaved.add(`${pfx}-expected`);
        }
      }
    }

    // Commit all validly filled fields into saved state (this changes them from red to normal!)
    setSavedFieldSet(newlySaved);

    if (missingFields.length > 0) {
      setSaving(false);
      setSaveNotice({
        type: "error",
        text: `${missingFields.length} required field(s) are still empty. Please complete all fields highlighted in red.`,
      });
      return;
    }

    setSaveNotice({
      type: "success",
      text: "All question fields and marks are verified and saved!",
    });

    try {
      const edits: QuestionReviewEdit[] = questions.map((question) => {
        const orig = originalQMap[question.id] || originalQMap[String(question.question_number)] || question.question_number;
        return {
          question_number: orig,
          new_question_number: question.question_number !== orig ? question.question_number : undefined,
          question_text: typeof question.question_text === "string" ? question.question_text : undefined,
          expected_answer_text: question.expected_answer_text,
          maximum_marks: Number(question.maximum_marks),
          keywords: question.keywords,
          mandatory_terms: question.mandatory_terms,
          options: question.options,
        };
      });
      const result = await reviewAnswerKey(payload.answer_key.id, { edits, confirm: andConfirm });
      onConfirmed(result);
    } catch (err: any) {
      setSaveNotice({
        type: "error",
        text: `Error saving answer key: ${err?.message || "Please try again."}`,
      });
    } finally {
      setSaving(false);
    }
  };

  // Calculate total missing / pending red fields
  let totalMissingFields = 0;
  for (const q of questions) {
    if (q.options && q.options.length > 0) {
      for (const opt of q.options) {
        const pfx = `q-${q.question_number}-opt-${opt.option_code.toLowerCase()}`;
        if (getFieldStatus(`${pfx}-statement`, opt.question_text).isRed) totalMissingFields++;
        if (getFieldStatus(`${pfx}-marks`, opt.maximum_marks).isRed) totalMissingFields++;
        if (getFieldStatus(`${pfx}-expected`, opt.expected_answer_text).isRed) totalMissingFields++;
      }
    } else {
      const pfx = `q-${q.question_number}`;
      if (getFieldStatus(`${pfx}-statement`, q.question_text).isRed) totalMissingFields++;
      if (getFieldStatus(`${pfx}-marks`, q.maximum_marks).isRed) totalMissingFields++;
      if (getFieldStatus(`${pfx}-expected`, q.expected_answer_text).isRed) totalMissingFields++;
    }
  }

  const warnings = payload.answer_key.parse_error ? [payload.answer_key.parse_error] : [];

  return (
    <section className="space-y-4">
      {/* Header Banner */}
      <div className="rounded-[24px] border border-white/85 bg-white/70 p-5 shadow-[0_14px_34px_rgba(60,70,135,0.08)] backdrop-blur-xl dark:border-white/10 dark:bg-[#202334]/72 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="inline-flex items-center gap-1.5 rounded-full bg-[#eef1ff] px-2.5 py-1 text-[11px] font-bold text-[#5d6ee0] dark:bg-white/10 dark:text-[#b2bcff]">
              <Sparkles className="h-3.5 w-3.5 text-[#5d6ee0]" />
              AI Extracted Answer Key & Rubric
            </div>
            <h2 className="type-section-title mt-2 text-[#171827] dark:text-white">
              {questions.length} questions detected across document
            </h2>
            <p className="type-support mt-1 text-slate-500 dark:text-slate-400">
              Review statements, expected answers, marks, and attached diagrams below. Unrecognized fields are
              highlighted in <span className="font-extrabold text-red-600">RED</span> — fill them and click Save to
              restore normal state.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => handleSaveAndValidate(false)}
              className="type-button inline-flex items-center gap-1.5 rounded-xl border border-[#dfe4ff] bg-white px-3.5 py-2 text-[12px] font-bold text-[#5d6ee0] shadow-xs hover:border-[#7788ff] dark:bg-[#1f2237] dark:text-[#a0afff]"
            >
              <Save className="h-4 w-4" />
              Save Changes
            </button>
            <button
              type="button"
              onClick={onReupload}
              className="type-button rounded-xl border border-[#dfe4ff] bg-white/80 px-3 py-2 text-[12px] font-bold text-slate-600 hover:border-[#7788ff] dark:bg-white/5 dark:text-slate-300"
            >
              Re-upload key
            </button>
          </div>
        </div>

        {/* Live Notification Bar */}
        {saveNotice && (
          <div
            className={`mt-4 flex items-start gap-2.5 rounded-2xl px-4 py-3 text-[12px] font-bold shadow-xs ${
              saveNotice.type === "error"
                ? "border border-red-300 bg-red-50 text-red-800 dark:bg-red-950/40 dark:border-red-800 dark:text-red-200"
                : "border border-emerald-300 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-200"
            }`}
          >
            {saveNotice.type === "error" ? (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
            ) : (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            )}
            <span>{saveNotice.text}</span>
          </div>
        )}

        {totalMissingFields > 0 && !saveNotice && (
          <div className="mt-4 flex items-center justify-between rounded-2xl border border-red-200 bg-red-50/80 px-4 py-2.5 text-[12px] font-bold text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300">
            <div className="flex items-center gap-2">
              <span className="flex h-2.5 w-2.5 rounded-full bg-red-500 animate-pulse" />
              <span>{totalMissingFields} required field(s) require attention (marked in red).</span>
            </div>
            <span className="text-[11px] font-normal text-red-600 dark:text-red-400">
              Fill and click "Save Changes" to confirm.
            </span>
          </div>
        )}

        {warnings.length > 0 && (
          <div className="mt-4 flex items-start gap-2 rounded-2xl bg-[#fdf3e7] px-3.5 py-3 text-[12px] font-semibold text-[#a4691c]">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {warnings.join(" · ")}
          </div>
        )}
      </div>

      {/* Questions List */}
      <div className="space-y-4">
        {questions.map((question) => {
          const hasOptions = Array.isArray(question.options) && question.options.length > 0;
          const currentOptCode = (activeOptions[question.question_number] || "a").toLowerCase();
          const currentOpt = hasOptions
            ? question.options!.find((o) => o.option_code.toLowerCase() === currentOptCode) || question.options![0]
            : null;

          // Check if this question has any red fields
          let qHasRed = false;
          if (hasOptions) {
            for (const opt of question.options!) {
              const pfx = `q-${question.question_number}-opt-${opt.option_code.toLowerCase()}`;
              if (
                getFieldStatus(`${pfx}-statement`, opt.question_text).isRed ||
                getFieldStatus(`${pfx}-marks`, opt.maximum_marks).isRed ||
                getFieldStatus(`${pfx}-expected`, opt.expected_answer_text).isRed
              ) {
                qHasRed = true;
                break;
              }
            }
          } else {
            const pfx = `q-${question.question_number}`;
            qHasRed =
              getFieldStatus(`${pfx}-statement`, question.question_text).isRed ||
              getFieldStatus(`${pfx}-marks`, question.maximum_marks).isRed ||
              getFieldStatus(`${pfx}-expected`, question.expected_answer_text).isRed;
          }

          // Filter diagrams strictly matching the active option (or all diagrams if single question)
          const matchedDiagrams = hasOptions
            ? question.diagrams.filter(
                (d) =>
                  !d.option_code ||
                  d.option_code.toLowerCase() === currentOptCode ||
                  d.diagram_code.toLowerCase().includes(`(${currentOptCode})`),
              )
            : question.diagrams;

          return (
            <article
              key={question.id || question.question_number}
              className={`rounded-[22px] border bg-white/75 p-5 shadow-sm backdrop-blur-xl transition hover:shadow-md dark:bg-[#202334]/75 ${
                qHasRed
                  ? "border-red-300 dark:border-red-900/60 shadow-[0_0_15px_rgba(239,68,68,0.06)]"
                  : "border-white/85 dark:border-white/10"
              }`}
            >
              {/* Question Header */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3 dark:border-white/5">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1 rounded-lg bg-[#171b32] px-2 py-0.5 text-white shadow-xs" title="Click to edit Question Number">
                    <span className="text-[11px] font-bold text-slate-300">Q</span>
                    <input
                      type="number"
                      min={1}
                      value={question.question_number}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        if (!isNaN(val) && val > 0) {
                          changeQuestionNumber(question.question_number, val);
                        }
                      }}
                      className="w-10 bg-transparent text-center text-[12px] font-extrabold text-white outline-none focus:bg-white/20 rounded px-0.5"
                    />
                  </div>
                  <span className="rounded-full bg-[#eef1ff] px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#6679e8] dark:bg-white/10 dark:text-[#b2bcff]">
                    {hasOptions ? "Choice (Either / Or)" : question.answer_type}
                  </span>
                  <span className="text-[11px] font-semibold text-slate-500">
                    {hasOptions ? (
                      <span className="text-[#5d6ee0] font-bold">16 Marks per option</span>
                    ) : (
                      `${question.maximum_marks} Marks · ${question.concepts.length || 1} concept rubric`
                    )}
                  </span>
                  {qHasRed && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-red-300 bg-red-100/90 px-2.5 py-0.5 text-[10px] font-extrabold text-red-700 dark:bg-red-950/60 dark:border-red-800 dark:text-red-300">
                      <AlertCircle className="h-3 w-3 text-red-600" />
                      Incomplete Fields
                    </span>
                  )}
                </div>

                {/* Option Tabs Switcher for Choice Questions */}
                {hasOptions && (
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => swapOptions(question.question_number)}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50/90 px-2.5 py-1 text-xs font-bold text-indigo-700 hover:bg-indigo-100 transition shadow-xs dark:border-indigo-500/30 dark:bg-indigo-950/40 dark:text-indigo-300"
                      title="Swap Option (A) and Option (B) content & diagrams"
                    >
                      <ArrowLeftRight className="h-3.5 w-3.5" />
                      <span>Swap (A) ⇄ (B)</span>
                    </button>
                    <div className="flex items-center gap-1.5 rounded-xl bg-slate-100 p-1 dark:bg-white/5">
                      {question.options!.map((opt) => {
                        const optCode = opt.option_code.toLowerCase();
                        const isActive = optCode === currentOptCode;
                        const optPfx = `q-${question.question_number}-opt-${optCode}`;
                        const optHasRed =
                          getFieldStatus(`${optPfx}-statement`, opt.question_text).isRed ||
                          getFieldStatus(`${optPfx}-marks`, opt.maximum_marks).isRed ||
                          getFieldStatus(`${optPfx}-expected`, opt.expected_answer_text).isRed;

                        return (
                          <button
                            key={opt.option_code}
                            type="button"
                            onClick={() => setQuestionActiveOption(question.question_number, optCode)}
                            className={`flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-bold transition ${
                              isActive
                                ? "bg-[#5d6ee0] text-white shadow-sm"
                                : "text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
                            }`}
                          >
                            <Layers className="h-3 w-3" />
                            <span>Option ({opt.option_code.toUpperCase()})</span>
                            {optHasRed && (
                              <span
                                className={`h-2 w-2 rounded-full ${
                                  isActive ? "bg-red-300 ring-2 ring-white" : "bg-red-500 animate-pulse"
                                }`}
                                title="Contains incomplete fields"
                              />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {/* Card Body */}
              {hasOptions && currentOpt ? (
                /* Choice Question View: Detailed Option Editor */
                (() => {
                  const pfx = `q-${question.question_number}-opt-${currentOpt.option_code.toLowerCase()}`;
                  const stmtStatus = getFieldStatus(`${pfx}-statement`, currentOpt.question_text);
                  const marksStatus = getFieldStatus(`${pfx}-marks`, currentOpt.maximum_marks);
                  const expStatus = getFieldStatus(`${pfx}-expected`, currentOpt.expected_answer_text);

                  return (
                    <div className="mt-3.5 grid gap-4 lg:grid-cols-[1fr_260px]">
                      <div className="space-y-3">
                        <div>
                          <div className="flex items-center justify-between">
                            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                              Option ({currentOpt.option_code.toUpperCase()}) Question Statement
                            </label>
                            {stmtStatus.label && (
                              <span className="inline-flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-[10px] font-extrabold text-red-700 dark:bg-red-950/60 dark:text-red-300">
                                <AlertCircle className="h-3 w-3 text-red-600" />
                                {stmtStatus.label}
                              </span>
                            )}
                          </div>
                          <input
                            value={String(currentOpt.question_text ?? "")}
                            onChange={(e) =>
                              editOption(question.question_number, currentOpt.option_code, {
                                question_text: e.target.value,
                              })
                            }
                            placeholder={`[Required] Enter Option (${currentOpt.option_code.toUpperCase()}) question statement`}
                            className={`mt-1 w-full rounded-xl px-3.5 py-2 text-[13px] font-semibold outline-none transition ${stmtStatus.classes}`}
                          />
                        </div>

                        <div>
                          <div className="flex items-center justify-between">
                            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                              Option ({currentOpt.option_code.toUpperCase()}) Expected Reference Answer
                            </label>
                            {expStatus.label ? (
                              <span className="inline-flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-[10px] font-extrabold text-red-700 dark:bg-red-950/60 dark:text-red-300">
                                <AlertCircle className="h-3 w-3 text-red-600" />
                                {expStatus.label}
                              </span>
                            ) : (
                              <span className="text-[10px] font-semibold text-[#5d6ee0]">
                                16 Marks Total Rubric
                              </span>
                            )}
                          </div>
                          <textarea
                            value={currentOpt.expected_answer_text}
                            onChange={(e) =>
                              editOption(question.question_number, currentOpt.option_code, {
                                expected_answer_text: e.target.value,
                              })
                            }
                            rows={7}
                            placeholder={`[Required] Expected reference answer, derivations, key steps for Option (${currentOpt.option_code.toUpperCase()})`}
                            className={`mt-1 w-full rounded-xl p-3 text-[12px] leading-5 font-mono outline-none transition ${expStatus.classes}`}
                          />
                        </div>

                        {/* Keywords & Rubric Concepts */}
                        <div className="space-y-2">
                          <div className="flex gap-2">
                            <label className="flex items-center gap-1.5 text-[11px] font-bold text-slate-500">
                              Option Marks
                              <input
                                type="number"
                                min={0}
                                value={Number(currentOpt.maximum_marks)}
                                onChange={(e) =>
                                  editOption(question.question_number, currentOpt.option_code, {
                                    maximum_marks: Number(e.target.value),
                                  })
                                }
                                className={`w-20 rounded-lg px-2 py-1.5 text-right text-[12px] font-bold outline-none ${marksStatus.classes}`}
                              />
                            </label>
                            <input
                              value={(currentOpt.keywords || []).join(", ")}
                              onChange={(e) =>
                                editOption(question.question_number, currentOpt.option_code, {
                                  keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                                })
                              }
                              placeholder={`Option (${currentOpt.option_code.toUpperCase()}) technical keywords (comma separated)`}
                              className="min-w-0 flex-1 rounded-lg border border-[#dfe4ff] bg-white/90 px-2.5 py-1.5 text-[12px] outline-none focus:border-[#7788ff]"
                            />
                          </div>

                          {currentOpt.expected_concepts && currentOpt.expected_concepts.length > 0 && (
                            <div className="rounded-xl bg-[#f4f6ff] p-2.5 text-[11px] font-semibold text-[#45509e] dark:bg-white/5 dark:text-[#b2bcff]">
                              <p className="font-bold mb-1 text-[10px] uppercase tracking-wider text-[#6679e8]">
                                Option ({currentOpt.option_code.toUpperCase()}) Rubric Breakdown:
                              </p>
                              <div className="grid gap-1 sm:grid-cols-2">
                                {currentOpt.expected_concepts.map((c) => (
                                  <div key={c.concept_code} className="flex items-center gap-1.5 text-[11px]">
                                    <span className="font-extrabold text-[#5d6ee0]">{c.concept_code}:</span>
                                    <span className="truncate">{c.description}</span>
                                    <span className="text-slate-400">({c.maximum_marks}m)</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Diagrams Column for Active Option */}
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                            Option ({currentOpt.option_code.toUpperCase()}) Diagram
                          </p>
                          <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-[#dfe4ff] bg-white px-2 py-1 text-[10px] font-bold text-[#5d6ee0] hover:bg-[#f0f3ff] transition dark:border-white/10 dark:bg-white/5 dark:text-[#a0afff]">
                            <Upload className="h-3 w-3" />
                            <span>{uploadingDiagramQ === `${question.question_number}-${currentOptCode}` ? "Uploading…" : "Add Image"}</span>
                            <input
                              type="file"
                              accept="image/*"
                              disabled={uploadingDiagramQ !== null}
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleUploadDiagram(question.question_number, file, currentOptCode);
                                e.target.value = "";
                              }}
                              className="hidden"
                            />
                          </label>
                        </div>
                        {matchedDiagrams.length > 0 ? (
                          <div className="grid gap-2">
                            {matchedDiagrams.map((diagram) => (
                              <figure
                                key={diagram.id}
                                className="group relative overflow-hidden rounded-xl border border-[#dfe4ff] bg-white/85 shadow-xs dark:border-white/10 dark:bg-[#1a1c2d]"
                              >
                                {diagramUrls[diagram.id] ? (
                                  <img
                                    src={diagramUrls[diagram.id]}
                                    alt={`${diagram.diagram_code} crop`}
                                    className="max-h-40 w-full bg-white object-contain p-2"
                                  />
                                ) : (
                                  <div className="flex h-24 items-center justify-center text-slate-300">
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  </div>
                                )}
                                <figcaption className="flex items-center justify-between border-t border-slate-100 bg-slate-50/80 px-2.5 py-1.5 text-[10px] font-bold text-slate-600 dark:border-white/5 dark:bg-white/5 dark:text-slate-300">
                                  <div className="truncate pr-1">
                                    <div className="flex items-center gap-1">
                                      <ImageIcon className="h-3 w-3 shrink-0 text-[#5d6ee0]" />
                                      <span className="truncate">{diagram.diagram_code}</span>
                                    </div>
                                    {diagram.type_label && (
                                      <p className="mt-0.5 text-[9px] font-normal text-slate-500 truncate">
                                        {diagram.type_label}
                                      </p>
                                    )}
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => handleDeleteDiagram(question.question_number, diagram.id)}
                                    title="Delete diagram"
                                    className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 transition"
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </button>
                                </figcaption>
                              </figure>
                            ))}
                          </div>
                        ) : (
                          <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-[11px] text-slate-400 dark:border-white/10">
                            <ImageIcon className="mx-auto mb-1 h-5 w-5 opacity-40" />
                            <p>No diagram for Option ({currentOpt.option_code.toUpperCase()}).</p>
                            <label className="mt-2 inline-flex cursor-pointer items-center gap-1 rounded-lg bg-[#eef1ff] px-2.5 py-1 text-[11px] font-bold text-[#5d6ee0] hover:bg-[#dfe4ff] transition dark:bg-white/10 dark:text-[#a0afff]">
                              <Upload className="h-3 w-3" />
                              <span>Upload Diagram</span>
                              <input
                                type="file"
                                accept="image/*"
                                disabled={uploadingDiagramQ !== null}
                                onChange={(e) => {
                                  const file = e.target.files?.[0];
                                  if (file) handleUploadDiagram(question.question_number, file, currentOptCode);
                                  e.target.value = "";
                                }}
                                className="hidden"
                              />
                            </label>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })()
              ) : (
                /* Single Question View (e.g. Q1 to Q10) */
                (() => {
                  const pfx = `q-${question.question_number}`;
                  const stmtStatus = getFieldStatus(`${pfx}-statement`, question.question_text);
                  const marksStatus = getFieldStatus(`${pfx}-marks`, question.maximum_marks);
                  const expStatus = getFieldStatus(`${pfx}-expected`, question.expected_answer_text);

                  return (
                    <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_240px]">
                      <div className="space-y-2.5">
                        <div>
                          {stmtStatus.label && (
                            <span className="mb-1 inline-flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-[10px] font-extrabold text-red-700 dark:bg-red-950/60 dark:text-red-300">
                              <AlertCircle className="h-3 w-3 text-red-600" />
                              {stmtStatus.label}
                            </span>
                          )}
                          <input
                            value={String(question.question_text ?? "")}
                            onChange={(event) =>
                              editSingleQuestion(question.question_number, { questionText: event.target.value })
                            }
                            placeholder="Question text"
                            className={`w-full rounded-xl px-3 py-2 text-[13px] font-semibold outline-none ${stmtStatus.classes}`}
                          />
                        </div>

                        <div>
                          {expStatus.label && (
                            <span className="mb-1 inline-flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-[10px] font-extrabold text-red-700 dark:bg-red-950/60 dark:text-red-300">
                              <AlertCircle className="h-3 w-3 text-red-600" />
                              {expStatus.label}
                            </span>
                          )}
                          <textarea
                            value={question.expected_answer_text}
                            onChange={(event) =>
                              editSingleQuestion(question.question_number, { expected: event.target.value })
                            }
                            rows={3}
                            placeholder="Expected answer"
                            className={`w-full rounded-xl px-3 py-2 text-[12px] leading-5 outline-none ${expStatus.classes}`}
                          />
                        </div>

                        <div className="flex gap-2">
                          <label className="flex items-center gap-1.5 text-[11px] font-bold text-slate-500">
                            Max marks
                            <input
                              type="number"
                              min={0}
                              value={Number(question.maximum_marks)}
                              onChange={(event) =>
                                editSingleQuestion(question.question_number, { maxMarks: Number(event.target.value) })
                              }
                              className={`w-20 rounded-lg px-2 py-1.5 text-right text-[12px] font-bold outline-none ${marksStatus.classes}`}
                            />
                          </label>
                          <input
                            value={question.keywords.join(", ")}
                            onChange={(event) =>
                              editSingleQuestion(question.question_number, { keywords: event.target.value })
                            }
                            placeholder="keywords, comma separated"
                            className="min-w-0 flex-1 rounded-lg border border-[#dfe4ff] bg-white/85 px-2.5 py-1.5 text-[12px] outline-none focus:border-[#7788ff]"
                          />
                        </div>
                        {question.parser_uncertainties.length > 0 && (
                          <p className="flex items-start gap-1.5 text-[11px] font-semibold text-[#a4691c]">
                            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                            {question.parser_uncertainties.join(" · ")}
                          </p>
                        )}
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                            Diagrams
                          </p>
                          <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-[#dfe4ff] bg-white px-2 py-1 text-[10px] font-bold text-[#5d6ee0] hover:bg-[#f0f3ff] transition dark:border-white/10 dark:bg-white/5 dark:text-[#a0afff]">
                            <Upload className="h-3 w-3" />
                            <span>{uploadingDiagramQ === `${question.question_number}-main` ? "Uploading…" : "Add Image"}</span>
                            <input
                              type="file"
                              accept="image/*"
                              disabled={uploadingDiagramQ !== null}
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleUploadDiagram(question.question_number, file);
                                e.target.value = "";
                              }}
                              className="hidden"
                            />
                          </label>
                        </div>
                        {question.diagrams.length > 0 ? (
                          <div className="grid gap-2">
                            {question.diagrams.map((diagram) => (
                              <figure
                                key={diagram.id}
                                className="group relative overflow-hidden rounded-xl border border-[#dfe4ff] bg-white/85 shadow-xs dark:border-white/10"
                              >
                                {diagramUrls[diagram.id] ? (
                                  <img
                                    src={diagramUrls[diagram.id]}
                                    alt={`${diagram.diagram_code} crop`}
                                    className="max-h-32 w-full object-contain"
                                  />
                                ) : (
                                  <div className="flex h-20 items-center justify-center text-slate-300">
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  </div>
                                )}
                                <figcaption className="flex items-center justify-between border-t border-slate-100 bg-slate-50/80 px-2 py-1 text-[10px] font-bold text-slate-500">
                                  <div className="truncate pr-1">
                                    <div className="flex items-center gap-1">
                                      <ImageIcon className="h-3 w-3 text-[#5d6ee0]" />
                                      <span>{diagram.diagram_code}</span>
                                    </div>
                                    {diagram.type_label && (
                                      <p className="mt-0.5 text-[9px] font-normal text-slate-400 truncate">
                                        {diagram.type_label}
                                      </p>
                                    )}
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => handleDeleteDiagram(question.question_number, diagram.id)}
                                    title="Delete diagram"
                                    className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 transition"
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </button>
                                </figcaption>
                              </figure>
                            ))}
                          </div>
                        ) : (
                          <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-[11px] text-slate-400 dark:border-white/10">
                            <ImageIcon className="mx-auto mb-1 h-5 w-5 opacity-40" />
                            <p>No diagram for this question.</p>
                            <label className="mt-2 inline-flex cursor-pointer items-center gap-1 rounded-lg bg-[#eef1ff] px-2.5 py-1 text-[11px] font-bold text-[#5d6ee0] hover:bg-[#dfe4ff] transition dark:bg-white/10 dark:text-[#a0afff]">
                              <Upload className="h-3 w-3" />
                              <span>Upload Diagram</span>
                              <input
                                type="file"
                                accept="image/*"
                                disabled={uploadingDiagramQ !== null}
                                onChange={(e) => {
                                  const file = e.target.files?.[0];
                                  if (file) handleUploadDiagram(question.question_number, file);
                                  e.target.value = "";
                                }}
                                className="hidden"
                              />
                            </label>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })()
              )}
            </article>
          );
        })}
      </div>

      {/* Action Footer */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-3">
        <button
          type="button"
          disabled={saving}
          onClick={onReupload}
          className="type-button inline-flex items-center gap-1.5 rounded-2xl border border-red-200 bg-red-50/90 px-4 py-2.5 text-xs font-bold text-red-600 shadow-sm transition hover:bg-red-100 hover:text-red-700 disabled:opacity-50 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
        >
          <Trash2 className="h-4 w-4" />
          Delete & Re-upload Key
        </button>
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={saving}
            onClick={() => handleSaveAndValidate(false)}
            className="type-button inline-flex items-center gap-1.5 rounded-2xl border border-[#dfe4ff] bg-white px-5 py-2.5 text-xs font-bold text-[#5d6ee0] shadow-sm hover:border-[#7788ff] dark:bg-[#202334] dark:text-[#a0afff]"
          >
            <Save className="h-4 w-4" />
            Save Changes
          </button>
          <button
            disabled={saving}
            onClick={() => handleSaveAndValidate(true)}
            className="type-button inline-flex items-center gap-2 rounded-2xl bg-[#7788ff] px-6 py-2.5 text-xs font-bold text-white shadow-[0_10px_24px_rgba(119,136,255,0.3)] transition hover:opacity-95 disabled:opacity-70"
          >
            {saving ? "Locking answer key…" : "Confirm & Save Answer Key"}
            <CheckCircle2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </section>
  );
}

function patchMap(
  patch: { questionText?: string; expected?: string; maxMarks?: number; keywords?: string },
  _original: AnswerKeyPayload["questions"][number],
) {
  const mapped: Record<string, unknown> = {};
  if (patch.questionText !== undefined) mapped.question_text = patch.questionText;
  if (patch.expected !== undefined) mapped.expected_answer_text = patch.expected;
  if (patch.maxMarks !== undefined) mapped.maximum_marks = patch.maxMarks;
  if (patch.keywords !== undefined)
    mapped.keywords = patch.keywords
      .split(",")
      .map((term) => term.trim())
      .filter(Boolean);
  return mapped;
}
