/** Answer-key API calls (Milestone 4). */
import { apiFetch, ApiError } from "./client";
import { currentSession } from "@/lib/auth";

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
  progress?: { done: number; total: number; percent?: number; stage?: string; message?: string } | null;
}

export interface QuestionOption {
  option_code: string;
  option_title: string;
  question_text: string;
  expected_answer_text: string;
  maximum_marks: string | number;
  expected_concepts?: Array<{ concept_code: string; description: string; maximum_marks: string | number }>;
  keywords?: string[];
  mandatory_terms?: string[];
}

export interface AnswerKeyDiagram {
  id: string;
  diagram_code: string;
  ordinal: number;
  type_label: string | null;
  source_page: number | null;
  bbox: number[] | null;
  parser_uncertain: boolean;
  option_code?: string | null;
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
  options?: QuestionOption[];
}

export interface AnswerKeyPayload {
  answer_key: AnswerKeyMeta & { raw_parser_json?: unknown };
  questions: AnswerKeyQuestion[];
}

export function uploadAnswerKey(
  assessmentId: string,
  file: File,
  onUploadProgress?: (percent: number) => void,
): Promise<{ answer_key: AnswerKeyMeta }> {
  const form = new FormData();
  form.append("file", file);

  if (!onUploadProgress) {
    return apiFetch(`/assessments/${assessmentId}/answer-key`, { method: "POST", body: form, upload: true });
  }

  return new Promise(async (resolve, reject) => {
    try {
      const xhr = new XMLHttpRequest();
      const session = await currentSession().catch(() => null);
      const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";
      xhr.open("POST", `${apiBase}/assessments/${assessmentId}/answer-key`);
      if (session?.access_token) {
        xhr.setRequestHeader("Authorization", `Bearer ${session.access_token}`);
      }
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) {
          const pct = Math.round((e.loaded / e.total) * 100);
          onUploadProgress(pct);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (err) {
            reject(err);
          }
        } else {
          let detail = `${xhr.status} ${xhr.statusText}`;
          try {
            const body = JSON.parse(xhr.responseText);
            if (body?.detail) detail = body.detail;
          } catch {}
          reject(new ApiError(xhr.status, detail));
        }
      };
      xhr.onerror = () => reject(new ApiError(xhr.status || 500, "Network error during upload"));
      xhr.send(form);
    } catch (err) {
      reject(err);
    }
  });
}

export function getAnswerKey(keyId: string): Promise<AnswerKeyPayload> {
  return apiFetch(`/answer-keys/${keyId}`);
}

export interface QuestionReviewEdit {
  question_number: number;
  question_text?: string;
  expected_answer_text?: string;
  new_question_number?: number;
  maximum_marks?: number;
  keywords?: string[];
  mandatory_terms?: string[];
  options?: QuestionOption[];
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

export async function uploadQuestionDiagram(
  keyId: string,
  questionNumber: number,
  file: File,
  optionCode?: string,
  typeLabel?: string
): Promise<{ diagram: AnswerKeyDiagram }> {
  const formData = new FormData();
  formData.append("file", file);
  if (optionCode) formData.append("option_code", optionCode);
  if (typeLabel) formData.append("type_label", typeLabel);

  const response = await fetch(`/api/answer-keys/${keyId}/questions/${questionNumber}/diagrams`, {
    method: "POST",
    headers: await authHeaders(),
    body: formData,
  });
  if (!response.ok) throw new Error(`Diagram upload failed (${response.status})`);
  return response.json();
}

export async function deleteQuestionDiagram(keyId: string, diagramId: string): Promise<void> {
  const response = await fetch(`/api/answer-keys/${keyId}/diagrams/${diagramId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!response.ok) throw new Error(`Diagram deletion failed (${response.status})`);
}

async function authHeaders(): Promise<Record<string, string>> {
  const { currentSession } = await import("@/lib/auth");
  const session = await currentSession().catch(() => null);
  return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
}
