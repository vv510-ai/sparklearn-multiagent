import type { Cet6Kind, Cet6Preferences } from "./cet6";

export type AdviceAction = { kind: Cet6Kind; label: string; paper_id: string; source: string };
// Older saved reports retain their original text and remain readable.
export type AdviceSection = { kind: Cet6Kind; title: string; body?: string; analysis?: string; steps?: string[]; check?: string };
export type AdviceSource = { id: string; title: string; url: string; checked_on: string; supports: string };
export type TargetBreakdown = { listening: number; reading: number; writing_translation: number; reason: string };
export type AdviceText = {
  summary: string; priority_kind: Cet6Kind; rationale: string; uncertainty: string;
  score_analysis?: string; target_breakdown?: TargetBreakdown | null; plan_explanation?: string; closing?: string;
  sections: AdviceSection[]; week_note: string; stages: { title: string; text: string }[];
  followup_keys: ("preparation" | "reading_completion")[];
};
export type Cet6AdviceData = {
  status: "empty" | "running" | "ready" | "failed" | "unavailable";
  stale: boolean; input: Omit<Cet6Preferences, "daily_new_words" | "word_order">; profile_revision: number; message?: string;
  stale_reason?: "profile" | "report_update";
  generated_at?: string; model?: string; content: AdviceText;
  facts: { today: string; days_to_exam: number | null; date_state: "missing" | "past" | "today" | "upcoming"; score_gap: number | null; basis: string; daily_minutes: number };
  week: { day: number; kind: Cet6Kind; minutes: number; tasks: { kind: Cet6Kind; title: string; minutes: number }[] }[];
  actions: AdviceAction[];
  sources: AdviceSource[];
  previous?: { input: Omit<Cet6Preferences, "daily_new_words" | "word_order">; content: AdviceText; generated_at?: string; model?: string };
};
