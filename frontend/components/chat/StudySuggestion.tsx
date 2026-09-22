"use client";

import { ArrowRight, Lightbulb } from "lucide-react";
import { TOOL_SUGGESTIONS, type SuggestedTool } from "@/lib/learning-guidance";

export default function StudySuggestion({ tool, onChoose, onDismiss }: {
  tool: SuggestedTool;
  onChoose: (tool: SuggestedTool) => void;
  onDismiss: (mute?: boolean) => void;
}) {
  const suggestion = TOOL_SUGGESTIONS[tool];
  return <section className="study-suggestion" aria-label="学习工具建议">
    <p className="study-suggestion-kicker"><Lightbulb size={16} aria-hidden /> 可以停下来整理一下，也可以继续聊</p>
    <h3>{suggestion.title}</h3>
    <p>{suggestion.reason}</p>
    <div className="study-suggestion-actions">
      <button type="button" onClick={() => onChoose(tool)}>生成{suggestion.title} <ArrowRight size={15} aria-hidden /></button>
      <button type="button" onClick={() => onDismiss()}>继续聊，稍后再说</button>
      <button type="button" onClick={() => onDismiss(true)}>本次对话不再提醒</button>
    </div>
    <small>选择后才会生成。已聊过的轮数不代表掌握程度。</small>
  </section>;
}
