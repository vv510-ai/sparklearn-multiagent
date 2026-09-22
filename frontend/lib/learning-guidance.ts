/** Tool discovery is a pacing aid, never evidence of mastery. No model call is
 * made until the learner explicitly chooses a tool. Only completed teaching
 * turns are recorded; transcripts and personal goals are not stored here. */
export type SuggestedTool = "one_page" | "framework" | "conversation_notes" | "quiz";
export type StudyStage = "start" | "explore" | "organize";
export type LearningGuidance = {
  version: 1;
  turns: number;
  nextAt: number;
  muted: boolean;
  offered: SuggestedTool[];
  pending: SuggestedTool | null;
};

const TOOLS: SuggestedTool[] = ["one_page", "framework", "conversation_notes", "quiz"];
export const emptyGuidance = (): LearningGuidance => ({ version: 1, turns: 0, nextAt: 3, muted: false, offered: [], pending: null });

export function readGuidance(raw: string | null): LearningGuidance {
  try {
    const value = JSON.parse(raw || "null");
    if (value?.version !== 1 || !Number.isSafeInteger(value.turns) || value.turns < 0
      || !Number.isSafeInteger(value.nextAt) || value.nextAt < 3 || !Array.isArray(value.offered)) return emptyGuidance();
    return { version: 1, turns: value.turns, nextAt: value.nextAt, muted: value.muted === true,
      offered: value.offered.filter((id: SuggestedTool) => TOOLS.includes(id)),
      pending: TOOLS.includes(value.pending) ? value.pending : null };
  } catch { return emptyGuidance(); }
}

export function studyStage(state: LearningGuidance): StudyStage {
  return state.turns >= 3 ? "organize" : state.turns > 0 ? "explore" : "start";
}

export function recordLearningTurn(state: LearningGuidance, question: string): LearningGuidance {
  const next = { ...state, turns: state.turns + 1, pending: null };
  if (next.muted || next.turns < next.nextAt) return next;
  // These are product heuristics, not psychological scores or an LLM verdict.
  const preferred: SuggestedTool = /联系|区别|对比|关系|分类|框架|先后|全局|结构/.test(question) ? "framework"
    : /练习|试一试|做题|会了|懂了|掌握/.test(question) ? "quiz"
    : /复习|回顾|记不住|笔记|整理/.test(question) ? "conversation_notes" : "one_page";
  const candidate = [preferred, ...TOOLS].find(id => !state.offered.includes(id));
  return candidate ? { ...next, pending: candidate } : next;
}

export function dismissGuidance(state: LearningGuidance, mute = false): LearningGuidance {
  return { ...state, pending: null, muted: state.muted || mute, nextAt: state.turns + 3,
    offered: state.pending ? Array.from(new Set([...state.offered, state.pending])) : state.offered };
}

export const TOOL_SUGGESTIONS: Record<SuggestedTool, { title: string; reason: string }> = {
  one_page: { title: "一图看懂", reason: "已经积累了几轮讲解。可以把当前主题的概念、例子和易错点放到一张图里，回看时更容易找到主线。" },
  framework: { title: "框架导图", reason: "可以把本次对话里的知识点按层次和先后关系连起来，检查它们之间的联系。" },
  conversation_notes: { title: "本次学习笔记", reason: "可以把本次问过的问题、讲过的例子和还没解决的疑问整理在一起，方便下次接着学。" },
  quiz: { title: "巩固测验", reason: "已经讨论了几轮，可以换一道新题独立试试。看懂讲解是否能迁移到做题，还需要作答来确认。" },
};
