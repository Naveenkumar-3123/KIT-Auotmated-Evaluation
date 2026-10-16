/** STYLE: EvalAI results domain — teacher-facing assessment decisions are modeled separately from optional technical evidence. */
export type ResultStatus = "completed" | "needs-review" | "teacher-modified";
export type Strictness = "lenient" | "moderate" | "strict";

export interface QuestionResult {
  id: string;
  number: number;
  questionText: string;
  marksAwarded: number;
  maxMarks: number;
  strictness: Strictness;
  studentAnswer: string;
  expectedPoints: string[];
  evaluation: string;
  needsReview: boolean;
}

export interface StudentResult {
  id: string;
  rollNumber: string;
  totalScore: number;
  maxScore: number;
  status: ResultStatus;
  questionResults: QuestionResult[];
}

export interface ResultClass {
  id: string;
  className: string;
  subject: string;
  totalStudents: number;
  totalMarks: number;
  completedAt: string;
  completionStatus: "complete" | "partial";
  students: StudentResult[];
}

const questionBlueprints = [
  ["Define bagging.", ["Builds multiple training samples", "Combines model outputs", "Reduces variance"], "The response identifies the ensemble approach and the use of multiple sampled datasets."],
  ["Explain Random Forest.", ["Ensemble of decision trees", "Random subsets of data", "Majority voting or averaging", "Reduces variance"], "The response identifies the main idea but needs closer review against the required aggregation detail."],
  ["List practical benefits of ensemble learning.", ["Improves generalisation", "Reduces overfitting", "Combines complementary models"], "The response covers the main benefits expected by the marking scheme."],
  ["Compare bagging and boosting.", ["Independent versus sequential learning", "Variance reduction", "Bias reduction", "Weighted combination"], "The response explains the core distinction and compares how the two approaches improve a model."],
  ["What is a decision boundary?", ["Separates predicted classes", "Defined by model behaviour", "Used for classification"], "The answer states the required concept in a concise and relevant way."],
  ["Describe model validation.", ["Uses held-out data", "Checks generalisation", "Guides model selection"], "The response is plausible but one required validation detail should be reviewed by the teacher."],
  ["What does overfitting mean?", ["Fits training data too closely", "Weak generalisation", "Validation performance drops"], "The student identifies the central risk and its effect on unseen data."],
  ["State the purpose of feature scaling.", ["Normalises feature ranges", "Supports distance-based models", "Prevents dominance by large values"], "The response includes the purpose and a relevant modelling implication."],
  ["Explain cross-validation.", ["Splits data into folds", "Rotates validation folds", "Estimates generalisation"], "The answer reflects the expected multi-fold validation process."],
  ["What is a confusion matrix?", ["Compares predicted and actual classes", "Shows error categories", "Supports classification metrics"], "The explanation connects the matrix to practical classification evaluation."],
  ["Define precision.", ["True positives among predicted positives", "Measures positive prediction quality"], "The student states the expected relationship accurately."],
  ["Define recall.", ["True positives among actual positives", "Measures coverage of positive cases"], "The response uses the correct interpretation of recall."],
  ["What is regularisation?", ["Constrains model complexity", "Reduces overfitting", "Adds a penalty term"], "The answer provides the intended relationship between complexity and generalisation."],
  ["Describe gradient descent.", ["Optimises a loss function", "Moves along negative gradient", "Uses iterative updates"], "The core optimisation process is described clearly."],
  ["What does a learning rate control?", ["Update step size", "Affects convergence", "Too high can overshoot"], "The response covers the relevant effect on training updates."],
  ["Explain supervised learning.", ["Uses labelled data", "Learns input-output mapping", "Supports prediction"], "The answer includes the expected labelled-data framing."],
  ["Explain unsupervised learning.", ["Uses unlabelled data", "Finds patterns or groups", "Does not require target labels"], "The response distinguishes the unlabelled setting appropriately."],
  ["What is clustering?", ["Groups similar observations", "Uses similarity criteria", "Explores structure in data"], "The answer correctly describes the grouping objective."],
  ["What is dimensionality reduction?", ["Reduces feature count", "Retains useful structure", "Can simplify modelling"], "The response identifies the purpose and expected outcome."],
  ["State one limit of a simple baseline model.", ["May underfit complex data", "Can miss nonlinear relationships", "Needs context-specific evaluation"], "The student identifies a valid limitation of a simple baseline."],
] as const;

const questionMaxima = [2, 2, 5, 10, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 6];
const referenceScores = [2, 1, 4, 8, ...Array(15).fill(4), 3];

function distributeScore(totalScore: number) {
  const scores = questionMaxima.map((maxMarks) => Math.floor((maxMarks * totalScore) / 100));
  let remaining = totalScore - scores.reduce((total, score) => total + score, 0);
  let pointer = 0;
  while (remaining > 0) {
    if (scores[pointer] < questionMaxima[pointer]) {
      scores[pointer] += 1;
      remaining -= 1;
    }
    pointer = (pointer + 1) % questionMaxima.length;
  }
  return scores;
}

function makeQuestions(rollNumber: string, totalScore: number, status: ResultStatus): QuestionResult[] {
  const scores = rollNumber === "24CSE001" ? referenceScores : distributeScore(totalScore);
  return questionBlueprints.map(([questionText, expectedPoints, evaluation], index) => {
    const number = index + 1;
    const needsReview = status === "needs-review" && number === 6;
    return {
      id: `${rollNumber}-q${number}`,
      number,
      questionText,
      marksAwarded: scores[index],
      maxMarks: questionMaxima[index],
      strictness: number === 2 || number === 6 ? "strict" : number >= 15 ? "lenient" : "moderate",
      studentAnswer: number === 2 ? "Random forest are many decision tree using different random sample of data. Their output is collected for a final result." : `The student response for question ${number} is retained in the result record for teacher review.` ,
      expectedPoints: [...expectedPoints],
      evaluation: needsReview ? "The response is partly aligned with the marking scheme, but the wording is uncertain enough to require teacher confirmation." : evaluation,
      needsReview,
    };
  });
}

function makeStudents(prefix: string, start: number, scores: number[], specialFirst = false): StudentResult[] {
  return scores.map((totalScore, index) => {
    const rollNumber = `${prefix}${String(start + index).padStart(3, "0")}`;
    const status: ResultStatus = index === 2 ? "needs-review" : index === 7 ? "teacher-modified" : "completed";
    return { id: rollNumber.toLowerCase(), rollNumber: specialFirst && index === 0 ? "24CSE001" : rollNumber, totalScore, maxScore: 100, status, questionResults: makeQuestions(specialFirst && index === 0 ? "24CSE001" : rollNumber, totalScore, status) };
  });
}

export const resultClasses: ResultClass[] = [
  { id: "eval-cse-ii", className: "CSE - II", subject: "Machine Learning", totalStudents: 24, totalMarks: 100, completedAt: "Completed today", completionStatus: "complete", students: makeStudents("24CSE", 1, [78, 82, 74, 61, 94, 76, 69, 84, 73, 71, 79, 68, 88, 77, 65, 83, 72, 75, 81, 70, 86, 66, 80, 76], true) },
  { id: "eval-cse-iii", className: "CSE - III", subject: "Data Structures", totalStudents: 12, totalMarks: 100, completedAt: "Completed today", completionStatus: "complete", students: makeStudents("24CSE", 31, [85, 71, 78, 69, 90, 76, 72, 82, 74, 67, 88, 79]) },
  { id: "eval-cse-iv", className: "CSE - IV", subject: "Compiler Design", totalStudents: 18, totalMarks: 100, completedAt: "15 of 18 completed", completionStatus: "partial", students: makeStudents("24CSE", 51, [74, 68, 81, 70, 89, 76, 64, 83, 72, 78, 69, 85, 73, 66, 80]) },
];

export function getResultClass(classId: string | undefined) { return resultClasses.find((item) => item.id === classId); }

export function getStudentResult(classId: string | undefined, studentId: string | undefined) { return getResultClass(classId)?.students.find((student) => student.id === studentId || student.rollNumber === studentId); }

export function getClassSummary(resultClass: ResultClass) {
  const scores = resultClass.students.map((student) => student.totalScore);
  return {
    evaluated: resultClass.students.length,
    total: resultClass.totalStudents,
    average: scores.reduce((total, score) => total + score, 0) / scores.length,
    highest: Math.max(...scores),
    reviewCount: resultClass.students.filter((student) => student.status === "needs-review").length,
  };
}

export const resultStatusLabel: Record<ResultStatus, string> = { completed: "Completed", "needs-review": "Needs Review", "teacher-modified": "Teacher Modified" };
export const resultStatusTone: Record<ResultStatus, string> = { completed: "bg-[#e8f7ef] text-[#4f8f70]", "needs-review": "bg-[#fff2df] text-[#b57626]", "teacher-modified": "bg-[#edf0ff] text-[#6276e5]" };
export const strictnessTone: Record<Strictness, string> = { lenient: "bg-[#edf5f1] text-[#54846b]", moderate: "bg-[#eef0ff] text-[#6374da]", strict: "bg-[#f5efff] text-[#8156ad]" };
