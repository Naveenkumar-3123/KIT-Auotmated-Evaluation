/** STYLE: EvalAI analytics — calm academic-performance data supports charts and drilldowns. */

export type StudentStatus = "Pass" | "Fail";

export interface AnalyticsStudent {
  rollNumber: string;
  score: number;
  percentage: number;
  rank: number;
  status: StudentStatus;
  questions: Array<{ label: string; percent: number; score: string }>;
  strongConcepts: string[];
  needsImprovement: string[];
  insight: string;
  revision: string;
}

const scores = [82, 74, 38, 94, 68, 62, 85, 71, 56, 49, 78, 66, 53, 89, 44, 76, 58, 91, 63, 31, 80, 72];
const ranks = [4, 8, 21, 1, 12, 15, 3, 10, 17, 19, 6, 14, 18, 2, 20, 7, 16, 2, 13, 22, 5, 9];
const statuses: StudentStatus[] = ["Pass", "Pass", "Fail", "Pass", "Pass", "Pass", "Pass", "Pass", "Pass", "Fail", "Pass", "Pass", "Pass", "Pass", "Fail", "Pass", "Pass", "Pass", "Pass", "Fail", "Pass", "Pass"];

export const analyticsStudents: AnalyticsStudent[] = scores.map((score, index) => ({
  rollNumber: `24CSE${String(index + 1).padStart(3, "0")}`,
  score,
  percentage: score,
  rank: ranks[index],
  status: statuses[index],
  questions: index === 0
    ? [{ label: "Q1", percent: 100, score: "2 / 2" }, { label: "Q2", percent: 50, score: "1 / 2" }, { label: "Q3", percent: 80, score: "4 / 5" }, { label: "Q4", percent: 40, score: "2 / 5" }, { label: "Q5", percent: 60, score: "3 / 5" }]
    : [{ label: "Q1", percent: 84, score: "2 / 2" }, { label: "Q2", percent: 72, score: "2 / 3" }, { label: "Q3", percent: 41, score: "2 / 5" }, { label: "Q4", percent: 65, score: "3 / 5" }, { label: "Q5", percent: 29, score: "1 / 4" }],
  strongConcepts: ["Decision Trees", "Random Sampling", "Basic Ensemble Learning"],
  needsImprovement: ["Bagging", "Majority Voting", "Variance Reduction"],
  insight: "The student understands basic ensemble-learning concepts but lost marks on how Bagging combines predictions and reduces variance.",
  revision: "Review Bagging, majority voting, and variance reduction before attempting similar questions again.",
}));

export const analyticsClassOptions = [
  { id: "cse-ii", className: "CSE - II", subject: "Machine Learning" },
  { id: "cse-iii", className: "CSE - III", subject: "Data Structures" },
  { id: "cse-iv", className: "CSE - IV", subject: "Compiler Design" },
];

export const summaryMetrics = [
  { label: "Pass percentage", value: "82%", detail: "18 of 22 students passed", tone: "pass" },
  { label: "Fail percentage", value: "18%", detail: "4 students below pass mark", tone: "fail" },
  { label: "Class average", value: "68.4", suffix: "/ 100", detail: "Assessment average", tone: "average" },
  { label: "Highest score", value: "94", suffix: "/ 100", detail: "Best evaluated answer", tone: "neutral" },
  { label: "Lowest score", value: "31", suffix: "/ 100", detail: "Lowest evaluated answer", tone: "neutral" },
];

export const scoreBands = [
  { label: "0–39", value: 2 }, { label: "40–49", value: 2 }, { label: "50–59", value: 3 }, { label: "60–69", value: 5 }, { label: "70–79", value: 5 }, { label: "80–89", value: 4 }, { label: "90–100", value: 1 },
];

export const questionPerformance = [
  { label: "Q1", value: 84 }, { label: "Q2", value: 72 }, { label: "Q3", value: 41 }, { label: "Q4", value: 65 }, { label: "Q5", value: 29 },
];

export const difficultConcepts = [
  { label: "Bagging", value: 62 }, { label: "Random Sampling", value: 48 }, { label: "Majority Voting", value: 45 }, { label: "Variance Reduction", value: 39 },
];

export const classInsights = [
  "Students performed well on basic definition questions but struggled with application-based questions.",
  "Question 5 had the lowest average score across the class.",
  "Bagging was the most frequently missed concept.",
];

export const teachingFocus = [
  "Revisit Bagging and ensemble-learning concepts.",
  "Spend more time on application-based questions.",
  "Review Question 5 concepts before the next assessment.",
];
