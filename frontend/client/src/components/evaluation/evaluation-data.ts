/** STYLE: EvalAI evaluation domain — maps REAL backend assessment/submission
 * records onto the teacher-facing UI models. No mock fixtures: the page is
 * backed by the FastAPI control plane (Milestone 6). */
import type { AssessmentStatusStudent, AssessmentWithCounts, SubmissionRecord } from "@/api/assessments";

export type SheetStatus = "ready" | "processing" | "completed" | "needs-review";

export interface AnswerSheet {
  rollNumber: string;
  fileName: string;
  status: SheetStatus;
  rawStatus?: string;
  submissionId?: string;
  statusDetail?: string | null;
  currentStage?: string | null;
  progressCompleted?: number | null;
  progressTotal?: number | null;
  workerId?: string | null;
}

export interface ConfiguredEvaluation {
  id: string;
  className: string;
  subject: string;
  answerKeyName: string;
  strictnessMode: "Question ranges" | "Individual questions";
  strictnessSummary: string;
  students: AnswerSheet[];
  counts?: { total: number; processing: number; completed: number; review: number; failed: number };
}

/** Backend assessment row -> evaluation workspace card. */
export function toConfiguredEvaluation(item: AssessmentWithCounts): ConfiguredEvaluation {
  return {
    id: item.id,
    className: item.class_name || item.title || "Untitled class",
    subject: item.subject_name || item.title || "Subject not set",
    answerKeyName: `Parsed answer key · ${item.question_count} questions`,
    strictnessMode: "Question ranges",
    strictnessSummary:
      `${item.question_count} questions · max ${item.total_marks} marks · pass ${item.pass_percentage}%`,
    students: [],
    counts: {
      total: item.student_count,
      processing: item.processing_count,
      completed: item.completed_count,
      review: item.review_count,
      failed: item.failed_count,
    },
  };
}

const SUBMISSION_STATUS_MAP: Record<string, SheetStatus> = {
  pending: "ready",
  uploaded: "ready",
  ready: "ready",
  queued: "processing",
  processing: "processing",
  evaluating: "processing",
  completed: "completed",
  waiting_for_review: "needs-review",
  failed: "needs-review",
  invalid: "needs-review",
};

export function mapSubmissionStatus(status: string): SheetStatus {
  return SUBMISSION_STATUS_MAP[status] ?? "needs-review";
}

export function toAnswerSheet(record: SubmissionRecord | AssessmentStatusStudent): AnswerSheet {
  const rollNumber = record.roll_number;
  const submissionId =
    "submission_id" in record ? record.submission_id : (record as SubmissionRecord).id;
  const statusDetail = "status_detail" in record ? record.status_detail : null;
  const currentStage = "current_stage" in record ? record.current_stage : null;
  const progressCompleted = "progress_completed" in record ? record.progress_completed : null;
  const progressTotal = "progress_total" in record ? record.progress_total : null;
  const workerId = "worker_id" in record ? record.worker_id : null;

  return {
    rollNumber,
    fileName: `${rollNumber}.pdf`,
    status: mapSubmissionStatus(record.status),
    rawStatus: record.status,
    submissionId,
    statusDetail,
    currentStage,
    progressCompleted,
    progressTotal,
    workerId,
  };
}

export const friendlyStatus: Record<SheetStatus, string> = {
  ready: "Ready",
  processing: "Processing",
  completed: "Completed",
  "needs-review": "Needs Review",
};

export const statusTone: Record<SheetStatus, string> = {
  ready: "bg-[#e8f7ef] text-[#4f8f70]",
  processing: "bg-[#edf0ff] text-[#6276e5]",
  completed: "bg-[#e8f7ef] text-[#4f8f70]",
  "needs-review": "bg-[#fff2df] text-[#b57626]",
};

export interface PipelineStageDef {
  id: string;
  keys: string[];
  title: string;
  description: string;
  stepNumber: number;
}

export const EVALUATION_PIPELINE_STAGES: PipelineStageDef[] = [
  {
    id: "ingestion",
    keys: ["validating", "rendering_pdf"],
    title: "PDF Ingestion & Rendering",
    description: "Validating scanned submission and rendering high-resolution page bitmaps.",
    stepNumber: 1,
  },
  {
    id: "segmentation",
    keys: ["segmenting"],
    title: "Layout & Bounding Box Segmentation",
    description: "Detecting handwritten answer regions, borders, question labels, and diagram anchors.",
    stepNumber: 2,
  },
  {
    id: "mapping",
    keys: ["mapping_questions"],
    title: "Question Alignment to Answer Key",
    description: "Correlating detected answer regions to exact question numbers in the teacher rubric.",
    stepNumber: 3,
  },
  {
    id: "ocr",
    keys: ["ocr"],
    title: "Handwriting OCR & Diagram Recognition",
    description: "Transcribing handwritten text via vision perception and analyzing scientific figures.",
    stepNumber: 4,
  },
  {
    id: "evaluation",
    keys: ["reconstructing", "evaluating"],
    title: "AI Semantic Rubric & Strictness Evaluation",
    description: "Grading student explanations against criteria, mandatory keywords, and penalty bounds.",
    stepNumber: 5,
  },
  {
    id: "finalizing",
    keys: ["calculating_risk", "waiting_for_review", "completed"],
    title: "Verification Consensus & Grade Synthesis",
    description: "Cross-verifier validation check, heuristic risk scoring, and finalizing final marks.",
    stepNumber: 6,
  },
];

export const pipelineStages = [
  ["Preparing document", "Preparing pages for processing."],
  ["Segmenting answers", "Detecting individual answer regions."],
  ["Extracting responses", "Reading handwritten or typed answers."],
  ["Matching questions", "Associating responses with question numbers."],
  ["Evaluating answers", "Comparing responses with the configured answer key."],
  ["Calculating marks", "Applying evaluation rules and allocated marks."],
  ["Finalizing", "Saving evaluation results."],
] as const;
