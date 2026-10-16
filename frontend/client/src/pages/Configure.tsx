/** STYLE: EvalAI configuration flow — staged, bot-guided assessment setup reuses the existing lavender glass dashboard system. */
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import { useLocation } from "wouter";
import { createAssessment, deleteAnswerKey, deleteStudentSubmissions, updateAssessmentDetails, uploadStudentZip } from "@/api/assessments";
import { getAnswerKey, uploadAnswerKey, type AnswerKeyPayload } from "@/api/answerKeys";
import { finalizeAssessment, savePolicies, type PoliciesPayload } from "@/api/policies";
import { AnswerKeyReviewStep } from "@/components/configure/AnswerKeyReviewStep";
import { AssessmentDetailsStep } from "@/components/configure/AssessmentDetailsStep";
import { ConfigurationSummary } from "@/components/configure/ConfigurationSummary";
import { ConfigureProgress } from "@/components/configure/ConfigureProgress";
import { GuideBot } from "@/components/configure/GuideBot";
import { StrictnessStep } from "@/components/configure/StrictnessStep";
import { UploadStep } from "@/components/configure/UploadStep";
import { classOptions } from "@/components/teacher/teaching-data";
import { useTeacherProfile } from "@/contexts/TeacherProfileContext";
import { DiagramRuleMode, DiagramRuleRange, QuestionDiagramRule, QuestionRule, QuestionWordCountRule, StrictnessLevel, StrictnessMode, StrictnessRange, UploadState, WordCountMode, WordCountRange, getRangeCoverage, resolveRangeOverlap } from "@/components/configure/types";

const initialUpload: UploadState = { name: null, status: "idle" };
const DRAFT_KEY = "evalai-draft-assessment";
const defaultQuestions: QuestionRule[] = Array.from({ length: 10 }, (_, index) => ({ question: index + 1, level: "moderate" }));
const defaultQuestionWordCounts: QuestionWordCountRule[] = Array.from({ length: 10 }, (_, index) => ({ question: index + 1, minWords: 100, shortfallWords: 20, marksDeducted: 1 }));
const defaultQuestionDiagrams: QuestionDiagramRule[] = Array.from({ length: 10 }, (_, index) => ({ question: index + 1, required: false, minimumDiagrams: 1, missingDiagramDeductions: [1] }));

export default function Configure() {
  const { teacher, availableSubjectsForClass } = useTeacherProfile();
  const [, setLocation] = useLocation();
  const [activeStep, setActiveStep] = useState(1);
  const [assessmentId, setAssessmentId] = useState<string | null>(() => { try { return window.sessionStorage.getItem(DRAFT_KEY); } catch { return null; } });
  const [papers, setPapers] = useState<UploadState>(initialUpload);
  const [papersDetail, setPapersDetail] = useState("No archive uploaded yet");
  const [answerKey, setAnswerKey] = useState<UploadState>(initialUpload);
  const [keyPayload, setKeyPayload] = useState<AnswerKeyPayload | null>(null);
  const [keyParsing, setKeyParsing] = useState(false);
  const [keyProgress, setKeyProgress] = useState<string | null>(null);
  const [keyProgressPct, setKeyProgressPct] = useState<number | null>(null);
  const [passPercentage, setPassPercentage] = useState(40);
  const [savingConfig, setSavingConfig] = useState(false);
  const [classNameValue, setClassNameValue] = useState("");
  const [subjectValue, setSubjectValue] = useState("");
  const [customClasses, setCustomClasses] = useState<string[]>([]);
  const [strictnessMode, setStrictnessMode] = useState<StrictnessMode>(null);
  const [ranges, setRanges] = useState<StrictnessRange[]>([]);
  const [rangeDraft, setRangeDraft] = useState<Omit<StrictnessRange, "id">>({ from: 1, to: 5, level: "moderate" });
  const [questions, setQuestions] = useState<QuestionRule[]>(defaultQuestions);
  const [wordCountMode, setWordCountMode] = useState<WordCountMode>(null);
  const [wordCountRanges, setWordCountRanges] = useState<WordCountRange[]>([]);
  const [wordCountRangeDraft, setWordCountRangeDraft] = useState<Omit<WordCountRange, "id">>({ from: 1, to: 5, minWords: 100, shortfallWords: 20, marksDeducted: 1 });
  const [questionWordCounts, setQuestionWordCounts] = useState<QuestionWordCountRule[]>(defaultQuestionWordCounts);
  const [diagramMode, setDiagramMode] = useState<DiagramRuleMode>(null);
  const [diagramRanges, setDiagramRanges] = useState<DiagramRuleRange[]>([]);
  const [diagramRangeDraft, setDiagramRangeDraft] = useState<Omit<DiagramRuleRange, "id">>({ from: 1, to: 5, required: true, minimumDiagrams: 1, missingDiagramDeductions: [1] });
  const [questionDiagrams, setQuestionDiagrams] = useState<QuestionDiagramRule[]>(defaultQuestionDiagrams);
  const [saved, setSaved] = useState(false);

  const startPapersUpload = async (file: File) => {
    const isZip = file.name.toLowerCase().endsWith(".zip");
    const isPdf = file.name.toLowerCase().endsWith(".pdf");
    if (!isZip && !isPdf) {
      toast("Unsupported file format", { description: "Please choose a PDF answer paper or a ZIP archive containing student answer sheets." });
      return;
    }
    setSaved(false);
    setPapers({ name: file.name, status: "uploading" });
    setPapersDetail(isPdf ? "Scanning and validating student PDF…" : "Scanning and validating the archive…");
    try {
      let id = assessmentId;
      if (!id) {
        const created = await createAssessment({ title: "Untitled assessment" });
        id = created.assessment.id;
        setAssessmentId(id);
        try { window.sessionStorage.setItem(DRAFT_KEY, id); } catch { /* session state is optional */ }
      }
      let result;
      try {
        result = await uploadStudentZip(id, file);
      } catch (err: any) {
        // If cached assessment ID was deleted or from a previous DB session (404 Not Found), create a fresh one and retry
        const isNotFound =
          err?.status === 404 ||
          String(err?.message || "").includes("404") ||
          String(err?.message || "").toLowerCase().includes("not found");
        if (isNotFound) {
          try { window.sessionStorage.removeItem(DRAFT_KEY); } catch { /* session state is optional */ }
          const created = await createAssessment({ title: "Untitled assessment" });
          id = created.assessment.id;
          setAssessmentId(id);
          try { window.sessionStorage.setItem(DRAFT_KEY, id); } catch { /* session state is optional */ }
          result = await uploadStudentZip(id, file);
        } else {
          throw err;
        }
      }
      const accepted = result.valid;
      const rejected = result.invalid;
      const rejectedEntries = (result.students || []).filter(
        (s) => s.status !== "valid" && s.status !== "duplicate"
      );
      const rejectionReasons = rejectedEntries
        .map((s) => `${s.file_name}: ${s.reason || s.status}`)
        .join("; ");

      if (accepted === 0) {
        setPapers(initialUpload);
        setPapersDetail("No valid student papers detected");
        toast.error("Student papers could not be accepted", {
          description: rejectionReasons || "No valid student PDFs found. Name each PDF with the student roll number (e.g., 24CSE011.pdf).",
        });
        return;
      }

      setPapersDetail(`${accepted} student file${accepted === 1 ? "" : "s"} ready${rejected ? ` · ${rejected} rejected` : ""}`);
      setPapers({ name: file.name, status: "complete" });
      setActiveStep(2);
      if (rejected > 0) {
        toast.warning("Answer papers uploaded with warnings", {
          description: `${accepted} student file${accepted === 1 ? "" : "s"} ready. ${rejected} rejected: ${rejectionReasons}`,
        });
      } else {
        toast.success("Answer papers uploaded", {
          description: `${accepted} student file${accepted === 1 ? "" : "s"} ready for evaluation.`,
        });
      }
    } catch (error) {
      setPapers(initialUpload); setPapersDetail("No archive uploaded yet");
      toast.error("Answer papers could not be processed", { description: error instanceof Error ? error.message : "Check the archive and try again." });
    }
  };
  const detectedQuestionNumbers = (keyPayload?.questions && keyPayload.questions.length > 0)
    ? Array.from(new Set(keyPayload.questions.map((q) => q.question_number))).sort((a, b) => a - b)
    : questions.map((q) => q.question).length > 0
    ? questions.map((q) => q.question).sort((a, b) => a - b)
    : Array.from({ length: 10 }, (_, i) => i + 1);

  const questionCount = detectedQuestionNumbers.length;

  useEffect(() => {
    if (!keyPayload || !keyPayload.questions || keyPayload.questions.length === 0) return;
    const qNums = Array.from(new Set(keyPayload.questions.map((q) => q.question_number))).sort((a, b) => a - b);
    setQuestions(qNums.map((question) => ({ question, level: "moderate" as StrictnessLevel })));
    setQuestionWordCounts(qNums.map((question) => ({ question, minWords: 100, shortfallWords: 20, marksDeducted: 1 })));
    setQuestionDiagrams(qNums.map((question) => ({ question, required: false, minimumDiagrams: 1, missingDiagramDeductions: [1] })));

    const minQ = qNums[0];
    const maxQ = qNums[qNums.length - 1];
    setRangeDraft({ from: minQ, to: maxQ, level: "moderate" });
    setWordCountRangeDraft({ from: minQ, to: maxQ, minWords: 100, shortfallWords: 20, marksDeducted: 1 });
    setDiagramRangeDraft({ from: minQ, to: maxQ, required: true, minimumDiagrams: 1, missingDiagramDeductions: [1] });
  }, [keyPayload]);
  const startKeyUpload = async (file: File) => {
    const allowed = [".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp"];
    if (!allowed.some((ext) => file.name.toLowerCase().endsWith(ext))) { toast("Unsupported answer key", { description: "Upload the key as PDF, DOC, DOCX or an image." }); return; }
    if (!assessmentId) { toast("Upload answer papers first", { description: "Step 1 creates the assessment that owns this key." }); return; }
    setSaved(false); setAnswerKey({ name: file.name, status: "uploading" }); setKeyParsing(false);
    setKeyProgress("Uploading file to server (0%)…");
    setKeyProgressPct(0);
    let keepWaiting = false;
    try {
      const accepted = await uploadAnswerKey(assessmentId, file, (percent) => {
        setKeyProgress(percent < 100 ? `Uploading file to server (${percent}%)…` : "Upload finished — starting AI parser…");
        setKeyProgressPct(Math.min(99, percent));
      });
      const keyId = accepted.answer_key.id;
      setKeyParsing(true);
      setKeyProgress("File uploaded — AI parser is reading each section…");
      setKeyProgressPct(5);
      // Big multi-page keys parse many VLM batches and can take several minutes.
      // Poll patiently, survive transient network hiccups, and surface live
      // progress instead of failing with a scary error at the two-minute mark.
      const softDeadline = Date.now() + 15 * 60_000;
      const hardDeadline = softDeadline + 30 * 60_000;
      const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
      const pollOnce = async (): Promise<AnswerKeyPayload | null> => {
        try {
          return await getAnswerKey(keyId);
        } catch { return null; } // transient error — keep polling
      };
      let payload = await pollOnce();
      const applyProgress = (progress?: { done: number; total: number; percent?: number; message?: string } | null) => {
        if (!progress) {
          setKeyProgress("The AI parser is reading each section…");
          setKeyProgressPct((prev) => (prev && prev > 10 ? prev : 10));
          return;
        }
        if (progress.percent !== undefined) {
          setKeyProgressPct(progress.percent);
          setKeyProgress(progress.message ?? `Parsed ${progress.done} of ${progress.total} sections (${progress.percent}%)…`);
        } else if (progress.total > 0) {
          const calculatedPct = Math.min(98, Math.max(10, Math.round((progress.done / progress.total) * 100)));
          setKeyProgressPct(calculatedPct);
          setKeyProgress(`Parsed ${progress.done} of ${progress.total} sections (${calculatedPct}%)…`);
        }
      };
      while (payload && payload.answer_key.status === "parsing" && Date.now() < softDeadline) {
        applyProgress(payload.answer_key.progress);
        await sleep(1500);
        payload = await pollOnce();
      }
      if (payload && payload.answer_key.status === "parsing") {
        // Still parsing after 15 minutes — do NOT fail. Keep the card in its
        // parsing state and keep polling quietly in the background.
        keepWaiting = true;
        toast("Large answer key is still parsing", { description: "Sections are being extracted in the background. Stay on this page — the review step opens automatically when it finishes." });
        setKeyParsing(true);
        void (async () => {
          let waiting: AnswerKeyPayload | null = payload;
          while (waiting && waiting.answer_key.status === "parsing" && Date.now() < hardDeadline) {
            applyProgress(waiting.answer_key.progress);
            await sleep(3000);
            waiting = await pollOnce();
          }
          setKeyParsing(false);
          setKeyProgress(null);
          setKeyProgressPct(null);
          if (waiting && waiting.answer_key.status === "failed") {
            setAnswerKey(initialUpload);
            toast("Answer key could not be processed", { description: waiting.answer_key.parse_error || "The AI parser could not read this key." });
            return;
          }
          if (waiting && waiting.answer_key.status !== "parsing") {
            setKeyPayload(waiting);
            setAnswerKey({ name: file.name, status: "complete" });
            setActiveStep(3);
            toast("Answer key parsed", { description: `${waiting.questions.length} questions detected — review them before continuing.` });
          }
        })();
        return;
      }
      if (!payload) throw new Error("Could not read the parse status — check the connection and try again.");
      if (payload.answer_key.status === "failed") throw new Error(payload.answer_key.parse_error || "The AI parser could not read this key.");
      setKeyPayload(payload);
      setAnswerKey({ name: file.name, status: "complete" });
      setActiveStep(3);
      toast("Answer key parsed", { description: `${payload.questions.length} questions detected — review them before continuing.` });
    } catch (error) {
      if (!keepWaiting) setAnswerKey(initialUpload);
      toast("Answer key could not be processed", { description: error instanceof Error ? error.message : "Try a different file." });
    } finally {
      if (!keepWaiting) { setKeyParsing(false); setKeyProgress(null); setKeyProgressPct(null); }
    }
  };
  const profileClasses = [...classOptions.filter((item) => teacher?.departmentIds.includes(item.departmentId)).map((item) => item.name), ...customClasses];
  const profileSubjects = availableSubjectsForClass(classNameValue);
  const updateClass = (value: string) => { setSaved(false); setClassNameValue(value); if (subjectValue && !availableSubjectsForClass(value).includes(subjectValue)) setSubjectValue(""); if (value && subjectValue && availableSubjectsForClass(value).includes(subjectValue)) setActiveStep(5); };
  const updateSubject = (value: string) => { setSaved(false); setSubjectValue(value); if (value && classNameValue) setActiveStep(5); };
  const addClass = (value: string) => { const option = value.trim(); if (!option) return; setCustomClasses((options) => options.includes(option) ? options : [...options, option]); updateClass(option); toast("Class added", { description: `${option} is selected for this assessment.` }); };
  const totalQuestionCount = detectedQuestionNumbers.length;
  const changeMode = (mode: Exclude<StrictnessMode, null>) => { setSaved(false); setStrictnessMode(mode); };
  const addRange = () => {
    const id = `${rangeDraft.from}-${rangeDraft.to}-${Date.now()}`;
    const resolved = resolveRangeOverlap(ranges, rangeDraft);
    const updated = [...resolved, { ...rangeDraft, id }].sort((a, b) => a.from - b.from);
    setRanges(updated);
    setSaved(false);
    const nextCoverage = getRangeCoverage(updated, detectedQuestionNumbers);
    if (nextCoverage.nextSuggestedRange) {
      setRangeDraft({ ...rangeDraft, from: nextCoverage.nextSuggestedRange.from, to: nextCoverage.nextSuggestedRange.to });
    }
  };
  const questionChange = (question: number, level: StrictnessLevel) => { setSaved(false); setQuestions((rules) => rules.map((rule) => rule.question === question ? { ...rule, level } : rule)); };
  const setAll = (level: StrictnessLevel) => { setSaved(false); setQuestions((rules) => rules.map((rule) => ({ ...rule, level }))); };
  const changeWordCountMode = (mode: Exclude<WordCountMode, null>) => { setSaved(false); setWordCountMode(mode); };
  const addWordCountRange = () => {
    const id = `${wordCountRangeDraft.from}-${wordCountRangeDraft.to}-${Date.now()}`;
    const resolved = resolveRangeOverlap(wordCountRanges, wordCountRangeDraft);
    const updated = [...resolved, { ...wordCountRangeDraft, id }].sort((a, b) => a.from - b.from);
    setWordCountRanges(updated);
    setSaved(false);
    const nextCoverage = getRangeCoverage(updated, detectedQuestionNumbers);
    if (nextCoverage.nextSuggestedRange) {
      setWordCountRangeDraft({
        ...wordCountRangeDraft,
        from: nextCoverage.nextSuggestedRange.from,
        to: nextCoverage.nextSuggestedRange.to,
      });
    }
  };
  const changeQuestionWordCount = (question: number, update: Partial<Omit<QuestionWordCountRule, "question">>) => { setSaved(false); setQuestionWordCounts((rules) => rules.map((rule) => rule.question === question ? { ...rule, ...update } : rule)); };
  const setAllWordCounts = (update: Omit<QuestionWordCountRule, "question">) => { setSaved(false); setQuestionWordCounts((rules) => rules.map((rule) => ({ ...rule, ...update }))); };
  const changeDiagramMode = (mode: Exclude<DiagramRuleMode, null>) => { setSaved(false); setDiagramMode(mode); };
  const addDiagramRange = () => {
    const id = `${diagramRangeDraft.from}-${diagramRangeDraft.to}-${Date.now()}`;
    const resolved = resolveRangeOverlap(diagramRanges, diagramRangeDraft);
    const updated = [...resolved, { ...diagramRangeDraft, id }].sort((a, b) => a.from - b.from);
    setDiagramRanges(updated);
    setSaved(false);
    const nextCoverage = getRangeCoverage(updated, detectedQuestionNumbers);
    if (nextCoverage.nextSuggestedRange) {
      setDiagramRangeDraft({
        ...diagramRangeDraft,
        from: nextCoverage.nextSuggestedRange.from,
        to: nextCoverage.nextSuggestedRange.to,
      });
    }
  };
  const changeQuestionDiagram = (question: number, update: Partial<Omit<QuestionDiagramRule, "question">>) => { setSaved(false); setQuestionDiagrams((rules) => rules.map((rule) => rule.question === question ? { ...rule, ...update } : rule)); };

  const strictnessCoverage = getRangeCoverage(ranges, detectedQuestionNumbers);
  const wordCountCoverage = getRangeCoverage(wordCountRanges, detectedQuestionNumbers);
  const diagramCoverage = getRangeCoverage(diagramRanges, detectedQuestionNumbers);

  const strictnessOk = strictnessMode === "individual" || (strictnessMode === "ranges" && strictnessCoverage.isCovered);
  const wordCountOk = wordCountMode === "individual" || (wordCountMode === "ranges" && wordCountCoverage.isCovered);
  const diagramOk = diagramMode !== "ranges" || diagramCoverage.isCovered;
  const strictnessReady = strictnessOk && wordCountOk && diagramOk && strictnessMode !== null && wordCountMode !== null;
  const guide = activeStep === 1 ? { message: "First, upload your class answer papers.", detail: "Use one ZIP file and name each student document using their roll number." } : activeStep === 2 ? { message: "Great. Now add the answer key.", detail: keyParsing ? `The AI parser is reading your key${keyProgress ? ` (${keyProgress})` : "…"}` : "Upload the official reference solution or marking document for this subject." } : activeStep === 3 ? { message: "Check the parsed questions.", detail: "Correct marks, keywords or diagrams — this becomes the locked grading source." } : activeStep === 4 ? { message: "Which class is this for?", detail: "Pick the class and subject so results land in the right place." } : activeStep === 5 ? { message: "Now let’s configure the evaluation rules.", detail: "Set strictness, word-count deductions, and optional diagram rules by question or range." } : { message: "Everything looks ready.", detail: "Review your setup and save it before continuing to evaluation." };
  const saveConfiguration = async () => {
    if (!assessmentId) { toast("Nothing to save yet", { description: "Upload the answer papers first." }); return; }
    if (!classNameValue || !subjectValue) { toast("Choose class and subject", { description: "Assessment details are required before saving." }); return; }
    if (!strictnessReady) {
      toast("Evaluation rules incomplete", { description: `All ${totalQuestionCount} questions must be covered by rules before proceeding.` });
      return;
    }
    setSavingConfig(true);
    try {
      await updateAssessmentDetails(assessmentId, {
        title: `${classNameValue} · ${subjectValue}`.slice(0, 120),
        class_name: classNameValue,
        subject_name: subjectValue,
        pass_percentage: passPercentage,
      });
      const policiesPayload: PoliciesPayload = {
        strictness: {
          mode: strictnessMode ?? "individual",
          ranges: strictnessMode === "ranges" ? ranges.map((range) => ({ from: range.from, to: range.to, level: range.level })) : undefined,
          questions: strictnessMode === "individual" ? questions.map((rule) => ({ question: rule.question, level: rule.level })) : undefined,
        },
        word_count: {
          mode: wordCountMode ?? "individual",
          ranges: wordCountMode === "ranges" ? wordCountRanges.map((range) => ({ from: range.from, to: range.to, minimum_words: range.minWords, trigger_shortfall_words: range.shortfallWords, marks_deducted: range.marksDeducted })) : undefined,
          questions: wordCountMode === "individual" ? questionWordCounts.map((rule) => ({ question: rule.question, minimum_words: rule.minWords, trigger_shortfall_words: rule.shortfallWords, marks_deducted: rule.marksDeducted })) : undefined,
        },
        diagrams: {
          mode: diagramMode ?? "individual",
          ranges: diagramMode === "ranges" ? diagramRanges.map((range) => ({ from: range.from, to: range.to, required: range.required, minimum_diagrams: range.minimumDiagrams, missing_diagram_deductions: range.missingDiagramDeductions })) : undefined,
          questions: diagramMode === "individual" ? questionDiagrams.map((rule) => ({ question: rule.question, required: rule.required, minimum_diagrams: rule.minimumDiagrams, missing_diagram_deductions: rule.missingDiagramDeductions })) : undefined,
        },
      };
      const savedPolicies = await savePolicies(assessmentId, policiesPayload);
      const finalized = await finalizeAssessment(assessmentId);
      try { localStorage.setItem("evalai-configuration", JSON.stringify({ assessmentId, policyVersion: savedPolicies.policy_version })); } catch { /* local mirror is optional */ }
      setSaved(true);
      try { window.sessionStorage.removeItem(DRAFT_KEY); } catch { /* optional */ }
      toast("Assessment saved", { description: `${finalized.summary?.total ?? 0} student paper${(finalized.summary?.total ?? 0) === 1 ? "" : "s"} ready for evaluation.` });
      setLocation("/evaluation");
    } catch (error) {
      toast("Could not save the assessment", { description: error instanceof Error ? error.message : "Please review your setup and retry." });
    } finally {
      setSavingConfig(false);
    }
  };
  const handleBack = () => {
    if (activeStep > 1) {
      setActiveStep((prev) => prev - 1);
    } else {
      setLocation("/dashboard");
    }
  };

  const [saveStatus, setSaveStatus] = useState<"saved" | "saving" | "unsaved">("saved");

  // Real-time auto-save effect
  useEffect(() => {
    if (!assessmentId) return;
    const timer = setTimeout(async () => {
      setSaveStatus("saving");
      try {
        if (classNameValue || subjectValue) {
          await updateAssessmentDetails(assessmentId, {
            title: classNameValue && subjectValue ? `${classNameValue} · ${subjectValue}`.slice(0, 120) : "Draft Assessment",
            class_name: classNameValue || undefined,
            subject_name: subjectValue || undefined,
            pass_percentage: passPercentage,
          });
        }
        if (keyPayload && keyPayload.questions.length > 0) {
          const policiesPayload: PoliciesPayload = {
            strictness: {
              mode: strictnessMode ?? "individual",
              ranges: strictnessMode === "ranges" ? ranges.map((r) => ({ from: r.from, to: r.to, level: r.level })) : undefined,
              questions: strictnessMode === "individual" ? questions.map((r) => ({ question: r.question, level: r.level })) : undefined,
            },
            word_count: {
              mode: wordCountMode ?? "individual",
              ranges: wordCountMode === "ranges" ? wordCountRanges.map((r) => ({ from: r.from, to: r.to, minimum_words: r.minWords, trigger_shortfall_words: r.shortfallWords, marks_deducted: r.marksDeducted })) : undefined,
              questions: wordCountMode === "individual" ? questionWordCounts.map((r) => ({ question: r.question, minimum_words: r.minWords, trigger_shortfall_words: r.shortfallWords, marks_deducted: r.marksDeducted })) : undefined,
            },
            diagrams: {
              mode: diagramMode ?? "individual",
              ranges: diagramMode === "ranges" ? diagramRanges.map((r) => ({ from: r.from, to: r.to, required: r.required, minimum_diagrams: r.minimumDiagrams, missing_diagram_deductions: r.missingDiagramDeductions })) : undefined,
              questions: diagramMode === "individual" ? questionDiagrams.map((r) => ({ question: r.question, required: r.required, minimum_diagrams: r.minimumDiagrams, missing_diagram_deductions: r.missingDiagramDeductions })) : undefined,
            },
          };
          await savePolicies(assessmentId, policiesPayload);
        }
        setSaveStatus("saved");
      } catch (err) {
        console.warn("Real-time auto-save error:", err);
        setSaveStatus("unsaved");
      }
    }, 1200);

    return () => clearTimeout(timer);
  }, [assessmentId, classNameValue, subjectValue, passPercentage, keyPayload, strictnessMode, ranges, questions, wordCountMode, wordCountRanges, questionWordCounts, diagramMode, diagramRanges, questionDiagrams]);

  const handleRemovePapers = async () => {
    if (assessmentId) {
      try {
        await deleteStudentSubmissions(assessmentId);
      } catch (err) {
        console.warn("Could not delete submissions on server:", err);
      }
    }
    setPapers(initialUpload);
    setPapersDetail("No archive uploaded yet");
    toast("Answer papers deleted", { description: "You can upload a new answer paper PDF or ZIP." });
  };

  const handleRemoveAnswerKey = async () => {
    if (assessmentId) {
      try {
        await deleteAnswerKey(assessmentId);
      } catch (err) {
        console.warn("Could not delete answer key on server:", err);
      }
    }
    setAnswerKey(initialUpload);
    setKeyPayload(null);
    setKeyParsing(false);
    setKeyProgress(null);
    setKeyProgressPct(null);
    setActiveStep(2);
    toast("Answer key deleted", { description: "You can upload a new answer key document." });
  };

  const handleSaveDraft = async () => {
    if (!assessmentId) {
      toast("Upload student papers first", { description: "Student answer sheets must be uploaded to create the assessment draft." });
      return;
    }
    setSavingConfig(true);
    setSaveStatus("saving");
    try {
      if (classNameValue || subjectValue) {
        await updateAssessmentDetails(assessmentId, {
          title: classNameValue && subjectValue ? `${classNameValue} · ${subjectValue}`.slice(0, 120) : "Draft Assessment",
          class_name: classNameValue || undefined,
          subject_name: subjectValue || undefined,
          pass_percentage: passPercentage,
        });
      }
      if (keyPayload && keyPayload.questions.length > 0) {
        const policiesPayload: PoliciesPayload = {
          strictness: {
            mode: strictnessMode ?? "individual",
            ranges: strictnessMode === "ranges" ? ranges.map((range) => ({ from: range.from, to: range.to, level: range.level })) : undefined,
            questions: strictnessMode === "individual" ? questions.map((rule) => ({ question: rule.question, level: rule.level })) : undefined,
          },
          word_count: {
            mode: wordCountMode ?? "individual",
            ranges: wordCountMode === "ranges" ? wordCountRanges.map((range) => ({ from: range.from, to: range.to, minimum_words: range.minWords, trigger_shortfall_words: range.shortfallWords, marks_deducted: range.marksDeducted })) : undefined,
            questions: wordCountMode === "individual" ? questionWordCounts.map((rule) => ({ question: rule.question, minimum_words: rule.minWords, trigger_shortfall_words: rule.shortfallWords, marks_deducted: rule.marksDeducted })) : undefined,
          },
          diagrams: {
            mode: diagramMode ?? "individual",
            ranges: diagramMode === "ranges" ? diagramRanges.map((range) => ({ from: range.from, to: range.to, required: range.required, minimum_diagrams: range.minimumDiagrams, missing_diagram_deductions: range.missingDiagramDeductions })) : undefined,
            questions: diagramMode === "individual" ? questionDiagrams.map((rule) => ({ question: rule.question, required: rule.required, minimum_diagrams: rule.minimumDiagrams, missing_diagram_deductions: rule.missingDiagramDeductions })) : undefined,
          },
        };
        await savePolicies(assessmentId, policiesPayload);
      }
      try { window.sessionStorage.setItem(DRAFT_KEY, assessmentId); } catch { /* optional */ }
      setSaveStatus("saved");
      toast("Draft saved in real time", { description: "Your assessment details and policies have been saved." });
    } catch (err) {
      setSaveStatus("unsaved");
      toast("Could not save draft", { description: err instanceof Error ? err.message : "Please check your network and retry." });
    } finally {
      setSavingConfig(false);
    }
  };

  const handleNext = () => {
    if (activeStep === 1) {
      if (papers.status === "complete") {
        setActiveStep(2);
      } else {
        toast("Upload answer papers first", { description: "Please choose student PDF or ZIP file to continue." });
      }
    } else if (activeStep === 2) {
      if (keyPayload) {
        setActiveStep(3);
      } else if (keyParsing) {
        toast("Answer key is being parsed", { description: "Please wait for the AI parser to complete." });
      } else {
        toast("Upload answer key first", { description: "Please choose an answer key file to continue." });
      }
    } else if (activeStep === 3) {
      if (keyPayload) {
        setActiveStep(4);
      } else {
        toast("Answer key required", { description: "Please review the parsed answer key to proceed." });
      }
    } else if (activeStep === 4) {
      if (classNameValue && subjectValue) {
        setActiveStep(5);
      } else {
        toast("Choose class and subject", { description: "Both class and subject must be selected to proceed." });
      }
    } else if (activeStep === 5) {
      if (strictnessReady) {
        setActiveStep(6);
      } else {
        const issues: string[] = [];
        if (!strictnessMode) issues.push("Choose strictness mode");
        else if (!strictnessOk) issues.push(`Strictness ranges missing ${strictnessCoverage.missingSummary}`);
        if (!wordCountMode) issues.push("Choose word-count mode");
        else if (!wordCountOk) issues.push(`Word-count ranges missing ${wordCountCoverage.missingSummary}`);
        if (!diagramOk) issues.push(`Diagram ranges missing ${diagramCoverage.missingSummary}`);
        toast("Evaluation rules incomplete", { description: issues.join(" · ") || `All questions (Q1–Q${totalQuestionCount}) must have rules defined.` });
      }
    } else if (activeStep === 6) {
      void saveConfiguration();
    }
  };

  const selectProgressStep = (step: number) => { if (step === 1 || (step === 2 && papers.status === "complete") || (step === 3 && keyPayload) || (step === 4 && keyPayload) || (step === 5 && classNameValue && subjectValue)) setActiveStep(step); };

  return <div className="configure-main mx-auto w-full max-w-[1240px] space-y-4 pb-6">
    <section className="relative overflow-hidden rounded-[25px] border border-white/85 bg-[linear-gradient(110deg,rgba(255,255,255,0.9),rgba(247,249,255,0.72),rgba(255,253,243,0.65))] px-5 py-6 shadow-[0_15px_40px_rgba(63,73,139,0.08)] backdrop-blur dark:border-white/10 dark:bg-[#1c1f2e] sm:px-7"><div className="pointer-events-none absolute right-0 top-0 h-32 w-80 bg-[radial-gradient(circle_at_top_right,rgba(133,148,255,0.25),transparent_68%)]" /><div className="relative flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><div className="type-overline inline-flex items-center rounded-full border border-[#dbe0ff] bg-white/80 px-2.5 py-1 text-[#6274e7] dark:border-[#8797ff]/20 dark:bg-white/5 dark:text-[#b2bcff]">Evaluation setup</div><h1 className="type-page-title mt-3 text-[#171827] dark:text-white">Configure your assessment.</h1><p className="type-body mt-3 max-w-2xl text-slate-600 dark:text-slate-300">Prepare student answer sheets, reference material, and evaluation rules before starting automated grading.</p></div><div className="rounded-2xl border border-white/85 bg-white/75 px-3.5 py-2.5 text-right shadow-sm dark:border-white/10 dark:bg-white/5"><p className="type-overline text-[#7182ef]">Progress</p><p className="mt-1 text-sm font-extrabold text-[#171827] dark:text-white">{activeStep > 5 ? "Ready to review" : `Step ${activeStep} of 5`}</p></div></div></section>
    <ConfigureProgress activeStep={Math.min(activeStep, 5)} onSelectStep={selectProgressStep} />
    <div className="configure-stage grid gap-4 lg:grid-cols-[minmax(0,1fr)_270px] lg:items-stretch">
      <div className="flex flex-col justify-between space-y-4">
        <div>
          {activeStep === 1 && <UploadStep heading="Upload answer papers" description="Add an individual student PDF answer paper or a ZIP containing answer sheets of all students." requirement="Name individual PDFs using student roll numbers, or upload a ZIP archive of PDFs." example="23CS041.pdf or class_submissions.zip" accept=".pdf,application/pdf,.zip,application/zip,application/x-zip-compressed" acceptedLabel="PDF · ZIP" upload={papers} completionDetail={papersDetail} onChoose={startPapersUpload} onRemove={handleRemovePapers} />}
          {activeStep === 2 && <UploadStep heading="Upload answer key" description="Add the official answer key, reference solution, or marking document for this assessment." requirement="Use the answer key or marking reference for this subject." example="machine-learning-answer-key.pdf" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp" acceptedLabel="PDF · DOCX · image" upload={answerKey} completionDetail={keyParsing ? `AI parser is reading the document${keyProgress ? ` (${keyProgress})` : "…"}` : "Reference material selected"} busyTitle={answerKey.status === "uploading" ? (keyParsing ? `Processing ${answerKey.name}` : `Uploading ${answerKey.name}`) : undefined} busySublabel={keyProgress ?? "Preparing your assessment files…"} busyProgressPercent={keyProgressPct ?? (keyParsing ? 10 : 0)} onChoose={startKeyUpload} onRemove={handleRemoveAnswerKey} />}
          {activeStep === 3 && keyPayload && <AnswerKeyReviewStep payload={keyPayload} onConfirmed={(updated) => { setKeyPayload(updated); setActiveStep(4); }} onReupload={handleRemoveAnswerKey} />}
          {activeStep === 4 && <AssessmentDetailsStep classNameValue={classNameValue} subjectValue={subjectValue} classes={profileClasses} subjects={profileSubjects} passPercentage={passPercentage} onPassPercentageChange={(value) => { setSaved(false); setPassPercentage(value); }} onClassChange={updateClass} onSubjectChange={updateSubject} onAddClass={addClass} onUpdateTeachingProfile={() => setLocation("/settings")} />}
          {activeStep === 5 && <StrictnessStep mode={strictnessMode} onModeChange={changeMode} ranges={ranges} draft={rangeDraft} onDraftChange={setRangeDraft} onAddRange={addRange} onRemoveRange={(id) => { setSaved(false); setRanges((value) => value.filter((range) => range.id !== id)); }} questions={questions} onQuestionChange={questionChange} onSetAll={setAll} wordCountMode={wordCountMode} onWordCountModeChange={changeWordCountMode} wordCountRanges={wordCountRanges} wordCountDraft={wordCountRangeDraft} onWordCountDraftChange={setWordCountRangeDraft} onAddWordCountRange={addWordCountRange} onRemoveWordCountRange={(id) => { setSaved(false); setWordCountRanges((value) => value.filter((range) => range.id !== id)); }} questionWordCounts={questionWordCounts} onQuestionWordCountChange={changeQuestionWordCount} onSetAllWordCounts={setAllWordCounts} diagramMode={diagramMode} onDiagramModeChange={changeDiagramMode} diagramRanges={diagramRanges} diagramDraft={diagramRangeDraft} onDiagramDraftChange={setDiagramRangeDraft} onAddDiagramRange={addDiagramRange} onRemoveDiagramRange={(id) => { setSaved(false); setDiagramRanges((value) => value.filter((range) => range.id !== id)); }} questionDiagrams={questionDiagrams} onQuestionDiagramChange={changeQuestionDiagram} onReview={() => strictnessReady && setActiveStep(6)} totalQuestions={totalQuestionCount} questionNumbers={detectedQuestionNumbers} />}
          {activeStep === 6 && <ConfigurationSummary classNameValue={classNameValue} subjectValue={subjectValue} papersName={papers.name ?? "—"} papersDetail={papersDetail} keyName={answerKey.name ?? "—"} mode={strictnessMode} ranges={ranges} questions={questions} wordCountMode={wordCountMode} wordCountRanges={wordCountRanges} questionWordCounts={questionWordCounts} diagramMode={diagramMode} diagramRanges={diagramRanges} questionDiagrams={questionDiagrams} saved={saved} onSave={saveConfiguration} onEdit={() => setActiveStep(3)} />}
        </div>

        {/* Global navigation action bar: Back on bottom left, Real-time status + Save and Next on bottom right */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/85 bg-white/75 p-4 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-[#202334]/72">
          <div>
            <button
              type="button"
              onClick={handleBack}
              disabled={activeStep === 1}
              className="type-button inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 shadow-sm transition-all hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:bg-white/5 dark:text-slate-200"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
          </div>
          <div className="flex items-center gap-3">
            {/* Live real-time save indicator badge */}
            <div className="hidden sm:flex items-center gap-1.5 text-xs font-semibold">
              {saveStatus === "saving" && (
                <span className="inline-flex items-center gap-1.5 text-indigo-500">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Saving changes…
                </span>
              )}
              {saveStatus === "saved" && assessmentId && (
                <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Saved in real time
                </span>
              )}
            </div>

            <button
              type="button"
              onClick={handleSaveDraft}
              disabled={savingConfig}
              className="type-button inline-flex items-center gap-1.5 rounded-xl border border-[#cbd4ff] bg-white px-4 py-2.5 text-xs font-bold text-[#5569df] shadow-sm transition-all hover:bg-[#f0f3ff] disabled:opacity-50 dark:border-[#8797ff]/30 dark:bg-white/5 dark:text-[#b2bcff]"
            >
              <Save className="h-4 w-4" />
              {savingConfig ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={handleNext}
              disabled={savingConfig}
              className="type-button inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#6576ee,#4d5ed6)] px-5 py-2.5 text-xs font-extrabold text-white shadow-[0_8px_20px_rgba(98,116,231,0.28)] transition-all hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span>{activeStep === 6 ? "Proceed to Evaluation" : "Next"}</span>
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
      <GuideBot message={guide.message} detail={guide.detail} />
    </div>
  </div>;
}
