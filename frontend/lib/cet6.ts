export type Cet6Kind = "listening" | "reading" | "writing" | "translation" | "vocabulary";
export const cet6Labels: Record<Cet6Kind, string> = { listening: "听力", reading: "阅读", writing: "写作", translation: "翻译", vocabulary: "词汇" };
export type Cet6Preferences = {
  goal: string; target_score: number | null; exam_date: string | null; daily_minutes: number;
  mode: "foundation" | "balanced" | "exam"; focus: Cet6Kind[];
  total_score: number | null; listening_score: number | null; reading_score: number | null; writing_translation_score: number | null;
};
export type Cet6Overview = {
  revision: number; preferences: Cet6Preferences; server_time: string; daily_new_limit: number; review_minutes: number;
  recommendation: { kind: Cet6Kind; id?: string; title: string; reason: string };
  stats: { collected: number; word_due: number; reading_due: number; practice_due: number };
  recent: { kind: Cet6Kind; at: string; independent: boolean; ratio?: number }[];
};
export type WordSummary = { id: string; word: string; level: "foundation" | "cet6"; phonetic: string; variants: string[]; derivatives: string[]; meaning: string; collected: boolean; status: string };
export type WordEntry = Omit<WordSummary, "meaning" | "collected" | "status"> & {
  senses: { id: string; definition: string }[]; source_pages: number[]; source_url: string; dictionary_url: string;
  role?: string; parents?: string[];
};
export type WordAttempt = { mode: "meaning" | "spelling"; started_at: string; revealed: boolean; early: boolean; used_help: boolean; answer?: string; correct?: boolean };
export type WordCard = {
  revision: number; sense_id: string; collected: boolean;
  contexts: { text: string; note: string; reading_id: string; source: string; saved_at: string; question_id?: string; question_number?: number; question_prompt?: string }[];
  tracks: Record<string, { scheduler?: string; due_at: string; attempts: number; independent_due_reviews: number }>;
  rating_options?: Record<string, string>;
  active?: WordAttempt | null; last?: WordAttempt & { rating: string; basis: string; due_at: string; submitted_at: string; scheduling_reason?: string };
};
export type WordDetail = { version: string; entry: WordEntry; cards: WordCard[]; next_review: { sense_id: string; mode: "meaning" | "spelling" } };
export type WordCatalogue = { version: string; total: number; offset: number; items: WordSummary[];
  manifest: { title: string; scope: string; notes: string[]; entry_count: number; headword_rows: number; declared_headword_rows: number; source_url: string; dictionary_url: string; license_url: string } };
export type PracticeTask = { id: string; kind: Cet6Kind; title: string; minutes: number; source: string; prompt: string;
  speech_text?: string; audio_url?: string; options?: string[]; answer?: string; reference?: string; checklist?: string[] };
export type PracticeFirst = { answer: string; submitted_at: string; used_help: boolean; timed: boolean; elapsed_seconds: number; correct?: boolean };
export type PracticeSession = { task: PracticeTask; revision: number; phase: "answer" | "feedback" | "done"; answer: string;
  revision_text?: string; reflection?: string; first?: PracticeFirst; used_help?: boolean; timed?: boolean; due_at?: string; last_early?: boolean;
  history: { first: PracticeFirst; revision_text: string; reflection: string; finished_at: string }[] };
export type PracticeSummary = Pick<PracticeTask, "id" | "kind" | "title" | "minutes" | "source"> & { progress: PracticeSession | null };

export function cet6Route(notebook: string, view: string, target?: string, review = false) {
  const url = new URL(window.location.href);
  url.searchParams.set("notebook", notebook); url.searchParams.set("cet6", view);
  url.searchParams.delete("cet6_word"); url.searchParams.delete("cet6_task"); url.searchParams.delete("cet6_review");
  if (view !== "reading") { url.searchParams.delete("reading"); url.searchParams.delete("reading_question"); }
  if (target && view === "vocabulary") url.searchParams.set("cet6_word", target);
  if (target && view === "vocabulary" && review) url.searchParams.set("cet6_review", "1");
  if (target && view === "practice") url.searchParams.set("cet6_task", target);
  if (target && view === "reading") url.searchParams.set("reading", target);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}
