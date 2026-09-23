/** @jsxImportSource react */
"use client";

import MathText from "@/components/chat/MathText";

import { useState } from "react";
import type { Assessment } from "@/lib/assessment";

type Report = NonNullable<Assessment["report"]>;

export default function AssessmentReview({ report, onLearn }: { report: Report; onLearn: (prompt: string) => void }) {
  const [index, setIndex] = useState(0);
  const item = report.explanations[Math.min(index, report.explanations.length - 1)];
  if (!item) return null;
  const status = item.status === "skipped" ? "当时跳过 · 不计错" : item.status === "dont_know" ? "当时选择还不会" : item.correct ? "本题答对" : "一起看看原因";
  return <section className="assessment-review" aria-label="已提交答案复盘">
    <h2 className="entry-section-title">已提交的题目 · 答案与解析</h2>
    <p className="entry-note">这是复盘区，不需要再答一次。下面可以查看你的选择、参考答案和原因；要继续练习，请回到学习任务使用新题。</p>
    <div className="review-navigation">
      <button className="secondary-action" disabled={index === 0} onClick={() => setIndex(i => i - 1)}>上一题解析</button>
      <label>查看第 <select aria-label="选择复盘题目" value={index} onChange={e => setIndex(Number(e.target.value))}>{report.explanations.map((q, i) => <option key={q.id} value={i}>{i + 1}</option>)}</select> / {report.explanations.length} 题</label>
      <button className="secondary-action" disabled={index >= report.explanations.length - 1} onClick={() => setIndex(i => i + 1)}>下一题解析</button>
    </div>
    <article className="entry-question-card" key={item.id}>
      <p className="entry-eyebrow">{item.topic || report.skills.find(s => s.kp === item.kp)?.name} · {status}</p>
      <p className="question-instruction">这是已经提交的题目。先看你当时的选择，再对照下面的解析。</p>
      <h3 className="assessment-stem"><MathText text={item.stem.replace(/\s+(?=\[[A-D]\])/g, "\n\n")} /></h3>
      {item.audio_url && <audio controls preload="none" src={item.audio_url} aria-label="复听这道题的音频" />}
      {!!item.options?.length && <ul className="review-options">{item.options.map((option, i) => <li key={i}>{String.fromCharCode(65 + i)}. <MathText text={option} /></li>)}</ul>}
      <p><strong>你当时的回答：</strong><MathText text={item.learner_answer || (item.status === "skipped" ? "暂时跳过" : item.status === "dont_know" ? "这题还不会" : "旧记录未保存选择详情")} /></p>
      <p><strong>参考答案：</strong><MathText text={item.answer} /></p>
      <p className="review-explanation"><strong>为什么：</strong><MathText text={item.explain} /></p>
      <button className="secondary-action" onClick={() => onLearn(`请帮我理解这次已提交的${item.topic || "课程"}作答。先用中文解释要求，再解释原因，用一个简单例子说明，最后等我提问。\n原文：${item.stem}\n选项：${(item.options || []).map((o, i) => `${String.fromCharCode(65 + i)}. ${o}`).join("；")}\n我的回答：${item.learner_answer || status}\n参考答案：${item.answer}\n解析：${item.explain}`)}>让小知讲解这一题</button>
    </article>
  </section>;
}
