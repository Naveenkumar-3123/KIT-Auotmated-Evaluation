/** Answer-key API calls (Milestone 4). */
import { apiFetch } from "./client";

export interface AnswerKeyMeta {
  id: string;
  assessment_id: string;
  version: number;
  status: "parsing" | "parsed" | "reviewed" | "locked" | "failed";
  parse_error?: string | null;
  source_format: string;
  parser_model?: string | null;
  schema_version?: string;
  /** Live batch progress while status === "parsing" (big multi-page keys). */
  progress?: { done: number; total: number } | null;
}

export interface AnswerKeyDiagram {
  id: string;
  diagram_code: string;
  ordinal: number;
  type_label: string | null;
  source_page: number | null;
  bbox: number[] | null;
  parser_uncertain: boolean;
}

export interface AnswerKeyQuestion {
  id: string;
  question_number: number;
  question_text: string;
  maximum_marks: string | number;
  answer_type: string;
  expected_answer_text: string;
  concepts: Array<{ concept_code: string; description: string; maximum_marks: string | number }>;
  keywords: string[];
  mandatory_terms: string[];
  math_rubric: Array<{ step_id: string; description: string; marks: number }>;
  diagrams: AnswerKeyDiagram[];
  parser_uncertainties: string[];
}

export interface AnswerKeyPayload {
  answer_key: AnswerKeyMeta & { raw_parser_json?: unknown };
  questions: AnswerKeyQuestion[];
}

export function uploadAnswerKey(assessmentId: string, file: File): Promise<{ answer_key: AnswerKeyMeta }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(`/assessments/${assessmentId}/answer-key`, { method: "POST", body: form, upload: true });
}

export function getAnswerKey(keyId: string): Promise<AnswerKeyPayload> {
  return apiFetch(`/answer-keys/${keyId}`);
}

export interface QuestionReviewEdit {
  question_number: number;
  question_text?: string;
  expected_answer_text?: string;
  maximum_marks?: number;
  keywords?: string[];
  mandatory_terms?: string[];
}

export function reviewAnswerKey(
  keyId: string,
  payload: { edits: QuestionReviewEdit[]; confirm: boolean },
): Promise<AnswerKeyPayload> {
  return apiFetch(`/answer-keys/${keyId}/review`, { method: "PATCH", body: JSON.stringify(payload) });
}

/** Authenticated diagram image URL — fetched as a blob via the API client. */
export async function fetchDiagramBlobUrl(keyId: string, diagramId: string): Promise<string> {
  const response = await fetch(`/api/answer-keys/${keyId}/diagrams/${diagramId}.png`, {
    headers: await authHeaders(),
  });
  if (!response.ok) throw new Error(`Diagram request failed (${response.status})`);
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

async function authHeaders(): Promise<Record<string, string>> {
  const { currentSession } = await import("@/lib/supabase");
  const session = await currentSession().catch(() => null);
  return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
}
