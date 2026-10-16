/** Analytics API (Milestone 18) — real class/student analytics (#75-#79). */
import { apiFetch } from "./client";

export interface ClassAnalytics {
  assessment_id: string;
  title: string;
  status: string;
  total_marks: number;
  pass_percentage: number;
  students: { total: number; completed: number; waiting_for_review: number };
  based_on_completed: number;
  partial_note: string | null;
  class_average: number | null;
  class_average_pct: number | null;
  median_pct: number | null;
  highest: number | null;
  lowest: number | null;
  pass_count: number;
  fail_count: number;
  pass_percentage_actual: number | null;
  score_distribution: Record<string, number>;
  per_question: Array<{
    question_id: string;
    average_awarded: number;
    maximum: number;
    attainment_pct: number;
    difficulty: "easy" | "moderate" | "hard";
    failure_rate: number;
    avg_marks_lost: number;
  }>;
  concept_difficulty: Array<{ criterion_id: string; attainment_pct: number; samples: number; difficulty: string }>;
  teacher_review_frequency: number;
}

export interface StudentAnalytics {
  submission_id: string;
  roll_number: string;
  status: string;
  total: number;
  maximum: number;
  overall_max: number;
  percentage: number | null;
  passed: boolean | null;
  rank: number | null;
  questions: Array<{ question_id: string; awarded: number; maximum: number; source: string }>;
  strengths: Array<Record<string, unknown>>;
  weaknesses: Array<Record<string, unknown>>;
  missing_concepts: Array<Record<string, unknown>>;
  needs_review: string[];
  math_steps: Array<Record<string, unknown>>;
}

export function getClassAnalytics(assessmentId: string): Promise<ClassAnalytics> {
  return apiFetch<ClassAnalytics>(`/analytics/classes/${assessmentId}`);
}

export function getStudentAnalytics(submissionId: string): Promise<StudentAnalytics> {
  return apiFetch<StudentAnalytics>(`/analytics/students/${submissionId}`);
}
