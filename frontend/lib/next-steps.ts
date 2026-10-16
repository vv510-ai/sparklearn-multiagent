/**
 * Learning-loop recommendations shown under a finished result.
 *
 * Deterministic and explainable on purpose: each suggestion names the learning
 * reason (see → remember → practise → review). Nothing is generated until the
 * learner clicks, and no suggestion claims mastery.
 */
import type { ResourceItem } from "@/lib/types";

export type NextAction =
  | { type: "generate"; template: string; label: string; reason: string }
  | { type: "open"; panel: "mistakes" | "profile" | "path" | "resources"; label: string; reason: string };

const VIDEO = { type: "generate", template: "video", label: "讲解视频", reason: "看动态过程" } as const;
const ONE_PAGE = { type: "generate", template: "one_page", label: "一图看懂", reason: "回顾全局" } as const;
const SONG = { type: "generate", template: "memory_song", label: "记忆歌曲", reason: "把要点唱进记忆" } as const;
const QUIZ = { type: "generate", template: "quiz", label: "巩固测验", reason: "独立作答检验" } as const;
const CARDS = { type: "generate", template: "flashcards", label: "记忆闪卡", reason: "主动回忆" } as const;
const PITFALLS = { type: "generate", template: "error_confusion", label: "易错易混", reason: "弄清错因" } as const;
const NOTES = { type: "generate", template: "complete_notes", label: "学习笔记", reason: "沉淀成笔记" } as const;
const MISTAKES = { type: "open", panel: "mistakes", label: "错题本", reason: "随时重做" } as const;

function template(resource: ResourceItem): string {
  const payload = (resource.payload || {}) as Record<string, unknown>;
  return String(payload.template || "").toLowerCase();
}

export function nextStepsFor(resource: ResourceItem): NextAction[] {
  const payload = (resource.payload || {}) as Record<string, unknown>;
  if (payload.generation_mode === "unavailable") return [];
  const kind = resource.kind;
  if (kind === "video" || kind === "manim" || kind === "python_animation") return [ONE_PAGE, QUIZ, SONG];
  if (kind === "song") return [CARDS, QUIZ];
  if (kind === "quiz") return [PITFALLS, CARDS, MISTAKES];
  if (kind === "flashcards") return [QUIZ, SONG];
  if (kind === "mindmap") return [ONE_PAGE, QUIZ];
  if (kind === "ppt") return [QUIZ, CARDS];
  if (kind === "data_table" || kind === "infographic") return [SONG, QUIZ];
  if (kind === "doc") {
    const used = template(resource);
    if (used === "one_page") return [SONG, QUIZ, VIDEO];
    if (used === "interactive_audio") return [ONE_PAGE, QUIZ];
    if (used === "error_confusion") return [QUIZ, CARDS];
    if (used === "complete_notes" || used === "conversation_notes") return [CARDS, ONE_PAGE, SONG];
    return [ONE_PAGE, QUIZ];
  }
  return [];
}
