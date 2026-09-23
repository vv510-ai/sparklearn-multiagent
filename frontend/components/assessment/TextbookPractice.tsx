"use client";

import MathText from "@/components/chat/MathText";

import { useState } from "react";
import { apiPost } from "@/lib/api";
import type { Assessment, PracticeProgress, PracticeResult } from "@/lib/assessment";
import ListeningAudio from "./ListeningAudio";

type PracticeState = {
  status: "active" | "scheduled" | "exhausted";
  question: { id: string; kp: string; stem: string; code?: string; audio_url?: string; options: string[] } | null;
  progress: PracticeProgress;
};
const dueText = (value: string) => new Date(value).toLocaleString("zh-CN", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });

export default function TextbookPractice({ assessment, kp, onUpdated, onActive }: {
  assessment: Assessment; kp: string; onUpdated: (a: Assessment) => void; onActive: (active: boolean) => void;
}) {
  const [state, setState] = useState<PracticeState | null>(null);
  const [result, setResult] = useState<PracticeResult | null>(null);
  const [choice, setChoice] = useState("");
  const [assisted, setAssisted] = useState(false);
  const [listened, setListened] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const progress = assessment.learning_progress?.[kp] || state?.progress;
  const begin = async () => {
    setBusy(true); setError("");
    try {
      const next = await apiPost<PracticeState>(`/assessment/${assessment.id}/practice`, { kp });
      setState(next); setResult(null); setChoice(""); setAssisted(false); setListened(false); onActive(next.status === "active");
    } catch (e) { setError(e instanceof Error ? e.message : "暂时无法读取练习，请重试。"); }
    finally { setBusy(false); }
  };
  const submit = async (answer: string | null) => {
    if (!state?.question) return;
    setBusy(true); setError("");
    try {
      const response = await apiPost<{ result: PracticeResult; assessment: Assessment }>(`/assessment/${assessment.id}/practice/answers`, {
        question_id: state.question.id, choice: answer, assisted,
      });
      setResult(response.result); onUpdated(response.assessment); onActive(false);
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败；可以重试，作答不会重复计入。"); }
    finally { setBusy(false); }
  };
  return <section className="textbook-practice" aria-label="教材新题练习" aria-busy={busy}>
    <h3>用新题检查能否独立完成</h3>
    <p>每轮 3 题，题目与起点测评不同。先合上资料作答，提交后查看解释；一轮结束后安排延迟复测。</p>
    {progress?.answered ? <p className="entry-note">已完成 {progress.answered} 道新题，其中独立作答 {progress.independent} 道、答对 {progress.correct} 道。{progress.next_due_at && `下次复测：${dueText(progress.next_due_at)}。`}</p> : null}
    {error && <p role="alert" className="entry-error">{error}</p>}
    {!state && <button type="button" className="intake-primary" disabled={busy} onClick={() => void begin()}>开始无提示新题</button>}
    {state?.question && <>
      <h4><MathText text={state.question.stem} /></h4>{state.question.code && <pre><code>{state.question.code}</code></pre>}
      {state.question.audio_url && <ListeningAudio key={state.question.id} src={state.question.audio_url} onListened={() => setListened(true)} />}
      <fieldset className="entry-options" disabled={busy || !!result}><legend>{state.question.code ? "选择程序输出" : "选择一个答案"}</legend>
        {state.question.options.map((option, i) => { const key = String.fromCharCode(65 + i); return <label key={key}>
          <input type="radio" name="textbook-answer" value={key} checked={choice === key} onChange={() => setChoice(key)} /><b>{key}</b><span><MathText text={option} /></span>
        </label>; })}
      </fieldset>
      {!result && <><label className="practice-assisted"><input type="checkbox" checked={assisted} onChange={e => setAssisted(e.target.checked)} disabled={busy} />作答时看了资料或得到提示</label>
        <div className="entry-actions"><button type="button" className="secondary-action" disabled={busy || (!!state.question.audio_url && !listened)} onClick={() => void submit(null)}>这道新题还不会</button>
          <button type="button" className="intake-primary" disabled={busy || !choice || (!!state.question.audio_url && !listened)} onClick={() => void submit(choice)}>提交新题答案</button></div></>}
    </>}
    {result && <div className="practice-feedback" role="status"><strong>{result.correct ? "这道题答对了" : "先核对这一步"} · 答案 {result.answer}</strong><p><MathText text={result.explain} /></p><p>{result.message}</p>
      {result.transcript && <details><summary>查看听力文字稿，复听核对</summary><p lang="en">{result.transcript}</p></details>}
      <ul>{result.citations.map(c => <li key={c.url}><a href={c.url} target="_blank" rel="noopener noreferrer">核对教材：{c.chapter} ↗</a></li>)}</ul>
      <button type="button" className="intake-primary" disabled={busy} onClick={() => void begin()}>{progress?.next_due_at ? "查看下次复测" : "继续下一道新题"}</button></div>}
    {state?.status === "scheduled" && <p role="status">本轮已完成。请在 {dueText(state.progress.next_due_at!)} 后回来，用另一组题检查是否还记得。</p>}
    {state?.status === "exhausted" && <p role="status">这个主题已完成全部 9 道新题。起点表现、练习和延迟复测记录已保留；这些有限题目不能代表整门课程都已掌握。</p>}
  </section>;
}
