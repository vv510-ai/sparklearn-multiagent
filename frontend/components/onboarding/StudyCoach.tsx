"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Sparkles, X } from "lucide-react";
import type { StudyStage } from "@/lib/learning-guidance";

export type CoachAction = "ask" | "sources" | "assessment" | "quiz" | "notes";

export default function StudyCoach({ stage, sourceCount, hasNotebook, storageKey, disabled, onAction }: {
  stage: StudyStage; sourceCount: number; hasNotebook: boolean; storageKey: string;
  disabled: boolean; onAction: (action: CoachAction) => void;
}) {
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    const sync = () => { try { setDismissed(localStorage.getItem(storageKey) === "hidden"); } catch { setDismissed(false); } };
    sync();
    window.addEventListener("learnloop:coach-preference", sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener("learnloop:coach-preference", sync); window.removeEventListener("storage", sync); };
  }, [storageKey]);
  const setHidden = (hidden: boolean) => {
    setDismissed(hidden);
    try { if (hidden) localStorage.setItem(storageKey, "hidden"); else localStorage.removeItem(storageKey); } catch {}
    window.dispatchEvent(new Event("learnloop:coach-preference"));
  };
  if (dismissed) return <button className="coach-restore" onClick={() => setHidden(false)}>显示下一步建议</button>;
  const suggestion = stage === "organize"
    ? { title: "换道题，看看能不能自己做", text: "讲解已经积累了一些。试着独立作答，再决定要补哪里。", label: "试一道练习", action: "quiz" as const, alternate: "notes" as const, alternateLabel: "先整理笔记" }
    : stage === "explore"
    ? { title: "这个地方，还有哪里没懂？", text: "换个例子、追问一个步骤，或者用自己的话说一遍。", label: "继续问小知", action: "ask" as const, alternate: "quiz" as const, alternateLabel: "我想试一题" }
    : sourceCount > 0
    ? { title: "资料准备好了，从一个问题开始", text: `已选 ${sourceCount} 项资料。告诉小知想先弄懂哪里，回答时会结合这些内容。`, label: "问问这份资料", action: "ask" as const, alternate: "assessment" as const, alternateLabel: "帮我找到起点" }
    : { title: hasNotebook ? "这次想弄懂什么？" : "先说一个你想解决的问题", text: "直接提问就能开始，也可以带上自己的讲义。", label: "开始提问", action: "ask" as const, alternate: "sources" as const, alternateLabel: "带上学习资料" };
  return <section className="study-coach" aria-label="小知的下一步建议">
    <div className="study-coach-top"><span><Sparkles size={14} />小知 · 陪你学</span><button type="button" aria-label="关闭下一步建议" onClick={() => setHidden(true)}><X size={15} /></button></div>
    <div key={`${stage}-${sourceCount > 0}`} className="study-coach-message" aria-live="polite"><h3>{suggestion.title}</h3><p>{suggestion.text}</p></div>
    <div className="study-coach-actions"><button type="button" disabled={disabled} onClick={() => onAction(suggestion.action)}>{suggestion.label}<ArrowRight size={14}/></button><button type="button" disabled={disabled} onClick={() => onAction(suggestion.alternate)}>{suggestion.alternateLabel}</button></div>
  </section>;
}
