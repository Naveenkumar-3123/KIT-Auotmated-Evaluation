/** Processing-pipeline evidence API — powers the Results "View Processing
 * Details" drawer with real pipeline artifacts and grading telemetry. */
import { apiFetch, apiFetchObjectUrl } from "./client";

export interface ProcessingJobInfo {
  job_id: string | null;
  status: string | null;
  current_stage: string | null;
  attempt: number | null;
  progress_completed: number | null;
  progress_total: number | null;
  worker_id: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface ProcessingCriterion {
  criterion_id?: string;
  criterion?: string;
  name?: string;
  status?: string;
  match_type?: string;
  proposed_marks?: number | null;
  maximum_marks?: number | null;
  reason?: string | null;
  student_evidence?: Array<{ quote?: string; page_number?: number }>;
}

export interface ProcessingQuestion {
  question_id: string;
  proposed_marks: number | null;
  maximum_marks: number | null;
  feedback?: string | null;
  reasons?: string[];
  risk_level?: string | null;
  risk_score?: number | null;
  auto_approve?: boolean | null;
  review_reasons?: string[];
  grader_disagreement?: number | null;
  ocr_uncertainty?: number | null;
  major_disagreement?: boolean | null;
  criteria?: ProcessingCriterion[];
  teacher_decision?: {
    approved: boolean | null;
    final_marks: number | null;
    reviewer_notes: string | null;
  };
}

export interface ProcessingArtifacts {
  original: string[];
  preprocessed: string[];
  segments: string[];
}

export interface ProcessingRegionOcr {
  raw_text: string;
  lines?: string[];
  uncertain_spans?: Array<Record<string, unknown>>;
  flags?: string[];
  word_count?: number | null;
  status?: string | null;
  model_id?: string | null;
}

export interface ProcessingRegion {
  region_id: string;
  page_number: number;
  question_id: string | null;
  bbox: Record<string, number | null>;
  region_type: string;
  reading_order: number;
  confidence: number | null;
  ocr: ProcessingRegionOcr | null;
}

export interface ProcessingSpan {
  question_id: string;
  start_page: number;
  end_page: number;
  region_ids: string[];
  mapping_uncertain: boolean;
  uncertainty_reasons: string[];
}

export interface ProcessingPageMeta {
  page_number: number;
  width_px: number | null;
  height_px: number | null;
  quality_flags: string[];
}

export interface ProcessingDetails {
  submission_id: string;
  roll_number: string;
  status: string;
  page_count: number | null;
  job: ProcessingJobInfo | null;
  questions: Record<string, ProcessingQuestion>;
  artifacts: ProcessingArtifacts;
  /** DB-backed perception evidence (written by the worker on job completion). */
  regions?: ProcessingRegion[];
  spans?: ProcessingSpan[];
  pages?: ProcessingPageMeta[];
}

export type ProcessingImageKind = keyof ProcessingArtifacts;

/** Pipeline evidence for one submission (job status, grading data, artifacts). */
export function getProcessingDetails(submissionId: string): Promise<ProcessingDetails> {
  return apiFetch<ProcessingDetails>(`/assessments/submissions/${submissionId}/processing`);
}

/** Authenticated processing-artifact image URL (fetched as a blob). */
export function fetchProcessingImageUrl(
  submissionId: string,
  kind: ProcessingImageKind,
  filename: string,
): Promise<string> {
  return apiFetchObjectUrl(
    `/assessments/submissions/${submissionId}/processing/images/${kind}/${filename}`,
  );
}
