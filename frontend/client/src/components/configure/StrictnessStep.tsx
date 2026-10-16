/** STYLE: EvalAI rule controls — substantial glass cards let teachers set strictness, word-count deductions, and diagram requirements by range or individual question. */
import { AlertCircle, CheckCircle2, Info, ListChecks, Plus, Rows3, TextCursorInput, Trash2 } from "lucide-react";
import { QuestionDiagramRules } from "./QuestionDiagramRules";
import { DiagramRuleMode, DiagramRuleRange, QuestionDiagramRule, QuestionRule, QuestionWordCountRule, RangeCoverage, StrictnessLevel, StrictnessMode, StrictnessRange, WordCountMode, WordCountRange, getRangeCoverage, strictnessCopy } from "./types";

interface StrictnessStepProps {
  mode: StrictnessMode; onModeChange: (mode: Exclude<StrictnessMode, null>) => void; ranges: StrictnessRange[]; draft: Omit<StrictnessRange, "id">; onDraftChange: (draft: Omit<StrictnessRange, "id">) => void; onAddRange: () => void; onRemoveRange: (id: string) => void; questions: QuestionRule[]; onQuestionChange: (question: number, level: StrictnessLevel) => void; onSetAll: (level: StrictnessLevel) => void;
  wordCountMode: WordCountMode; onWordCountModeChange: (mode: Exclude<WordCountMode, null>) => void; wordCountRanges: WordCountRange[]; wordCountDraft: Omit<WordCountRange, "id">; onWordCountDraftChange: (draft: Omit<WordCountRange, "id">) => void; onAddWordCountRange: () => void; onRemoveWordCountRange: (id: string) => void; questionWordCounts: QuestionWordCountRule[]; onQuestionWordCountChange: (question: number, update: Partial<Omit<QuestionWordCountRule, "question">>) => void; onSetAllWordCounts: (update: Omit<QuestionWordCountRule, "question">) => void;
  diagramMode: DiagramRuleMode; onDiagramModeChange: (mode: Exclude<DiagramRuleMode, null>) => void; diagramRanges: DiagramRuleRange[]; diagramDraft: Omit<DiagramRuleRange, "id">; onDiagramDraftChange: (draft: Omit<DiagramRuleRange, "id">) => void; onAddDiagramRange: () => void; onRemoveDiagramRange: (id: string) => void; questionDiagrams: QuestionDiagramRule[]; onQuestionDiagramChange: (question: number, update: Partial<Omit<QuestionDiagramRule, "question">>) => void;
  onReview: () => void;
  totalQuestions?: number;
  questionNumbers?: number[];
}

const levels: StrictnessLevel[] = ["lenient", "moderate", "strict"];

export function StrictnessStep(props: StrictnessStepProps) {
  const { mode, onModeChange, ranges, draft, onDraftChange, onAddRange, onRemoveRange, questions, onQuestionChange, onSetAll, wordCountMode, onWordCountModeChange, wordCountRanges, wordCountDraft, onWordCountDraftChange, onAddWordCountRange, onRemoveWordCountRange, questionWordCounts, onQuestionWordCountChange, onSetAllWordCounts, diagramMode, onDiagramModeChange, diagramRanges, diagramDraft, onDiagramDraftChange, onAddDiagramRange, onRemoveDiagramRange, questionDiagrams, onQuestionDiagramChange, onReview, totalQuestions: totalQuestionsProp, questionNumbers: questionNumbersProp } = props;
  const questionNumbers = questionNumbersProp ?? (questions.map((q) => q.question).length ? questions.map((q) => q.question) : Array.from({ length: totalQuestionsProp || 10 }, (_, i) => i + 1));
  const minQ = Math.min(...questionNumbers);
  const maxQ = Math.max(...questionNumbers);
  const totalQuestions = questionNumbers.length;

  const strictnessCoverage = getRangeCoverage(ranges, questionNumbers);
  const wordCountCoverage = getRangeCoverage(wordCountRanges, questionNumbers);
  const diagramCoverage = getRangeCoverage(diagramRanges, questionNumbers);

  const invalidRange = draft.to < draft.from || draft.from < minQ || draft.to > maxQ;
  const overlapping = ranges.some((range) => draft.from <= range.to && draft.to >= range.from);
  const invalidWordCountRange =
    wordCountDraft.to < wordCountDraft.from ||
    wordCountDraft.from < minQ ||
    wordCountDraft.to > maxQ ||
    wordCountDraft.minWords < 1 ||
    wordCountDraft.shortfallWords < 1 ||
    wordCountDraft.shortfallWords >= wordCountDraft.minWords ||
    wordCountDraft.marksDeducted < 0.5;
  const overlappingWordCountRange = wordCountRanges.some((range) => wordCountDraft.from <= range.to && wordCountDraft.to >= range.from);

  const strictnessReady = mode === "individual" || (mode === "ranges" && strictnessCoverage.isCovered);
  const wordCountReady = wordCountMode === "individual" || (wordCountMode === "ranges" && wordCountCoverage.isCovered);
  const diagramReady = diagramMode !== "ranges" || diagramCoverage.isCovered;
  const ready = strictnessReady && wordCountReady && diagramReady && mode !== null && wordCountMode !== null;

  const quickWordRule = questionWordCounts[0] ?? { question: minQ, minWords: 100, shortfallWords: 20, marksDeducted: 1 };

  return <section className="rounded-[24px] border border-white/85 bg-white/64 p-5 shadow-[0_14px_34px_rgba(60,70,135,0.08)] backdrop-blur-xl dark:border-white/10 dark:bg-[#202334]/72 sm:p-6">
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="type-overline text-[#7182ef]">Step 4</p>
        <span className="rounded-full bg-[#eef1ff] px-3 py-1 text-xs font-bold text-[#6275df] dark:bg-[#7587f2]/15 dark:text-[#b7c0ff]">
          Total questions: {totalQuestions} (Q{minQ}–Q{maxQ})
        </span>
      </div>
      <h2 className="type-section-title mt-1.5 text-[#171827] dark:text-white">Evaluation rules</h2>
      <p className="type-support mt-2 max-w-2xl text-slate-500 dark:text-slate-400">Set response alignment, word-count eligibility and deductions, and optional diagram requirements. When using question ranges, all extracted questions (Q{minQ}–Q{maxQ}) must be covered before continuing.</p>
    </div>

    {/* Strictness Section */}
    <RuleModeSection eyebrow="Evaluation strictness" title="How closely should responses match?" description="Choose the degree of alignment required against expected concepts, terminology, and detail." mode={mode} onModeChange={onModeChange} rangeTitle="Question ranges" rangeDescription="Apply strictness levels across ranges covering all questions." individualTitle="Individual questions" individualDescription="Configure strictness separately for every question." rangeIcon={Rows3} individualIcon={ListChecks}>
      {mode === "ranges" && <div className="mt-5 rounded-2xl border border-[#e0e5ff] bg-[#f8f9ff]/75 p-4 dark:border-white/10 dark:bg-white/[0.035]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="type-overline text-[#7182ef]">Strictness by question range</p>
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Range coverage: {strictnessCoverage.coveredCount}/{totalQuestions} questions</span>
        </div>
        <CoverageStatus
          coverage={strictnessCoverage}
          label="Strictness"
          onFillRemaining={() => {
            if (strictnessCoverage.nextSuggestedRange) {
              onDraftChange({
                ...draft,
                from: strictnessCoverage.nextSuggestedRange.from,
                to: strictnessCoverage.nextSuggestedRange.to,
              });
            }
          }}
        />

        {/* Quick Presets for Strictness */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">Quick presets:</span>
          {minQ <= 10 && maxQ > 10 && (
            <>
              <button
                type="button"
                onClick={() => onDraftChange({ from: minQ, to: 10, level: "strict" })}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
              >
                Part A: Q{minQ}–Q10 (Strict)
              </button>
              <button
                type="button"
                onClick={() => onDraftChange({ from: 11, to: maxQ, level: "moderate" })}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
              >
                Part B: Q11–Q{maxQ} (Moderate)
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => onDraftChange({ from: minQ, to: maxQ, level: "moderate" })}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            All Q{minQ}–Q{maxQ} (Moderate)
          </button>
          <button
            type="button"
            onClick={() => onDraftChange({ from: minQ, to: maxQ, level: "strict" })}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            All Q{minQ}–Q{maxQ} (Strict)
          </button>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_1fr_1.2fr_auto]">
          <NumberField
            label="From question"
            value={draft.from}
            min={minQ}
            max={maxQ}
            onChange={(from) => {
              const vFrom = Math.max(minQ, Math.min(maxQ, from));
              onDraftChange({
                ...draft,
                from: vFrom,
                to: draft.to < vFrom ? vFrom : Math.min(maxQ, draft.to),
              });
            }}
          />
          <NumberField
            label="To question"
            value={draft.to}
            min={minQ}
            max={maxQ}
            onChange={(to) => {
              const vTo = Math.max(minQ, Math.min(maxQ, to));
              onDraftChange({
                ...draft,
                to: vTo,
                from: draft.from > vTo ? vTo : Math.max(minQ, draft.from),
              });
            }}
          />
          <LevelSelect label="Strictness" value={draft.level} onChange={(level) => onDraftChange({ ...draft, level })} />
          <button
            type="button"
            onClick={onAddRange}
            disabled={invalidRange}
            className="type-button self-end rounded-full bg-[#171b32] px-3.5 py-2.5 text-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-[#9aa8ff] dark:text-[#151827]"
          >
            <Plus className="mr-1 inline h-3.5 w-3.5" />
            {overlapping ? "Add range (resolves overlap)" : "Add range"}
          </button>
        </div>
        {draft.to > maxQ && <RuleError>Question {draft.to} exceeds assessment upper question Q{maxQ}.</RuleError>}
        {draft.from < minQ && <RuleError>Question {draft.from} is below assessment lower question Q{minQ}.</RuleError>}
        {draft.to < draft.from && <RuleError>End question must be greater than or equal to the starting question.</RuleError>}
        {overlapping && (
          <div className="mt-2.5 flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50/80 px-3 py-1.5 text-xs font-semibold text-indigo-800 dark:border-indigo-500/20 dark:bg-indigo-950/25 dark:text-indigo-300">
            <Info className="h-3.5 w-3.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <span>Overlaps existing range(s). Adding will automatically adjust overlapping ranges without conflict.</span>
          </div>
        )}
        {ranges.length > 0 && <RuleRows>{ranges.map((range) => <RuleRow key={range.id} label={`Q${range.from} – Q${range.to}`} value={range.level} onRemove={() => onRemoveRange(range.id)} removeLabel={`Remove strictness rule for questions ${range.from} to ${range.to}`} />)}</RuleRows>}
      </div>}
      {mode === "individual" && <div className="mt-5 rounded-2xl border border-[#e0e5ff] bg-[#f8f9ff]/75 p-4 dark:border-white/10 dark:bg-white/[0.035]"><div className="flex flex-wrap items-center justify-between gap-3"><p className="type-overline text-[#7182ef]">{questions.length} questions detected</p><label className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">Set all to:<select className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-bold text-[#171827] outline-none dark:border-white/10 dark:bg-white/5 dark:text-white" onChange={(event) => onSetAll(event.target.value as StrictnessLevel)} defaultValue="moderate">{levels.map((level) => <option key={level} value={level}>{strictnessCopy[level].title}</option>)}</select></label></div><div className="mt-3 divide-y divide-slate-100 overflow-hidden rounded-xl border border-white/80 bg-white/75 dark:divide-white/[0.06] dark:border-white/10 dark:bg-white/[0.04]">{questions.map((rule) => <div key={rule.question} className="flex items-center justify-between px-3 py-2.5"><span className="text-sm font-semibold text-[#171827] dark:text-white">Question {rule.question}</span><LevelSelect label="" value={rule.level} onChange={(level) => onQuestionChange(rule.question, level)} compact /></div>)}</div></div>}
    </RuleModeSection>

    <Divider />

    {/* Word-count Section */}
    <RuleModeSection eyebrow="Word-count policy" title="When should a short answer lose marks?" description="Set the minimum word count eligible for full marks, then choose how far below that minimum an answer must be before a deduction applies." mode={wordCountMode} onModeChange={onWordCountModeChange} rangeTitle="Question ranges" rangeDescription="Apply the same minimum, trigger, and deduction to a question range covering all questions." individualTitle="Individual questions" individualDescription="Set word-count requirements and deductions separately for every question." rangeIcon={Rows3} individualIcon={TextCursorInput}>
      {wordCountMode === "ranges" && <div className="mt-5 rounded-2xl border border-[#e0e5ff] bg-[#f8f9ff]/75 p-4 dark:border-white/10 dark:bg-white/[0.035]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="type-overline text-[#7182ef]">Word-count rules by question range</p>
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Range coverage: {wordCountCoverage.coveredCount}/{totalQuestions} questions</span>
        </div>
        <CoverageStatus
          coverage={wordCountCoverage}
          label="Word-count"
          onFillRemaining={() => {
            if (wordCountCoverage.nextSuggestedRange) {
              onWordCountDraftChange({
                ...wordCountDraft,
                from: wordCountCoverage.nextSuggestedRange.from,
                to: wordCountCoverage.nextSuggestedRange.to,
              });
            }
          }}
        />

        {/* Quick Presets for Word Count */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">Quick presets:</span>
          {minQ <= 10 && maxQ > 10 && (
            <>
              <button
                type="button"
                onClick={() => {
                  onWordCountDraftChange({
                    from: minQ,
                    to: 10,
                    minWords: 30,
                    shortfallWords: 15,
                    marksDeducted: 0.5,
                  });
                }}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
              >
                Part A: Q{minQ}–Q10 (Min: 30w, -0.5m)
              </button>
              <button
                type="button"
                onClick={() => {
                  onWordCountDraftChange({
                    from: 11,
                    to: maxQ,
                    minWords: 150,
                    shortfallWords: 30,
                    marksDeducted: 1,
                  });
                }}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
              >
                Part B: Q11–Q{maxQ} (Min: 150w, -1m)
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => {
              onWordCountDraftChange({
                from: minQ,
                to: maxQ,
                minWords: 100,
                shortfallWords: 20,
                marksDeducted: 1,
              });
            }}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            All Q{minQ}–Q{maxQ} (Min: 100w, -1m)
          </button>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-[.75fr_.75fr_1fr_1fr_1fr_auto]">
          <NumberField
            label="From question"
            value={wordCountDraft.from}
            min={minQ}
            max={maxQ}
            onChange={(from) => {
              const vFrom = Math.max(minQ, Math.min(maxQ, from));
              onWordCountDraftChange({
                ...wordCountDraft,
                from: vFrom,
                to: wordCountDraft.to < vFrom ? vFrom : Math.min(maxQ, wordCountDraft.to),
              });
            }}
          />
          <NumberField
            label="To question"
            value={wordCountDraft.to}
            min={minQ}
            max={maxQ}
            onChange={(to) => {
              const vTo = Math.max(minQ, Math.min(maxQ, to));
              onWordCountDraftChange({
                ...wordCountDraft,
                to: vTo,
                from: wordCountDraft.from > vTo ? vTo : Math.max(minQ, wordCountDraft.from),
              });
            }}
          />
          <NumberField
            label="Full-mark minimum"
            value={wordCountDraft.minWords}
            onChange={(minWords) => {
              const validMin = Math.max(1, Math.round(minWords));
              const shortfallWords = wordCountDraft.shortfallWords >= validMin
                ? Math.max(1, validMin - 1)
                : wordCountDraft.shortfallWords;
              onWordCountDraftChange({ ...wordCountDraft, minWords: validMin, shortfallWords });
            }}
          />
          <NumberField
            label="Trigger below by"
            value={wordCountDraft.shortfallWords}
            max={Math.max(1, wordCountDraft.minWords - 1)}
            helperText={`Must be < ${wordCountDraft.minWords} words`}
            onChange={(shortfallWords) => {
              const maxAllowed = Math.max(1, wordCountDraft.minWords - 1);
              const validShortfall = Math.max(1, Math.min(maxAllowed, Math.round(shortfallWords)));
              onWordCountDraftChange({ ...wordCountDraft, shortfallWords: validShortfall });
            }}
          />
          <MarkField
            label="Deduct"
            value={wordCountDraft.marksDeducted}
            onChange={(marksDeducted) => onWordCountDraftChange({ ...wordCountDraft, marksDeducted })}
          />
          <button
            type="button"
            onClick={onAddWordCountRange}
            disabled={invalidWordCountRange}
            className="type-button self-end rounded-full bg-[#171b32] px-3.5 py-2.5 text-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-[#9aa8ff] dark:text-[#151827]"
          >
            <Plus className="mr-1 inline h-3.5 w-3.5" />
            {overlappingWordCountRange ? "Add rule (resolves overlap)" : "Add rule"}
          </button>
        </div>
        {wordCountDraft.to > maxQ && <RuleError>Question {wordCountDraft.to} exceeds assessment upper question Q{maxQ}.</RuleError>}
        {wordCountDraft.from < minQ && <RuleError>Question {wordCountDraft.from} is below assessment lower question Q{minQ}.</RuleError>}
        {wordCountDraft.shortfallWords >= wordCountDraft.minWords && (
          <RuleError>Trigger shortfall ({wordCountDraft.shortfallWords} words) must be less than full-mark minimum ({wordCountDraft.minWords} words).</RuleError>
        )}
        {invalidWordCountRange && wordCountDraft.to <= maxQ && wordCountDraft.from >= minQ && wordCountDraft.shortfallWords < wordCountDraft.minWords && (
          <RuleError>Enter valid question bounds, minimum words, shortfall trigger, and deduction values.</RuleError>
        )}
        {overlappingWordCountRange && (
          <div className="mt-2.5 flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50/80 px-3 py-1.5 text-xs font-semibold text-indigo-800 dark:border-indigo-500/20 dark:bg-indigo-950/25 dark:text-indigo-300">
            <Info className="h-3.5 w-3.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <span>Overlaps existing rule(s). Adding will automatically adjust overlapping ranges without conflict.</span>
          </div>
        )}
        {wordCountRanges.length > 0 && <RuleRows>{wordCountRanges.map((range) => <RuleRow key={range.id} label={`Q${range.from} – Q${range.to}`} value={wordCountRuleLabel(range)} onRemove={() => onRemoveWordCountRange(range.id)} removeLabel={`Remove word-count rule for questions ${range.from} to ${range.to}`} />)}</RuleRows>}
      </div>}
      {wordCountMode === "individual" && <div className="mt-5 rounded-2xl border border-[#e0e5ff] bg-[#f8f9ff]/75 p-4 dark:border-white/10 dark:bg-white/[0.035]"><div className="flex flex-wrap items-start justify-between gap-3"><p className="type-overline pt-1.5 text-[#7182ef]">{questionWordCounts.length} questions detected</p><div className="grid w-full gap-2 sm:w-auto sm:grid-cols-3"><QuickNumber label="Set all minimum" value={quickWordRule.minWords} suffix="words" onChange={(minWords) => { const validMin = Math.max(1, Math.round(minWords)); const shortfallWords = quickWordRule.shortfallWords >= validMin ? Math.max(1, validMin - 1) : quickWordRule.shortfallWords; onSetAllWordCounts({ ...quickWordRule, minWords: validMin, shortfallWords }); }} /><QuickNumber label="Set all trigger" value={quickWordRule.shortfallWords} suffix="words below" onChange={(shortfallWords) => { const maxAllowed = Math.max(1, quickWordRule.minWords - 1); onSetAllWordCounts({ ...quickWordRule, shortfallWords: Math.max(1, Math.min(maxAllowed, Math.round(shortfallWords))) }); }} /><QuickMark label="Set all deduction" value={quickWordRule.marksDeducted} onChange={(marksDeducted) => onSetAllWordCounts({ ...quickWordRule, marksDeducted })} /></div></div><div className="mt-4 space-y-2">{questionWordCounts.map((rule) => <IndividualWordRule key={rule.question} rule={rule} onChange={(update) => onQuestionWordCountChange(rule.question, update)} />)}</div></div>}
    </RuleModeSection>

    <Divider />

    {/* Diagram Section */}
    <QuestionDiagramRules
      mode={diagramMode}
      onModeChange={onDiagramModeChange}
      ranges={diagramRanges}
      draft={diagramDraft}
      onDraftChange={onDiagramDraftChange}
      onAddRange={onAddDiagramRange}
      onRemoveRange={onRemoveDiagramRange}
      questions={questionDiagrams}
      onQuestionChange={onQuestionDiagramChange}
      totalQuestions={totalQuestions}
      questionNumbers={questionNumbers}
    />

    {/* Review footer card */}
    <div className="mt-7 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#c9dfd3] bg-[#f1faf5]/90 p-4 dark:border-[#589377]/25 dark:bg-[#4d916e]/10">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2 text-xs font-semibold">
        {ready ? (
          <span className="inline-flex items-center gap-2 text-[#4f8f70] dark:text-[#98d1af]">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            All evaluation rules cover all {totalQuestions} questions (Q{minQ}–Q{maxQ}). Ready to review.
          </span>
        ) : (
          <span className="inline-flex items-start gap-2 text-amber-800 dark:text-amber-300">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>
              <strong>Rule coverage required before proceeding:</strong>
              {!mode && " Choose strictness mode ·"}
              {mode === "ranges" && !strictnessCoverage.isCovered && ` Strictness (${strictnessCoverage.missingSummary}) ·`}
              {!wordCountMode && " Choose word-count mode ·"}
              {wordCountMode === "ranges" && !wordCountCoverage.isCovered && ` Word count (${wordCountCoverage.missingSummary}) ·`}
              {diagramMode === "ranges" && !diagramCoverage.isCovered && ` Diagrams (${diagramCoverage.missingSummary})`}
            </span>
          </span>
        )}
      </div>
      <button
        type="button"
        disabled={!ready}
        onClick={onReview}
        className="type-button rounded-full bg-[#171b32] px-5 py-2.5 text-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-[#9aa8ff] dark:text-[#151827]"
      >
        Review configuration
      </button>
    </div>
  </section>;
}

function CoverageStatus({ coverage, onFillRemaining, label = "Rule coverage" }: { coverage: RangeCoverage; onFillRemaining?: () => void; label?: string }) {
  if (coverage.isCovered) {
    return <div className="mt-3 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50/80 px-3.5 py-2 text-xs font-semibold text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-950/25 dark:text-emerald-300">
      <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
      <span>100% complete: All {coverage.totalCount} questions are covered.</span>
    </div>;
  }
  return <div className="mt-3 flex flex-wrap items-center justify-between gap-2.5 rounded-xl border border-amber-200 bg-amber-50/90 p-3 text-xs dark:border-amber-500/25 dark:bg-amber-950/25">
    <div className="flex items-center gap-2 font-semibold text-amber-900 dark:text-amber-200">
      <AlertCircle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <div>
        <span>{label} incomplete: </span>
        <span className="font-bold text-amber-950 dark:text-amber-100">{coverage.missingSummary}</span>
        <span className="ml-1 text-[11px] font-normal text-amber-700 dark:text-amber-300">({coverage.coveredCount}/{coverage.totalCount} questions defined)</span>
      </div>
    </div>
    {onFillRemaining && coverage.nextSuggestedRange && (
      <button type="button" onClick={onFillRemaining} className="inline-flex items-center gap-1 rounded-lg bg-amber-600 px-2.5 py-1 text-[11px] font-bold text-white shadow-sm hover:bg-amber-700 transition">
        <Plus className="h-3 w-3 inline" />
        Fill Q{coverage.nextSuggestedRange.from}–Q{coverage.nextSuggestedRange.to}
      </button>
    )}
  </div>;
}

function Divider() { return <div className="my-7 h-px bg-[linear-gradient(90deg,transparent,rgba(119,136,255,0.32),transparent)]" />; }
function RuleModeSection({ eyebrow, title, description, mode, onModeChange, rangeTitle, rangeDescription, individualTitle, individualDescription, rangeIcon: RangeIcon, individualIcon: IndividualIcon, children }: { eyebrow: string; title: string; description: string; mode: StrictnessMode | WordCountMode; onModeChange: (mode: "ranges" | "individual") => void; rangeTitle: string; rangeDescription: string; individualTitle: string; individualDescription: string; rangeIcon: typeof Rows3; individualIcon: typeof Rows3; children: React.ReactNode }) { return <div><p className="type-overline text-[#7182ef]">{eyebrow}</p><h3 className="mt-1 text-[15px] font-semibold tracking-[-0.022em] text-[#171827] dark:text-white">{title}</h3><p className="type-support mt-1.5 max-w-2xl text-slate-500 dark:text-slate-400">{description}</p><div className="mt-4 grid gap-3 sm:grid-cols-2"><ModeCard active={mode === "ranges"} title={rangeTitle} description={rangeDescription} icon={RangeIcon} onClick={() => onModeChange("ranges")} /><ModeCard active={mode === "individual"} title={individualTitle} description={individualDescription} icon={IndividualIcon} onClick={() => onModeChange("individual")} /></div>{children}</div>; }
function ModeCard({ active, title, description, icon: Icon, onClick }: { active: boolean; title: string; description: string; icon: typeof Rows3; onClick: () => void }) { return <button type="button" onClick={onClick} aria-pressed={active} className={`relative rounded-2xl border p-4 text-left transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7788ff] ${active ? "border-[#7f90ef] bg-[#eef1ff]/85 shadow-[0_10px_24px_rgba(99,117,225,0.12)] dark:border-[#9aa8ff]/55 dark:bg-[#7587f2]/15" : "border-[#e0e5ff] bg-[#f8f9ff]/70 hover:border-[#bfc9ff] dark:border-white/10 dark:bg-white/[0.035]"}`}><Icon className={`h-5 w-5 ${active ? "text-[#6578e7] dark:text-[#b7c0ff]" : "text-slate-400"}`} /><p className="mt-4 text-sm font-extrabold text-[#171827] dark:text-white">{title}</p><p className="mt-1.5 max-w-[260px] text-xs font-medium leading-5 text-slate-500 dark:text-slate-400">{description}</p><span className={`mt-4 inline-flex rounded-full px-2.5 py-1 text-[11px] font-bold ${active ? "bg-[#6578e7] text-white" : "bg-white text-slate-500 dark:bg-white/5 dark:text-slate-300"}`}>{active ? "Selected" : "Select"}</span></button>; }
function RuleRows({ children }: { children: React.ReactNode }) { return <div className="mt-4 space-y-2">{children}</div>; }
function RuleRow({ label, value, onRemove, removeLabel }: { label: string; value: string; onRemove: () => void; removeLabel: string }) { return <div className="flex items-center justify-between gap-3 rounded-xl border border-white/80 bg-white/75 px-3 py-2.5 text-sm dark:border-white/10 dark:bg-white/[0.04]"><span className="font-semibold text-[#171827] dark:text-white">{label}</span><span className="rounded-full bg-[#eef1ff] px-2.5 py-1 text-[11px] font-bold capitalize text-[#6275df] dark:bg-[#7587f2]/15 dark:text-[#b7c0ff]">{value}</span><button type="button" onClick={onRemove} aria-label={removeLabel} className="rounded-lg p-1.5 text-slate-400 hover:bg-[#fff1f0] hover:text-[#b85d59]"><Trash2 className="h-3.5 w-3.5" /></button></div>; }
function IndividualWordRule({ rule, onChange }: { rule: QuestionWordCountRule; onChange: (update: Partial<Omit<QuestionWordCountRule, "question">>) => void }) {
  return <article className="rounded-xl border border-white/80 bg-white/80 p-3 dark:border-white/10 dark:bg-white/[0.04]">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <p className="shrink-0 text-sm font-semibold text-[#171827] dark:text-white">Question {rule.question}</p>
      <div className="grid flex-1 gap-2 sm:grid-cols-3">
        <CompactNumber
          label="Full-mark minimum"
          value={rule.minWords}
          suffix="words"
          onChange={(minWords) => {
            const validMin = Math.max(1, Math.round(minWords));
            const shortfallWords = rule.shortfallWords >= validMin ? Math.max(1, validMin - 1) : rule.shortfallWords;
            onChange({ minWords: validMin, shortfallWords });
          }}
        />
        <CompactNumber
          label="Trigger below by"
          value={rule.shortfallWords}
          suffix="words"
          max={Math.max(1, rule.minWords - 1)}
          onChange={(shortfallWords) => {
            const maxAllowed = Math.max(1, rule.minWords - 1);
            onChange({ shortfallWords: Math.max(1, Math.min(maxAllowed, Math.round(shortfallWords))) });
          }}
        />
        <CompactMark label="Deduct" value={rule.marksDeducted} onChange={(marksDeducted) => onChange({ marksDeducted })} />
      </div>
    </div>
  </article>;
}
function RuleError({ children }: { children: React.ReactNode }) { return <p className="mt-3 text-xs font-semibold text-[#b85d59]">{children}</p>; }
function NumberField({ label, value, min = 1, max, onChange, compact = false, helperText }: { label: string; value: number; min?: number; max?: number; onChange: (value: number) => void; compact?: boolean; helperText?: string }) {
  return <label className={`${compact ? "flex items-center gap-2" : "text-[11px] font-bold text-slate-500 dark:text-slate-400"}`}>
    {label}{label && <br />}
    <input
      min={min}
      max={max}
      type="number"
      value={value}
      onChange={(event) => onChange(Math.max(min, Math.min(max ?? Number.POSITIVE_INFINITY, Number(event.target.value))))}
      className={`${compact ? "w-20" : "mt-1.5 w-full"} rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-[#171827] outline-none focus:border-[#8292ee] dark:border-white/10 dark:bg-white/[0.04] dark:text-white`}
    />
    {helperText && <span className="mt-1 block text-[10px] font-medium text-slate-400">{helperText}</span>}
  </label>;
}
function MarkField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) { return <label className="text-[11px] font-bold text-slate-500 dark:text-slate-400">{label}<input min={0.5} step={0.5} type="number" value={value} onChange={(event) => onChange(normalizeMark(Number(event.target.value)))} className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-[#171827] outline-none focus:border-[#8292ee] dark:border-white/10 dark:bg-white/[0.04] dark:text-white" /><span className="mt-1 block text-[10px] font-medium text-slate-400">0.5 mark increments</span></label>; }
function QuickNumber({ label, value, suffix, onChange }: { label: string; value: number; suffix: string; onChange: (value: number) => void }) { return <label className="rounded-xl border border-white/85 bg-white/80 px-2.5 py-2 text-[10px] font-bold text-slate-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-400">{label}<span className="mt-1 flex items-center gap-1"><input min={1} type="number" value={value} onChange={(event) => onChange(Math.max(1, Number(event.target.value)))} className="w-14 border-0 bg-transparent p-0 text-sm font-bold text-[#171827] outline-none dark:text-white" /><span className="text-[9px]">{suffix}</span></span></label>; }
function QuickMark({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) { return <label className="rounded-xl border border-white/85 bg-white/80 px-2.5 py-2 text-[10px] font-bold text-slate-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-400">{label}<span className="mt-1 flex items-center gap-1"><input min={0.5} step={0.5} type="number" value={value} onChange={(event) => onChange(normalizeMark(Number(event.target.value)))} className="w-12 border-0 bg-transparent p-0 text-sm font-bold text-[#171827] outline-none dark:text-white" /><span className="text-[9px]">marks</span></span></label>; }
function CompactNumber({ label, value, suffix, max, onChange }: { label: string; value: number; suffix: string; max?: number; onChange: (value: number) => void }) {
  return <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400">{label}<span className="mt-1 flex items-center gap-1"><input min={1} max={max} type="number" value={value} onChange={(event) => onChange(Math.max(1, Math.min(max ?? Number.POSITIVE_INFINITY, Number(event.target.value))))} className="h-8 w-16 rounded-lg border border-slate-200 bg-white px-2 text-center text-xs font-bold text-[#171827] outline-none focus:border-[#8292ee] dark:border-white/10 dark:bg-white/[0.04] dark:text-white" /><span className="text-[9px] font-medium">{suffix}</span></span></label>;
}
function CompactMark({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) { return <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400">{label}<span className="mt-1 flex items-center gap-1"><input min={0.5} step={0.5} type="number" value={value} onChange={(event) => onChange(normalizeMark(Number(event.target.value)))} className="h-8 w-14 rounded-lg border border-slate-200 bg-white px-2 text-center text-xs font-bold text-[#171827] outline-none focus:border-[#8292ee] dark:border-white/10 dark:bg-white/[0.04] dark:text-white" /><span className="text-[9px] font-medium">marks</span></span></label>; }
function LevelSelect({ label, value, onChange, compact = false }: { label: string; value: StrictnessLevel; onChange: (level: StrictnessLevel) => void; compact?: boolean }) { return <label className={`${compact ? "" : "text-[11px] font-bold text-slate-500 dark:text-slate-400"}`}>{label}{label && <br />}<select value={value} onChange={(event) => onChange(event.target.value as StrictnessLevel)} className={`rounded-xl border border-slate-200 bg-white text-sm font-semibold capitalize text-[#171827] outline-none focus:border-[#8292ee] dark:border-white/10 dark:bg-white/[0.04] dark:text-white ${compact ? "px-2.5 py-1.5" : "mt-1.5 w-full px-3 py-2.5"}`}>{levels.map((level) => <option key={level} value={level}>{strictnessCopy[level].title}</option>)}</select></label>; }
function wordCountRuleLabel(rule: Pick<WordCountRange, "minWords" | "shortfallWords" | "marksDeducted">) { return `${rule.minWords} words · ${rule.shortfallWords} below → −${rule.marksDeducted} ${rule.marksDeducted === 1 ? "mark" : "marks"}`; }
function normalizeMark(value: number) { return Math.max(0.5, Math.round(value * 2) / 2); }
