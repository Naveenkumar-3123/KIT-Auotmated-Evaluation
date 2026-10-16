/** STYLE: EvalAI teacher data — explicit, future-ready teaching relationships keep subject selection personal and assessment-focused. */
export interface DepartmentOption { id: string; name: string; shortName: string; }
export interface SubjectOption { id: string; name: string; departmentIds: string[]; }
export interface ClassOption { id: string; name: string; departmentId: string; }

export const departmentOptions: DepartmentOption[] = [
  { id: "cse", name: "Computer Science & Engineering", shortName: "CSE" },
  { id: "ece", name: "Electronics & Communication Engineering", shortName: "ECE" },
  { id: "it", name: "Information Technology", shortName: "IT" },
  { id: "aids", name: "Artificial Intelligence & Data Science", shortName: "AI & DS" },
  { id: "me", name: "Mechanical Engineering", shortName: "ME" },
  { id: "ce", name: "Civil Engineering", shortName: "CE" },
  { id: "eee", name: "Electrical & Electronics Engineering", shortName: "EEE" },
];

export const subjectOptions: SubjectOption[] = [
  { id: "machine-learning", name: "Machine Learning", departmentIds: ["cse", "aids"] },
  { id: "artificial-intelligence", name: "Artificial Intelligence", departmentIds: ["cse", "aids"] },
  { id: "deep-learning", name: "Deep Learning", departmentIds: ["cse", "aids"] },
  { id: "natural-language-processing", name: "Natural Language Processing", departmentIds: ["cse", "aids"] },
  { id: "data-structures", name: "Data Structures", departmentIds: ["cse", "it"] },
  { id: "operating-systems", name: "Operating Systems", departmentIds: ["cse", "it"] },
  { id: "database-management", name: "Database Management Systems", departmentIds: ["cse", "it", "aids"] },
  { id: "computer-networks", name: "Computer Networks", departmentIds: ["cse", "it", "ece"] },
  { id: "embedded-systems", name: "Embedded Systems", departmentIds: ["ece", "eee"] },
  { id: "digital-systems", name: "Digital Systems", departmentIds: ["ece", "eee"] },
  { id: "thermodynamics", name: "Thermodynamics", departmentIds: ["me"] },
  { id: "structural-analysis", name: "Structural Analysis", departmentIds: ["ce"] },
];

export const classOptions: ClassOption[] = [
  { id: "cse-ii", name: "CSE - II", departmentId: "cse" },
  { id: "cse-iii", name: "CSE - III", departmentId: "cse" },
  { id: "cse-iv", name: "CSE - IV", departmentId: "cse" },
  { id: "aids-ii", name: "AI & DS - II", departmentId: "aids" },
  { id: "ece-ii", name: "ECE - II", departmentId: "ece" },
  { id: "it-ii", name: "IT - II", departmentId: "it" },
];

export const departmentName = (departmentId: string) => departmentOptions.find((department) => department.id === departmentId)?.name ?? departmentId;
export const subjectName = (subjectId: string) => subjectOptions.find((subject) => subject.id === subjectId)?.name ?? subjectId;
export const allowedSubjectsForDepartments = (departmentIds: string[]) => subjectOptions.filter((subject) => subject.departmentIds.some((departmentId) => departmentIds.includes(departmentId)));
