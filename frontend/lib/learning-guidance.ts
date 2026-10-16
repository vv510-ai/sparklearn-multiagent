/** Tool discovery is a pacing aid, never evidence of mastery. No model call is
 * made until the learner explicitly chooses a tool. Only completed teaching
 * turns are recorded; transcripts and personal goals are not stored here. */
export type SuggestedTool =
  | "one_page" | "framework" | "conversation_notes" | "quiz"
  | "video" | "memory_song" | "flashcards" | "error_confusion"
  | "complete_notes" | "interactive_audio" | "review_ppt" | "data_table";
export type StudyStage = "start" | "explore" | "organize";
export type LearningGuidance = {
  version: 1;
  turns: number;
  nextAt: number;
  muted: boolean;
  offered: SuggestedTool[];
  pending: SuggestedTool | null;
};

// Tools the conversation itself may propose (others appear as result follow-ups).
const CHAT_TOOLS: SuggestedTool[] = ["one_page", "video", "memory_song", "quiz", "framework", "conversation_notes"];
const ALL_TOOLS: SuggestedTool[] = [...CHAT_TOOLS, "flashcards", "error_confusion", "complete_notes", "interactive_audio", "review_ppt", "data_table"];
export const emptyGuidance = (): LearningGuidance => ({ version: 1, turns: 0, nextAt: 2, muted: false, offered: [], pending: null });

export function readGuidance(raw: string | null): LearningGuidance {
  try {
    const value = JSON.parse(raw || "null");
    if (value?.version !== 1 || !Number.isSafeInteger(value.turns) || value.turns < 0
      || !Number.isSafeInteger(value.nextAt) || value.nextAt < 2 || !Array.isArray(value.offered)) return emptyGuidance();
    return { version: 1, turns: value.turns, nextAt: value.nextAt, muted: value.muted === true,
      offered: value.offered.filter((id: SuggestedTool) => ALL_TOOLS.includes(id)),
      pending: ALL_TOOLS.includes(value.pending) ? value.pending : null };
  } catch { return emptyGuidance(); }
}

export function studyStage(state: LearningGuidance): StudyStage {
  return state.turns >= 3 ? "organize" : state.turns > 0 ? "explore" : "start";
}

/** Map the learner's own words to the format that fits the question type. */
export function preferredTool(question: string): SuggestedTool {
  if (/记不住|背不下|背诵|口诀|顺口溜|记忆|唱|歌/.test(question)) return "memory_song";
  if (/过程|步骤|流程|怎么运行|如何运作|机制|原理|演示|动画|推导|怎么算|执行/.test(question)) return "video";
  if (/练习|试一试|做题|会了|懂了|明白了|掌握|考考我/.test(question)) return "quiz";
  if (/复习|回顾|笔记|整理|记下来/.test(question)) return "conversation_notes";
  if (/先后|体系|知识点之间|章节|大纲/.test(question)) return "framework";
  return "one_page";
}

export function recordLearningTurn(state: LearningGuidance, question: string): LearningGuidance {
  const next = { ...state, turns: state.turns + 1, pending: null };
  if (next.muted || next.turns < next.nextAt) return next;
  // Product heuristics, not psychological scores or an LLM verdict.
  const preferred = preferredTool(question);
  const candidate = [preferred, ...CHAT_TOOLS].find(id => !state.offered.includes(id));
  return candidate ? { ...next, pending: candidate } : next;
}

export function dismissGuidance(state: LearningGuidance, mute = false): LearningGuidance {
  return { ...state, pending: null, muted: state.muted || mute, nextAt: state.turns + 3,
    offered: state.pending ? Array.from(new Set([...state.offered, state.pending])) : state.offered };
}

export const TOOL_SUGGESTIONS: Record<SuggestedTool, { title: string; reason: string }> = {
  one_page: { title: "一图看懂", reason: "已经聊了几轮。把概念、关系、例子和易错点画成一图（讲不完会自动拆成多张），回看时一眼找到主线。" },
  video: { title: "讲解视频", reason: "这个问题有明显的过程或机制。用动画把每一步演示出来，比文字更容易跟上。" },
  memory_song: { title: "记忆歌曲", reason: "需要背下来的要点可以先编成口诀，再唱成歌；之后用填空模式检查能不能主动回忆。" },
  framework: { title: "框架导图", reason: "把本次对话里的知识点按层次和先后关系连起来，检查它们之间的联系。" },
  conversation_notes: { title: "本次学习笔记", reason: "把问过的问题、讲过的例子和还没解决的疑问整理在一起，方便下次接着学。" },
  quiz: { title: "巩固测验", reason: "看懂讲解不等于会做。换几道新题独立试一试，错的地方会自动进入错题本。" },
  flashcards: { title: "记忆闪卡", reason: "把要点拆成一问一答，按遗忘曲线安排复习。" },
  error_confusion: { title: "易错易混", reason: "把容易混淆的概念放在一起对照，弄清错因。" },
  complete_notes: { title: "学习笔记", reason: "把定义、原理、步骤和例子整理成可复习的笔记。" },
  interactive_audio: { title: "互动讲解", reason: "先听一段短讲解，随时暂停提问。" },
  review_ppt: { title: "复习PPT", reason: "把当前主题整理成考前复习用的演示文稿。" },
  data_table: { title: "知识数据表", reason: "把可比较的概念整理成表格，方便筛选和复制。" },
};
