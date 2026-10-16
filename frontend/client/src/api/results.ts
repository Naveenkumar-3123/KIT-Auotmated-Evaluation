import { apiFetch } from "./client";
import type { ProcessingCriterion } from "./processing";

// ---------------------------------------------------------------------------
// Teacher review (human-in-the-loop resolution)
// ---------------------------------------------------------------------------

export interface ReviewPendingQuestion {
  question_id: string;
  proposed_marks: number | null;
  maximum_marks: number | null;
  feedback?: string;
  reasons?: string[];
  criteria?: ProcessingCriterion[];
}

export interface ReviewRequestPayload {
  awaiting_review?: Record<string, ReviewPendingQuestion>;
  instructions?: string;
}

export interface SubmissionReviewRequest {
  job_id: string;
  status: string;
  review_request: ReviewRequestPayload;
}

export type ReviewDecision = { approved: boolean; final_marks?: number; reviewer_notes?: string };

/** Pending review questions (AI proposals) for a submission's active job. */
export function getSubmissionReviewRequest(_assessmentId: string, submissionId: string): Promise<SubmissionReviewRequest> {
  return apiFetch(`/assessments/submissions/${submissionId}/review-request`);
}

/** Apply teacher decisions ({questionId: {approved, final_marks?}}) and resume the job. */
export function submitReviewDecisions(
  _assessmentId: string,
  submissionId: string,
  decisions: Record<string, ReviewDecision>,
): Promise<{ job_id: string; status: string }> {
  return apiFetch(`/assessments/submissions/${submissionId}/review`, {
    method: "POST",
    body: JSON.stringify({ decisions }),
  });
}

/** Retry evaluation for a submission that failed or needs re-running. */
export function retrySubmissionEvaluation(submissionId: string): Promise<{ status: string; job_id: string; submission_id: string }> {
  return apiFetch(`/assessments/submissions/${submissionId}/retry`, {
    method: "POST",
  });
}


export interface ResultStudent {
  submission_id: string;
  roll_number: string;
  status: string;
  total: number;
  maximum: number;
  percentage: number | null;
  passed: boolean | null;
  teacher_modified: boolean;
  graded_questions: number;
  rank: number | null;
  highest?: boolean;
}

export interface ResultsSummary {
  total: number;
  completed: number;
  waiting_for_review: number;
  processing: number;
  ready: number;
  failed: number;
}

export interface AssessmentResults {
  assessment_id: string;
  title: string;
  status: string;
  question_count: number;
  total_marks: number;
  pass_percentage: number;
  summary: ResultsSummary;
  students: ResultStudent[];
}

export interface SubmissionQuestionResult {
  question_id: string;
  final_marks: number;
  maximum: number;
  source: "ai" | "review";
  ai_proposed: number | null;
  criteria: Array<Record<string, unknown>>;
  breakdown?: Record<string, unknown> | null;
  strictness_level?: string | null;
}

export interface SubmissionResultDetail {
  submission_id: string;
  roll_number: string;
  status: string;
  questions: SubmissionQuestionResult[];
}

export function getAssessmentResults(assessmentId: string): Promise<AssessmentResults> {
  return apiFetch<AssessmentResults>(`/assessments/${assessmentId}/results`);
}

export function getSubmissionResult(
  assessmentId: string,
  submissionId: string,
): Promise<SubmissionResultDetail> {
  return apiFetch<SubmissionResultDetail>(`/assessments/${assessmentId}/results/${submissionId}`);
}
