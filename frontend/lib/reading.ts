export type ReadingQuestion = {
  id: string; skill: string; prompt: string; options: string[];
  answer?: number; evidence?: { paragraph: number; quote: string };
  explanation?: string; optionFeedback?: string[]; takeaway?: string;
};
export type ReadingExercise = { id: string; context: string; prompt: string; options: string[]; kind: "short" | "original"; answer?: number; explanation?: string };
export type ReadingFirst = { answers: Record<string, number>; uncertain: string[]; used_help: boolean; correct: number; total: number; elapsed_seconds: number; submitted_at: string };
export type ReadingReview = { answers: Record<string, number>; correct: number; total: number; early: boolean; used_help: boolean; submitted_at: string; kind: string; feedback?: ReadingExercise[] };
export type ReadingSummary = {
  id: string; title: string; source: string; demo: boolean; source_type: string;
  phase: "answer" | "feedback" | "drill" | "drill_feedback" | "done" | "recall";
  due_at: string | null; first: ReadingFirst | null; reviews: number; sample_id: string; updated_at: string;
};
export type ReadingSession = ReadingSummary & {
  notebook_id: string; revision: number; version: string; elapsed_seconds: number;
  material: { title: string; englishTitle: string; source: string; source_url: string; source_type: string; paragraphs: string[]; questions: ReadingQuestion[] };
  draft: Record<string, number>; uncertain: string[]; used_help: boolean; note: string; focus_ids: string[];
  feedback?: ReadingQuestion[]; exercises?: ReadingExercise[]; exercise_answers: Record<string, number>;
  review: { stage: number; due_at: string | null } | null;
  history: ReadingReview[]; last_review?: ReadingReview;
  active_review?: { early: boolean; used_help?: boolean; started_at: string };
};
export type ReadingLibrary = {
  items: ReadingSummary[]; examples: { id: string; title: string; source: string; questions: number }[];
  due: number; legacy_due: number; private_completed: number; demo_completed: number; server_time: string;
};
// randomUUID is unavailable on an HTTP deployment, while getRandomValues is available.
export function readingRequestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const h = [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
export const readingDate = (s?: string | null) => s ? new Date(s).toLocaleString("zh-CN", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Shanghai" }) : "本轮复习已完成";
export const readingError = (e: unknown) => e instanceof Error ? e.message.replace(/^(GET|POST) \S+ → \d+:\s*/, "") : "暂时无法保存，请重试。";
