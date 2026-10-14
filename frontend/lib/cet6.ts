export type Cet6Kind = "listening" | "reading" | "writing" | "translation" | "vocabulary";
export const cet6Labels: Record<Cet6Kind, string> = { listening: "听力", reading: "阅读", writing: "写作", translation: "翻译", vocabulary: "词汇" };
export type WordOrder = "priority" | "family" | "alphabetical" | "random";
export const wordOrders: Record<WordOrder, string> = { priority: "重点词优先", family: "词族一起背", alphabetical: "字母顺序", random: "打乱顺序" };
export type WordFamily = { id: string; label: string; entry_ids: string[]; words: string[]; total: number; learned: number };
export type VocabularyCoverage = { total: number; learned: number; remaining: number; priority_total: number; priority_learned: number; foundation_total: number; foundation_learned: number };
export type Cet6Preferences = {
  goal: string; target_score: number | null; exam_date: string | null; daily_minutes: number; daily_new_words: number;
  word_order: WordOrder;
  mode: "foundation" | "balanced" | "exam"; focus: Cet6Kind[];
  total_score: number | null; listening_score: number | null; reading_score: number | null; writing_translation_score: number | null;
  preparation: "unknown" | "none" | "irregular" | "regular";
  reading_completion: "unknown" | "finished" | "unfinished" | "not_taken";
};
export type Cet6Overview = {
  revision: number; preferences: Cet6Preferences; server_time: string; daily_new_limit: number; review_minutes: number;
  recommendation: { kind: Cet6Kind; id?: string; title: string; reason: string };
  stats: { collected: number; word_due: number; reading_due: number; practice_due: number };
  recent: { kind: Cet6Kind; at: string; independent: boolean; ratio?: number }[];
};
export type WordSummary = { id: string; word: string; level: "foundation" | "cet6" | "reading"; phonetic: string; variants: string[]; derivatives: string[]; meaning: string; collected: boolean; status: string; family: WordFamily | null };
export type WordEntry = Omit<WordSummary, "meaning" | "collected" | "status" | "family"> & {
  senses: { id: string; definition: string; source_label?: string; source_url?: string }[]; source_pages: number[]; source_url: string; dictionary_url: string;
  role?: string; parents?: string[];
};
export type WordAttempt = { mode: "meaning" | "spelling"; started_at: string; revealed: boolean; early: boolean; used_help: boolean; help_reason?: string; answer?: string; correct?: boolean };
export type WordCard = {
  revision: number; sense_id: string; collected: boolean; queued_at?: string | null;
  contexts: { text: string; note: string; surface_form?: string; surface_forms?: string[]; reading_id: string; source: string; saved_at: string; question_id?: string; question_number?: number; question_prompt?: string; paper_id?: string; paper_question?: number; exam_id?: string; exam_kind?: string; exam_question?: number; exam_version?: string }[];
  tracks: Record<string, { scheduler?: string; due_at: string; attempts: number; independent_due_reviews: number }>;
  rating_options?: Record<string, string>;
  active?: WordAttempt | null; last?: WordAttempt & { rating: string; basis: string; due_at: string; submitted_at: string; scheduling_reason?: string };
};
export type WordDetail = { version: string; entry: WordEntry; cards: WordCard[]; preferred_sense_id: string; next_review: { sense_id: string; mode: "meaning" | "spelling" }; family: WordFamily | null };
export type WordLookup = {
  query: string; normalized: string; status: "matched" | "ambiguous" | "not_found"; auto_entry_id: string | null;
  usage_hint: string; dictionary_url: string; note: string;
  matches: { entry_id: string | null; word: string; codes: string[]; forms: string[]; match_kind: string;
    meaning: string; source_url: string; collectible: boolean; in_study_list?: boolean; suggested_sense_id?: string | null }[];
};
export type WordPlan = { day: string; timezone: string; target: number; new_done: number; new_remaining: number;
  new_ids: string[]; completed_ids: string[]; review_due: number; review_done: number; profile_revision: number; available_new: number;
  word_order: WordOrder; coverage: VocabularyCoverage; next_family: WordFamily | null; protected_count: number };
export type WordLesson = { status: "ready"; origin: "curated" | "generated"; version: string; source_note: string;
  focus: string; explanation: string; usage: string[]; example: { text: string; translation: string; note: string };
  contrast: string; memory: string; check: { stem: string; options: string[]; answer: string; explanation: string };
  sources: { title: string; url: string; supports: string; checked_on?: string }[];
  exam_occurrences: { label: string; url: string; note: string }[] };
export type VocabularyTopic = { id: string; title: string; focus: string; words: string[]; reference_words: string[];
  checks: { id: string; prompt: string; options: string[]; answer: number; explanation: string; sources: { title: string; url: string }[] }[] };
export type WordCatalogue = { version: string; total: number; offset: number; items: WordSummary[]; plan: WordPlan | null;
  topics: { id: string; title: string; total: number }[]; topic: VocabularyTopic | null;
  order: WordOrder; coverage: VocabularyCoverage;
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
  url.searchParams.delete("cet6_paper");
  url.searchParams.delete("cet6_paper_question");
  url.searchParams.delete("cet6_round");
  url.searchParams.delete("cet6_start");
  if (view !== "exams") { url.searchParams.delete("exam_kind"); url.searchParams.delete("exam_paper"); url.searchParams.delete("exam_question"); }
  if (view !== "reading") { url.searchParams.delete("reading"); url.searchParams.delete("reading_question"); }
  if (target && view === "vocabulary") url.searchParams.set("cet6_word", target);
  if (target && view === "vocabulary" && review) url.searchParams.set("cet6_review", "1");
  if (target && view === "practice") url.searchParams.set("cet6_task", target);
  if (target && view === "papers") url.searchParams.set("cet6_paper", target);
  if (target && view === "reading") url.searchParams.set("reading", target);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}
