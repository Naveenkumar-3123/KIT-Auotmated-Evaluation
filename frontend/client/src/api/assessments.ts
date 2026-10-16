/** Assessment + ingestion API calls (Milestone 3). */
import { apiFetch } from "./client";

export interface Assessment {
  id: string;
  teacher_id: string;
  class_id: string | null;
  subject_id: string | null;
  title: string;
  status: string;
  pass_percentage: string | number;
  total_marks: string | number;
  question_count: number;
  class_name?: string | null;
  subject_name?: string | null;
}

export interface StudentZipEntryResult {
  roll_number: string | null;
  file_name: string;
  status: "valid" | "duplicate" | "invalid_corrupt" | "invalid_filename" | "invalid_duplicate" | "unsupported_type" | "unsafe_path" | "too_large";
  reason?: string | null;
  submission_id?: string;
  flags?: string[];
}

export interface StudentZipUploadResult {
  assessment_id: string;
  detected: number;
  valid: number;
  invalid: number;
  students: StudentZipEntryResult[];
}

export interface SubmissionRecord {
  id: string;
  assessment_id: string;
  roll_number: string;
  status: string;
  status_detail?: string | null;
  page_count: number | null;
  flags: string[];
}

export function createAssessment(payload: { title?: string } = {}): Promise<{ assessment: Assessment }> {
  return apiFetch("/assessments", { method: "POST", body: JSON.stringify(payload) });
}

export function updateAssessmentDetails(
  id: string,
  payload: { title?: string; class_name?: string; subject_name?: string; pass_percentage?: number },
): Promise<{ assessment: Assessment }> {
  return apiFetch(`/assessments/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function uploadStudentZip(id: string, file: File): Promise<StudentZipUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(`/assessments/${id}/student-zip`, { method: "POST", body: form, upload: true });
}

export function listStudents(id: string): Promise<SubmissionRecord[]> {
  return apiFetch(`/assessments/${id}/students`);
}

// ---------------------------------------------------------------------------
// Milestone 6: evaluation workspace
// ---------------------------------------------------------------------------

export interface AssessmentCounts {
  total: number;
  ready: number;
  processing: number;
  completed: number;
  waiting_for_review: number;
  failed: number;
}

export interface AssessmentWithCounts extends Assessment {
  student_count: number;
  ready_count: number;
  processing_count: number;
  completed_count: number;
  review_count: number;
  failed_count: number;
}

export interface AssessmentStatusStudent {
  submission_id: string;
  roll_number: string;
  status: string;
  status_detail?: string | null;
  current_stage?: string | null;
  progress_completed?: number | null;
  progress_total?: number | null;
  worker_id?: string | null;
}

export interface AssessmentStatusResponse {
  assessment_id: string;
  status: Assessment["status"];
  total_marks: number;
  pass_percentage: number;
  summary: AssessmentCounts;
  students: AssessmentStatusStudent[];
  answer_key: { id: string; status: string; version: number } | null;
}

export function listAssessments(): Promise<AssessmentWithCounts[]> {
  return apiFetch("/assessments");
}

export function getAssessmentStatus(id: string): Promise<AssessmentStatusResponse> {
  return apiFetch(`/assessments/${id}/status`);
}

export function startEvaluation(
  id: string,
): Promise<{ assessment_id: string; status: string; submissions_queued: number }> {
  return apiFetch(`/assessments/${id}/start`, { method: "POST", body: JSON.stringify({}) });
}

export function uploadAnswerPaper(
  id: string,
  file: File,
): Promise<StudentZipUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(`/assessments/${id}/submissions`, { method: "POST", body: form, upload: true });
}

export function deleteStudentSubmissions(id: string): Promise<{ status: string; message: string }> {
  return apiFetch(`/assessments/${id}/student-submissions`, { method: "DELETE" });
}

export function deleteAnswerKey(id: string): Promise<{ status: string; message: string }> {
  return apiFetch(`/assessments/${id}/answer-key`, { method: "DELETE" });
}

