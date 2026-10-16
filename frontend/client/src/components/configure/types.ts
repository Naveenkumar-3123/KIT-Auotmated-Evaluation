export type UploadStatus = "idle" | "uploading" | "complete";
export type StrictnessLevel = "lenient" | "moderate" | "strict";
export type StrictnessMode = "ranges" | "individual" | null;
export type WordCountMode = "ranges" | "individual" | null;
export type DiagramRuleMode = "ranges" | "individual" | null;

export interface UploadState {
  name: string | null;
  status: UploadStatus;
}

export interface StrictnessRange {
  id: string;
  from: number;
  to: number;
  level: StrictnessLevel;
}

export interface QuestionRule {
  question: number;
  level: StrictnessLevel;
}

export interface WordCountRange {
  id: string;
  from: number;
  to: number;
  minWords: number;
  shortfallWords: number;
  marksDeducted: number;
}

export interface QuestionWordCountRule {
  question: number;
  minWords: number;
  shortfallWords: number;
  marksDeducted: number;
}

export interface GlobalDiagramPolicy {
  required: boolean;
  minimumDiagrams: number;
  missingDiagramDeductions: number[];
}

export interface DiagramRuleRange {
  id: string;
  from: number;
  to: number;
  required: boolean;
  minimumDiagrams: number;
  missingDiagramDeductions: number[];
}

export interface QuestionDiagramRule {
  question: number;
  required: boolean;
  minimumDiagrams: number;
  missingDiagramDeductions: number[];
}

export const strictnessCopy: Record<StrictnessLevel, { title: string; description: string }> = {
  lenient: { title: "Lenient", description: "Accept equivalent wording and partial conceptual matches more generously." },
  moderate: { title: "Moderate", description: "Balance conceptual correctness, relevant detail, and reasonable wording differences." },
  strict: { title: "Strict", description: "Require close alignment with expected concepts, terminology, and required details." },
};

export interface RangeCoverage {
  coveredCount: number;
  totalCount: number;
  isCovered: boolean;
  missingRanges: Array<{ from: number; to: number }>;
  missingSummary: string;
  nextSuggestedRange?: { from: number; to: number };
}

export function getRangeCoverage(
  ranges: Array<{ from: number; to: number }>,
  targetQuestions: number | number[]
): RangeCoverage {
  const actualQuestions: number[] = Array.isArray(targetQuestions)
    ? Array.from(new Set(targetQuestions)).sort((a, b) => a - b)
    : Array.from({ length: Math.max(1, targetQuestions || 1) }, (_, i) => i + 1);

  const covered = new Set<number>();
  for (const r of ranges) {
    const start = Math.min(r.from, r.to);
    const end = Math.max(r.from, r.to);
    for (let q = start; q <= end; q++) {
      if (actualQuestions.includes(q)) {
        covered.add(q);
      }
    }
  }

  const missingQuestions = actualQuestions.filter((q) => !covered.has(q));
  const isCovered = missingQuestions.length === 0;

  const missingRanges: Array<{ from: number; to: number }> = [];
  if (missingQuestions.length > 0) {
    let rStart = missingQuestions[0];
    let rPrev = missingQuestions[0];
    for (let i = 1; i < missingQuestions.length; i++) {
      const curr = missingQuestions[i];
      if (curr === rPrev + 1) {
        rPrev = curr;
      } else {
        missingRanges.push({ from: rStart, to: rPrev });
        rStart = curr;
        rPrev = curr;
      }
    }
    missingRanges.push({ from: rStart, to: rPrev });
  }

  const missingSummary = missingRanges
    .map((r) => (r.from === r.to ? `Q${r.from}` : `Q${r.from}–Q${r.to}`))
    .join(", ");

  const nextSuggestedRange = missingRanges.length > 0 ? missingRanges[0] : undefined;

  return {
    coveredCount: covered.size,
    totalCount: actualQuestions.length,
    isCovered,
    missingRanges,
    missingSummary: isCovered
      ? `All ${actualQuestions.length} questions covered`
      : `Missing: ${missingSummary}`,
    nextSuggestedRange,
  };
}

/**
 * Intelligent range conflict resolver:
 * Trims, splits, or removes existing ranges that conflict with a new range,
 * guaranteeing zero overlap without forcing the teacher to manually delete existing rules.
 */
export function resolveRangeOverlap<T extends { from: number; to: number; id: string }>(
  existingRanges: T[],
  newRange: { from: number; to: number }
): T[] {
  const result: T[] = [];
  for (const r of existingRanges) {
    // 1. Existing range is completely swallowed by the new range -> drop it
    if (r.from >= newRange.from && r.to <= newRange.to) {
      continue;
    }
    // 2. Existing range completely encloses new range -> split into left and right
    if (r.from < newRange.from && r.to > newRange.to) {
      result.push({ ...r, to: newRange.from - 1, id: `${r.from}-${newRange.from - 1}-${Date.now()}` });
      result.push({ ...r, from: newRange.to + 1, id: `${newRange.to + 1}-${r.to}-${Date.now() + 1}` });
      continue;
    }
    // 3. Overlaps on the right side of r
    if (r.from < newRange.from && r.to >= newRange.from) {
      result.push({ ...r, to: newRange.from - 1 });
      continue;
    }
    // 4. Overlaps on the left side of r
    if (r.from <= newRange.to && r.to > newRange.to) {
      result.push({ ...r, from: newRange.to + 1 });
      continue;
    }
    // No overlap
    result.push(r);
  }
  return result.filter((r) => r.from <= r.to).sort((a, b) => a.from - b.from);
}


