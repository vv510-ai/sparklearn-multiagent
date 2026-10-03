"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { readingError } from "@/lib/reading";
import type { WordLesson as Lesson } from "@/lib/cet6";

export default function WordLesson({ notebookId, wordId, senseId }: { notebookId: string; wordId: string; senseId: string }) {
  const [lesson, setLesson] = useState<Lesson | null>(null), [error, setError] = useState(""), [retry, setRetry] = useState(0);
  const [choice, setChoice] = useState(""), [checked, setChecked] = useState(false), [busy, setBusy] = useState(true);
  const request = useRef(0);
  useEffect(() => {
    const ticket = ++request.current;
    setBusy(true); setError(""); setLesson(null); setChoice(""); setChecked(false);
    const url = `/notebooks/${notebookId}/cet6/words/${wordId}/lesson?sense_id=${encodeURIComponent(senseId)}`;
    void (async () => {
      const cached = await apiGet<Lesson | { status: "missing" }>(url);
      if (ticket !== request.current) return;
      const result = cached.status === "ready" ? cached : await apiPost<Lesson>(url, {});
      if (ticket === request.current) setLesson(result);
    })().catch(e => { if (ticket === request.current) setError(readingError(e)); })
      .finally(() => { if (ticket === request.current) setBusy(false); });
    return () => { request.current++; };
  }, [notebookId, wordId, senseId, retry]);
  return <section className="cet6-word-lesson" aria-label="单词精讲">
    <div className="cet6-section-heading"><h3>理解与运用</h3>{lesson && <span className="cet6-lesson-label">{lesson.origin === "curated" ? "词典依据 · 本站讲解" : "AI讲解 · 待校核"}</span>}</div>
    {busy && <p role="status">正在准备本次义项的讲解…首次生成稍需等待，完成后会保存。</p>}
    {error && <div role="alert" className="cet6-error"><p>{error}</p><button className="secondary-action" onClick={() => setRetry(n => n + 1)}>重试精讲</button></div>}
    {lesson && <>
      <h4>{lesson.focus}</h4><p>{lesson.explanation}</p>
      <div className="cet6-lesson-usage"><h4>常见搭配与用法</h4><ul>{lesson.usage.map((u, i) => <li key={i}>{u}</li>)}</ul></div>
      <figure className="cet6-lesson-example"><figcaption>自编例句 · 非真题</figcaption><blockquote lang="en">{lesson.example.text}</blockquote><p>{lesson.example.translation}</p><p className="cet6-muted">{lesson.example.note}</p></figure>
      <h4>容易混淆的地方</h4><p>{lesson.contrast}</p>
      <details className="cet6-source"><summary>记忆线索 · AI助记，非真实词源</summary><p>{lesson.memory}</p></details>
      {!!lesson.exam_occurrences.length && <details className="cet6-source"><summary>查看考试样卷中的位置</summary>{lesson.exam_occurrences.map((e, i) => <p key={i}><a href={e.url} target="_blank" rel="noreferrer">{e.label}</a> · {e.note}</p>)}</details>}
      <fieldset className="cet6-lesson-check"><legend>试着用一次 · 自编应用题</legend><p>{lesson.check.stem}</p>{lesson.check.options.map((option, i) => {
        const key = "ABCD"[i]; return <label key={key} className="cet6-check"><input type="radio" name={`lesson-${wordId}-${senseId}`} value={key} checked={choice === key} disabled={checked} onChange={() => setChoice(key)} /><span>{key}. {option}</span></label>;
      })}<button className="secondary-action" disabled={!choice || checked} onClick={() => setChecked(true)}>核对应用题</button>
        {checked && <div role="status" className="cet6-feedback"><strong>{choice === lesson.check.answer ? "这次选对了" : `参考答案：${lesson.check.answer}`}</strong><p>{lesson.check.explanation}</p><p className="cet6-muted">这道练习用于理解用法，不改变翻面前的回忆记录。</p></div>}
      </fieldset>
      <details className="cet6-source"><summary>讲解依据与内容来源</summary><p>{lesson.source_note}</p>{lesson.sources.map(source => <p key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> · {source.supports}{source.checked_on && `（核对于${source.checked_on}）`}</p>)}<p>本词尚无已核验的历年实考例句；上面的练习不标注考试年份或考频。</p></details>
    </>}
  </section>;
}
