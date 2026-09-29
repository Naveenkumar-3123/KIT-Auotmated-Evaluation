/** STYLE: EvalAI configuration flow — staged, bot-guided assessment setup reuses the existing lavender glass dashboard system. */
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useLocation } from "wouter";
import { createAssessment, updateAssessmentDetails, uploadStudentZip } from "@/api/assessments";
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
import { DiagramRuleMode, DiagramRuleRange, QuestionDiagramRule, QuestionRule, QuestionWordCountRule, StrictnessLevel, StrictnessMode, StrictnessRange, UploadState, WordCountMode, WordCountRange } from "@/components/configure/types";

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
    if (!file.name.toLowerCase().endsWith(".zip")) { toast("Choose a ZIP file", { description: "Student answer papers should be uploaded as one ZIP archive." }); return; }
    setSaved(false); setPapers({ name: file.name, status: "uploading" }); setPapersDetail("Scanning and validating the archive…");
    try {
      let id = assessmentId;
      if (!id) {
        const created = await createAssessment({ title: "Untitled assessment" });
        id = created.assessment.id;
        setAssessmentId(id);
        try { window.sessionStorage.setItem(DRAFT_KEY, id); } catch { /* session state is optional */ }
      }
      const result = await uploadStudentZip(id, file);
      const accepted = result.valid;
      const rejected = result.invalid;
      setPapersDetail(`${accepted} student file${accepted === 1 ? "" : "s"} ready${rejected ? ` · ${rejected} rejected` : ""}`);
      setPapers({ name: file.name, status: "complete" });
      setActiveStep(2);
      toast("Answer papers uploaded", { description: `${accepted} student file${accepted === 1 ? "" : "s"} detected${rejected ? `, ${rejected} rejected for review` : ""}.` });
    } catch (error) {
      setPapers(initialUpload); setPapersDetail("No archive uploaded yet");
      toast("Answer papers could not be processed", { description: error instanceof Error ? error.message : "Check the archive and try again." });
    }
  };
  const questionCount = keyPayload?.questions.length ?? 10;
  useEffect(() => {
    if (!keyPayload) return;
    const count = keyPayload.questions.length || 10;
    const build = <T,>(make: (question: number) => T): T[] => Array.from({ length: count }, (_, index) => make(index + 1));
    setQuestions(build((question) => ({ question, level: "moderate" as StrictnessLevel })));
    setQuestionWordCounts(build((question) => ({ question, minWords: 100, shortfallWords: 20, marksDeducted: 1 })));
    setQuestionDiagrams(build((question) => ({ question, required: false, minimumDiagrams: 1, missingDiagramDeductions: [1] })));
  }, [keyPayload]);
  const startKeyUpload = async (file: File) => {
    const allowed = [".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp"];
    if (!allowed.some((ext) => file.name.toLowerCase().endsWith(ext))) { toast("Unsupported answer key", { description: "Upload the key as PDF, DOC, DOCX or an image." }); return; }
    if (!assessmentId) { toast("Upload answer papers first", { description: "Step 1 creates the assessment that owns this key." }); return; }
    setSaved(false); setAnswerKey({ name: file.name, status: "uploading" }); setKeyParsing(true);
    let keepWaiting = false;
    try {
      const accepted = await uploadAnswerKey(assessmentId, file);
      const keyId = accepted.answer_key.id;
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
      const applyProgress = (progress?: { done: number; total: number } | null) => {
        setKeyProgress(progress ? `Parsed ${progress.done} of ${progress.total} sections…` : null);
        setKeyProgressPct(progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : null);
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
        setKeyParsing(false);
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
  const changeMode = (mode: Exclude<StrictnessMode, null>) => { setSaved(false); setStrictnessMode(mode); };
  const addRange = () => { const id = `${rangeDraft.from}-${rangeDraft.to}-${Date.now()}`; setRanges((value) => [...value, { ...rangeDraft, id }]); setSaved(false); setRangeDraft({ from: rangeDraft.to + 1, to: rangeDraft.to + 5, level: "moderate" }); };
  const questionChange = (question: number, level: StrictnessLevel) => { setSaved(false); setQuestions((rules) => rules.map((rule) => rule.question === question ? { ...rule, level } : rule)); };
  const setAll = (level: StrictnessLevel) => { setSaved(false); setQuestions((rules) => rules.map((rule) => ({ ...rule, level }))); };
  const changeWordCountMode = (mode: Exclude<WordCountMode, null>) => { setSaved(false); setWordCountMode(mode); };
  const addWordCountRange = () => { const id = `${wordCountRangeDraft.from}-${wordCountRangeDraft.to}-${Date.now()}`; setWordCountRanges((value) => [...value, { ...wordCountRangeDraft, id }]); setSaved(false); setWordCountRangeDraft({ ...wordCountRangeDraft, from: wordCountRangeDraft.to + 1, to: wordCountRangeDraft.to + 5 }); };
  const changeQuestionWordCount = (question: number, update: Partial<Omit<QuestionWordCountRule, "question">>) => { setSaved(false); setQuestionWordCounts((rules) => rules.map((rule) => rule.question === question ? { ...rule, ...update } : rule)); };
  const setAllWordCounts = (update: Omit<QuestionWordCountRule, "question">) => { setSaved(false); setQuestionWordCounts((rules) => rules.map((rule) => ({ ...rule, ...update }))); };
  const changeDiagramMode = (mode: Exclude<DiagramRuleMode, null>) => { setSaved(false); setDiagramMode(mode); };
  const addDiagramRange = () => { const id = `${diagramRangeDraft.from}-${diagramRangeDraft.to}-${Date.now()}`; setDiagramRanges((value) => [...value, { ...diagramRangeDraft, id }]); setSaved(false); setDiagramRangeDraft({ ...diagramRangeDraft, from: diagramRangeDraft.to + 1, to: diagramRangeDraft.to + 5 }); };
  const changeQuestionDiagram = (question: number, update: Partial<Omit<QuestionDiagramRule, "question">>) => { setSaved(false); setQuestionDiagrams((rules) => rules.map((rule) => rule.question === question ? { ...rule, ...update } : rule)); };
  const strictnessReady = (strictnessMode === "individual" || ranges.length > 0) && (wordCountMode === "individual" || wordCountRanges.length > 0);
  const guide = activeStep === 1 ? { message: "First, upload your class answer papers.", detail: "Use one ZIP file and name each student document using their roll number." } : activeStep === 2 ? { message: "Great. Now add the answer key.", detail: keyParsing ? `The AI parser is reading your key${keyProgress ? ` (${keyProgress})` : "…"}` : "Upload the official reference solution or marking document for this subject." } : activeStep === 3 ? { message: "Check the parsed questions.", detail: "Correct marks, keywords or diagrams — this becomes the locked grading source." } : activeStep === 4 ? { message: "Which class is this for?", detail: "Pick the class and subject so results land in the right place." } : activeStep === 5 ? { message: "Now let’s configure the evaluation rules.", detail: "Set strictness, word-count deductions, and optional diagram rules by question or range." } : { message: "Everything looks ready.", detail: "Review your setup and save it before continuing to evaluation." };
  const saveConfiguration = async () => {
    if (!assessmentId) { toast("Nothing to save yet", { description: "Upload the answer papers first." }); return; }
    if (!classNameValue || !subjectValue) { toast("Choose class and subject", { description: "Assessment details are required before saving." }); return; }
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
  const selectProgressStep = (step: number) => { if (step === 1 || (step === 2 && papers.status === "complete") || (step === 3 && keyPayload) || (step === 4 && keyPayload) || (step === 5 && classNameValue && subjectValue)) setActiveStep(step); };

  return <div className="configure-main mx-auto w-full max-w-[1240px] space-y-4 pb-6">
    <section className="relative overflow-hidden rounded-[25px] border border-white/85 bg-[linear-gradient(110deg,rgba(255,255,255,0.9),rgba(247,249,255,0.72),rgba(255,253,243,0.65))] px-5 py-6 shadow-[0_15px_40px_rgba(63,73,139,0.08)] backdrop-blur dark:border-white/10 dark:bg-[#1c1f2e] sm:px-7"><div className="pointer-events-none absolute right-0 top-0 h-32 w-80 bg-[radial-gradient(circle_at_top_right,rgba(133,148,255,0.25),transparent_68%)]" /><div className="relative flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><div className="type-overline inline-flex items-center rounded-full border border-[#dbe0ff] bg-white/80 px-2.5 py-1 text-[#6274e7] dark:border-[#8797ff]/20 dark:bg-white/5 dark:text-[#b2bcff]">Evaluation setup</div><h1 className="type-page-title mt-3 text-[#171827] dark:text-white">Configure your assessment.</h1><p className="type-body mt-3 max-w-2xl text-slate-600 dark:text-slate-300">Prepare student answer sheets, reference material, and evaluation rules before starting automated grading.</p></div><div className="rounded-2xl border border-white/85 bg-white/75 px-3.5 py-2.5 text-right shadow-sm dark:border-white/10 dark:bg-white/5"><p className="type-overline text-[#7182ef]">Progress</p><p className="mt-1 text-sm font-extrabold text-[#171827] dark:text-white">{activeStep > 5 ? "Ready to review" : `Step ${activeStep} of 5`}</p></div></div></section>
    <ConfigureProgress activeStep={Math.min(activeStep, 5)} onSelectStep={selectProgressStep} />
    <div className="configure-stage grid gap-4 lg:grid-cols-[minmax(0,1fr)_270px] lg:items-stretch"><div>
      {activeStep === 1 && <UploadStep heading="Upload answer papers" description="Add a ZIP containing the answer sheets of all students in this class." requirement="Each document should be named using the student's roll number." example="23CS041.pdf" accept=".zip,application/zip,application/x-zip-compressed" acceptedLabel=".ZIP" upload={papers} completionDetail={papersDetail} onChoose={startPapersUpload} onRemove={() => { setPapers(initialUpload); setAnswerKey(initialUpload); setActiveStep(1); }} />}
      {activeStep === 2 && <UploadStep heading="Upload answer key" description="Add the official answer key, reference solution, or marking document for this assessment." requirement="Use the answer key or marking reference for this subject." example="machine-learning-answer-key.pdf" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp" acceptedLabel="PDF Â· DOCX Â· image" upload={answerKey} completionDetail={keyParsing ? `AI parser is reading the document${keyProgress ? ` (${keyProgress})` : "…"}` : "Reference material selected"} busyTitle={keyParsing ? `Processing ${answerKey.name}` : undefined} busySublabel={keyParsing ? (keyProgress ?? "Uploaded — the AI parser is reading each section…") : undefined} busyProgressPercent={keyParsing ? keyProgressPct ?? 8 : undefined} onChoose={startKeyUpload} onRemove={() => { setAnswerKey(initialUpload); setKeyPayload(null); setActiveStep(2); }} />}
      {activeStep === 3 && keyPayload && <AnswerKeyReviewStep payload={keyPayload} onConfirmed={(updated) => { setKeyPayload(updated); setActiveStep(4); }} onReupload={() => setActiveStep(2)} />}
      {activeStep === 4 && <AssessmentDetailsStep classNameValue={classNameValue} subjectValue={subjectValue} classes={profileClasses} subjects={profileSubjects} passPercentage={passPercentage} onPassPercentageChange={(value) => { setSaved(false); setPassPercentage(value); }} onClassChange={updateClass} onSubjectChange={updateSubject} onAddClass={addClass} onUpdateTeachingProfile={() => setLocation("/settings")} />}
      {activeStep === 5 && <StrictnessStep mode={strictnessMode} onModeChange={changeMode} ranges={ranges} draft={rangeDraft} onDraftChange={setRangeDraft} onAddRange={addRange} onRemoveRange={(id) => { setSaved(false); setRanges((value) => value.filter((range) => range.id !== id)); }} questions={questions} onQuestionChange={questionChange} onSetAll={setAll} wordCountMode={wordCountMode} onWordCountModeChange={changeWordCountMode} wordCountRanges={wordCountRanges} wordCountDraft={wordCountRangeDraft} onWordCountDraftChange={setWordCountRangeDraft} onAddWordCountRange={addWordCountRange} onRemoveWordCountRange={(id) => { setSaved(false); setWordCountRanges((value) => value.filter((range) => range.id !== id)); }} questionWordCounts={questionWordCounts} onQuestionWordCountChange={changeQuestionWordCount} onSetAllWordCounts={setAllWordCounts} diagramMode={diagramMode} onDiagramModeChange={changeDiagramMode} diagramRanges={diagramRanges} diagramDraft={diagramRangeDraft} onDiagramDraftChange={setDiagramRangeDraft} onAddDiagramRange={addDiagramRange} onRemoveDiagramRange={(id) => { setSaved(false); setDiagramRanges((value) => value.filter((range) => range.id !== id)); }} questionDiagrams={questionDiagrams} onQuestionDiagramChange={changeQuestionDiagram} onReview={() => strictnessReady && setActiveStep(6)} />}
      {activeStep === 6 && <ConfigurationSummary classNameValue={classNameValue} subjectValue={subjectValue} papersName={papers.name ?? "—"} papersDetail={papersDetail} keyName={answerKey.name ?? "—"} mode={strictnessMode} ranges={ranges} questions={questions} wordCountMode={wordCountMode} wordCountRanges={wordCountRanges} questionWordCounts={questionWordCounts} diagramMode={diagramMode} diagramRanges={diagramRanges} questionDiagrams={questionDiagrams} saved={saved} onSave={saveConfiguration} onEdit={() => setActiveStep(3)} />}
    </div><GuideBot message={guide.message} detail={guide.detail} /></div>
  </div>;
}
