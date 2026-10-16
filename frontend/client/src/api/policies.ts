/** Policy configuration + finalize API calls (Milestone 5). */
import { apiFetch } from "./client";
import type { Assessment } from "./assessments";

export interface PoliciesPayload {
  strictness: {
    mode: string;
    ranges?: Array<{ from: number; to: number; level: string }>;
    questions?: Array<{ question: number; level: string }>;
  };
  word_count: {
    mode: string;
    ranges?: Array<{ from: number; to: number; minimum_words: number; trigger_shortfall_words: number; marks_deducted: number }>;
    questions?: Array<{ question: number; minimum_words: number; trigger_shortfall_words: number; marks_deducted: number }>;
  };
  diagrams: {
    mode: string;
    ranges?: Array<{ from: number; to: number; required: boolean; minimum_diagrams: number; missing_diagram_deductions: number[] }>;
    questions?: Array<{ question: number; required: boolean; minimum_diagrams: number; missing_diagram_deductions: number[] }>;
  };
}

export interface ResolvedPolicy {
  question_number: number;
  version: number;
  strictness_level: string;
  minimum_words: number;
  word_count_mode: string;
  trigger_shortfall_words: number;
  marks_deducted: number;
  diagram_required: boolean;
  min_diagrams: number;
  missing_diagram_deductions: number[];
  source_rule_ids: string[];
  rubric_snapshot: Record<string, unknown>;
}

export function savePolicies(assessmentId: string, payload: PoliciesPayload): Promise<{ policy_version: number; question_count: number; policies: ResolvedPolicy[] }> {
  return apiFetch(`/assessments/${assessmentId}/policies`, { method: "PUT", body: JSON.stringify(payload) });
}

export function getResolvedPolicies(assessmentId: string): Promise<{ policies: ResolvedPolicy[]; total_maximum: number }> {
  return apiFetch(`/assessments/${assessmentId}/policies/resolved`);
}

export interface AssessmentSummaryCounts {
  total: number;
  processing: number;
  completed: number;
  waiting_for_review: number;
  failed: number;
}

export function finalizeAssessment(assessmentId: string, title?: string): Promise<{ assessment: Assessment; summary: AssessmentSummaryCounts }> {
  return apiFetch(`/assessments/${assessmentId}/finalize`, { method: "POST", body: JSON.stringify({ title }) });
}
