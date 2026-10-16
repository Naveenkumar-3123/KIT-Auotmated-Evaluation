/** STYLE: EvalAI subject entry — teacher-written subject names stay lightweight, clear, and reusable across profile and Configure contexts. */
export function parseSubjectNames(value: string): string[] {
  return Array.from(new Set(value.split(",").map((item) => item.trim()).filter(Boolean)));
}

export function subjectNamesToInput(subjects: string[]): string {
  return subjects.join(", ");
}
