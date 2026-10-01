"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Check, Clock3 } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { readStudyDraft, writeStudyDraft } from "@/lib/study-workspace";
import { readingDate, readingError, readingRequestId, type ReadingLibrary, type ReadingSession, type ReadingQuestion, type ReadingExercise } from "@/lib/reading";
import ReadingImport from "./ReadingImport";
import "./reading-training.css";

type Props = { notebookId: string; userId: string; onFocus: (active: boolean) => void; onChat: (prompt: string) => void;
  chapterDue: { id: string; title: string }[]; onChapter: (id: string) => void; onReviews: () => void };

function setReadingLink(notebook: string, item?: string) {
  const url = new URL(window.location.href); url.searchParams.set("notebook", notebook);
  if (item) url.searchParams.set("reading", item); else url.searchParams.delete("reading");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

export default function ReadingTraining({ notebookId, userId, onFocus, onChat, chapterDue, onChapter, onReviews }: Props) {
  const [library, setLibrary] = useState<ReadingLibrary | null>(null);
  const [active, setActive] = useState<ReadingSession | null>(null);
  const [importing, setImporting] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const alive = useRef(true); const inFlight = useRef(false);
  const base = `/notebooks/${notebookId}/reading`;
  const refresh = async () => { try { const result = await apiGet<ReadingLibrary>(base); if (alive.current) setLibrary(result); } catch (e) { if (alive.current) setError(readingError(e)); } };
  useEffect(() => {
    alive.current = true; void refresh();
    const link = new URLSearchParams(window.location.search);
    if (link.get("notebook") === notebookId && link.get("reading")) void open(link.get("reading")!);
    return () => { alive.current = false; };
    // Account and notebook changes remount this component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { onFocus(Boolean(active || importing)); return () => onFocus(false); }, [active?.id, importing, onFocus]);
  const open = async (id: string, sample = false) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const result = sample ? await apiPost<ReadingSession>(`${base}/examples/${id}`, {}) : await apiGet<ReadingSession>(`${base}/${id}`);
      if (alive.current) { setActive(result); setReadingLink(notebookId, result.id); }
    } catch (e) { if (alive.current) setError(readingError(e)); }
    finally { inFlight.current = false; if (alive.current) setBusy(false); }
  };
  const exit = () => { setActive(null); setImporting(false); setReadingLink(notebookId); void refresh(); };
  if (importing) return <div className="reading-hub"><ReadingImport notebookId={notebookId} userId={userId} onCancel={exit} onImported={data => { if (alive.current) { setImporting(false); setActive(data); setReadingLink(notebookId, data.id); } }} /></div>;
  if (active) return <div className="reading-hub"><ReadingPlayer key={active.id} initial={active} userId={userId} onExit={exit} onChat={onChat} /></div>;
  if (!library) return <section className="reading-hub reading-today"><p role="status">{error || "正在整理今日阅读任务…"}</p>{error && <button className="secondary-action" onClick={() => void refresh()}>重试阅读任务</button>}</section>;
  const candidate = library.items.find(i => i.phase !== "done" || (i.due_at && i.due_at <= library.server_time));
  const next = library.examples[0];
  const chapter = !candidate && chapterDue[0];
  const legacy = !candidate && !chapter && library.legacy_due > 0;
  return <section className="reading-hub" aria-label="今日阅读任务">
    <div className="reading-today">
      <div className="reading-heading"><span className="reading-eyebrow">今天 · 一次只做一件事</span><span className="reading-muted"><Clock3 size={14} />{library.due + chapterDue.length + library.legacy_due} 项到期</span></div>
      <h2>{candidate ? candidate.phase === "done" ? "先巩固上次的阅读" : "接着上次的练习" : chapter ? "先复习一节到期内容" : legacy ? "先复习到期错题" : next ? "开始一段阅读训练" : "今天的阅读已完成"}</h2>
      <p>{candidate?.title || (chapter && chapter.title) || (legacy ? `已有测验错题 ${library.legacy_due} 题` : next?.title) || "可以导入一篇新题，也可以查看已经保存的学习记录。"}</p>
      {(candidate?.demo || (!candidate && !chapter && !legacy && next)) && <p className="reading-source-badge">体验示例 · 非六级真题 · 难度未校准</p>}
      <div className="reading-toolbar">
        {candidate ? <button className="primary-action" disabled={busy} onClick={() => void open(candidate.id)}>{candidate.phase === "done" ? "打开到期复习" : "继续练习"}<ArrowRight size={16} /></button>
          : chapter ? <button className="primary-action" onClick={() => onChapter(chapter.id)}>打开待复习章节<ArrowRight size={16} /></button>
          : legacy ? <button className="primary-action" onClick={onReviews}>打开到期错题<ArrowRight size={16} /></button>
          : next ? <button className="primary-action" disabled={busy} onClick={() => void open(next.id, true)}>开始阅读体验<ArrowRight size={16} /></button> : null}
        <button className="secondary-action" disabled={busy} onClick={() => setImporting(true)}>导入自己的真题</button>
      </div>
      {!!(chapterDue.length || library.legacy_due) && <details className="reading-details"><summary>其他到期任务</summary>{chapterDue.map(u => <button className="reading-list-item" key={u.id} onClick={() => onChapter(u.id)}><span>章节复习 · {u.title}</span><ArrowRight size={15} /></button>)}{!!library.legacy_due && <button className="reading-list-item" onClick={onReviews}>已有测验错题 · {library.legacy_due} 题<ArrowRight size={15} /></button>}</details>}
      {error && <p role="alert" className="reading-error">{error}</p>}
    </div>
    <details className="reading-details reading-records"><summary>阅读记录与后续安排 · 已完成导入材料 {library.private_completed} 篇 / 体验示例 {library.demo_completed} 篇</summary>
      <p className="reading-muted">首次作答、订正和到期独立复习分别记录；练习表现不换算六级报道分。自备材料的答案由导入者提供。</p>
      {library.items.map(item => <button key={item.id} className="reading-list-item" disabled={busy} onClick={() => void open(item.id)}><span><strong>{item.title}</strong><small>{item.demo ? "体验示例（非真题）" : "自备材料"} · {item.first ? `首次 ${item.first.correct}/${item.first.total}${item.first.used_help ? "（借助提示）" : "（自述独立）"}` : "尚未提交"} · 到期独立复习 {item.reviews} 次</small><small>{item.phase !== "done" ? "上次尚未完成，继续即可" : `下次复习：${readingDate(item.due_at)}`}</small></span><ArrowRight size={16} /></button>)}
      {library.examples.map(sample => <button className="reading-list-item" key={sample.id} disabled={busy} onClick={() => void open(sample.id, true)}><span><strong>{sample.title}</strong><small>未练习的体验示例 · 非真题 · {sample.questions} 题</small></span><ArrowRight size={16} /></button>)}
    </details>
  </section>;
}

type Draft = { answers: Record<string, number>; uncertain: string[]; note: string; used_help: boolean; phase: string; version: string; baseRevision: number; elapsed: number; token: string };
const draftFor = (s: ReadingSession): Draft => ({ answers: s.phase === "answer" ? s.draft : s.exercise_answers, uncertain: s.uncertain,
  note: s.note, used_help: s.used_help || false, phase: s.phase, version: s.version, baseRevision: s.revision, elapsed: s.elapsed_seconds || 0, token: readingRequestId() });
const draftKey = (user: string, s: ReadingSession) => `learnloop:reading-draft:${user}:${s.notebook_id}:${s.id}:${s.phase}`;
function localDraft(user: string, session: ReadingSession) {
  return readStudyDraft<Draft>(draftKey(user, session), (x): x is Draft => {
    if (!x || typeof x !== "object") return false;
    const d = x as Draft;
    const questions = session.phase === "answer" ? session.material.questions : session.exercises || [];
    return d.version === session.version && d.phase === session.phase && typeof d.note === "string" && d.note.length <= 2000
      && Array.isArray(d.uncertain) && d.uncertain.every(id => session.material.questions.some(q => q.id === id))
      && !!d.answers && typeof d.answers === "object" && !Array.isArray(d.answers)
      && Object.entries(d.answers).every(([id, value]) => questions.some(q => q.id === id && Number.isInteger(value) && value >= 0 && value < q.options.length))
      && typeof d.token === "string" && Number.isInteger(d.baseRevision) && typeof d.used_help === "boolean" && Number.isFinite(d.elapsed) && d.elapsed >= 0;
  });
}

function ReadingPlayer({ initial, userId, onExit, onChat }: { initial: ReadingSession; userId: string; onExit: () => void; onChat: (prompt: string) => void }) {
  const [session, setSession] = useState(initial);
  const [draft, setDraft] = useState<Draft>(() => localDraft(userId, initial) || draftFor(initial));
  const [dirty, setDirty] = useState(() => Boolean(localDraft(userId, initial)));
  const [blocked, setBlocked] = useState(() => { const d = localDraft(userId, initial); return Boolean(d && d.baseRevision !== initial.revision); });
  const [busy, setBusy] = useState(false); const [error, setError] = useState(() => { const d = localDraft(userId, initial); return d && d.baseRevision !== initial.revision ? "服务器已有新记录，本机草稿已保留。请核对后选择保留草稿或使用服务器版本。" : ""; });
  const [notice, setNotice] = useState(""); const [index, setIndex] = useState(0); const [mobilePane, setMobilePane] = useState("question");
  const busyRef = useRef(false); const alive = useRef(true); const changes = useRef(0); const draftRef = useRef(draft); draftRef.current = draft;
  const started = useRef(Date.now()); const heading = useRef<HTMLHeadingElement>(null);
  const receipt = useRef<{ key: string; id: string; elapsed: number } | null>(null);
  const url = `/notebooks/${session.notebook_id}/reading/${session.id}`;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { setIndex(0); setMobilePane("question"); requestAnimationFrame(() => heading.current?.focus()); }, [session.phase]);
  const edit = (value: Partial<Draft>) => {
    const next = { ...draftRef.current, ...value, token: readingRequestId(), baseRevision: session.revision, elapsed: Math.min(86400, draftRef.current.elapsed + (Date.now() - started.current) / 1000) };
    started.current = Date.now(); changes.current++; draftRef.current = next; setDraft(next); setDirty(true); setNotice("");
    writeStudyDraft(draftKey(userId, session), next);
  };
  const action = async (kind: string) => {
    if (busyRef.current) return false;
    busyRef.current = true; setBusy(true); setError("");
    const generation = changes.current; const value = draftRef.current;
    const body = { revision: session.revision, version: session.version, action: kind,
      answers: ["answer", "drill", "recall"].includes(session.phase) ? value.answers : {},
      uncertain: value.uncertain, note: value.note, used_help: value.used_help,
      elapsed_seconds: Math.min(86400, Math.round(value.elapsed + (Date.now() - started.current) / 1000)) };
    const key = JSON.stringify({ ...body, elapsed_seconds: 0 });
    if (receipt.current?.key !== key) receipt.current = { key, id: readingRequestId(), elapsed: body.elapsed_seconds };
    body.elapsed_seconds = receipt.current.elapsed;
    try {
      const next = await apiPost<ReadingSession>(url, { ...body, request_id: receipt.current.id });
      if (!alive.current) return false;
      setSession(next); setBlocked(false);
      if (changes.current === generation || next.phase !== session.phase) {
        const restored = { ...draftFor(next), elapsed: next.elapsed_seconds || value.elapsed };
        draftRef.current = restored; setDraft(restored); setDirty(false);
        try { if (localDraft(userId, session)?.token === value.token) localStorage.removeItem(draftKey(userId, session)); } catch { /* Never delete another tab's newer draft. */ }
      } else {
        const pending = { ...draftRef.current, baseRevision: next.revision }; draftRef.current = pending; setDraft(pending);
        writeStudyDraft(draftKey(userId, next), pending);
      }
      started.current = Date.now(); setNotice("已保存到账号"); receipt.current = null; return true;
    } catch (e) { if (alive.current) { setError(readingError(e)); setBlocked(true); } return false; }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  };
  useEffect(() => {
    if (!dirty || blocked || busy || !["answer", "feedback", "drill", "recall"].includes(session.phase)) return;
    const timer = setTimeout(() => { void action(session.phase === "recall" ? "review_draft" : "draft"); }, 850);
    return () => clearTimeout(timer);
    // Snapshot changes re-schedule one serialized save; the server rejects stale revisions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, blocked, busy, draft, session.revision]);
  const reload = async (keep: boolean) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true);
    try {
      const latest = await apiGet<ReadingSession>(url); if (!alive.current) return;
      setSession(latest); receipt.current = null;
      if (!keep || latest.phase !== session.phase) { const next = draftFor(latest); draftRef.current = next; setDraft(next); setDirty(false); if (!keep) try { if (localDraft(userId, session)?.token === draft.token) localStorage.removeItem(draftKey(userId, session)); } catch {} }
      else { const next = { ...draftRef.current, baseRevision: latest.revision }; draftRef.current = next; setDraft(next); writeStudyDraft(draftKey(userId, latest), next); }
      setBlocked(keep && latest.phase === session.phase); setError("");
      setNotice(keep && latest.phase === session.phase ? "已读取服务器进度，当前草稿保留。核对后点击“保存当前草稿”。" : "已恢复服务器记录。");
    } catch (e) { if (alive.current) setError(readingError(e)); }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  };
  const leave = async () => { if (dirty && !(await action(session.phase === "recall" ? "review_draft" : "draft"))) return; onExit(); };
  const questions = session.material.questions;
  const exercises = session.exercises || [];
  const current = questions[Math.min(index, questions.length - 1)];
  const phase = session.phase;
  const isExercise = ["drill", "drill_feedback", "recall"].includes(phase);
  const selected = isExercise ? exercises[Math.min(index, exercises.length - 1)] : current;
  const feedback = session.feedback?.find(q => q.id === current.id);
  const answerSet = isExercise ? exercises : questions;
  const complete = answerSet.every(q => draft.answers[q.id] !== undefined);
  const stageLabel = { answer: "独立作答", feedback: "对照证据", drill: "短练习", drill_feedback: "练习反馈", done: "已完成", recall: "隔时复习" }[phase];
  const sourceLabel = session.demo ? "体验示例 · 非真题 · 虚构情境，难度未校准" : `${session.source_type === "past_paper" ? "自备真题（来源待核验）" : "自备阅读材料"} · 答案与解析由导入者提供`;
  const ask = () => onChat(`请根据以下原文和已提交答案帮助我订正，不要将推测错因说成事实。材料来源：${session.material.source}。\n原文：${session.material.paragraphs.join("\n\n")}\n题目：${current.prompt}\n选项：${current.options.map((o, i) => `${String.fromCharCode(65 + i)}. ${o}`).join("\n")}\n我的首次答案：${String.fromCharCode(65 + (session.first?.answers[current.id] ?? 0))}。\n材料提供的答案：${String.fromCharCode(65 + (feedback?.answer ?? 0))}。\n依据：${feedback?.evidence?.quote || ""}。\n我记录的问题：${draft.note || "尚未说明作答过程，请先问我当时怎么判断的。"}`);
  return <section className="reading-player" aria-label="阅读训练工作区">
    <header className="reading-player-top"><button className="reading-back" disabled={busy} onClick={() => void leave()}><ArrowLeft size={17} />今日任务</button><span>{stageLabel}</span><span className="reading-save-status" role="status">{busy ? "保存中…" : error || blocked ? "草稿待核对" : dirty ? "本机草稿待同步" : notice || "已恢复账号记录"}</span></header>
    <div className="reading-title"><p className="reading-source-badge">{sourceLabel}</p><h1 ref={heading} tabIndex={-1}>{session.material.title}</h1><details><summary>材料出处</summary><p>{session.material.source}</p>{session.material.source_url && <a href={session.material.source_url} target="_blank" rel="noopener noreferrer">打开来源 ↗</a>}</details></div>
    {(error || blocked) && <div className="reading-error" role="alert"><p>{error || notice}</p><p>服务器版本已作答 {Object.keys(phase === "answer" ? session.draft : session.exercise_answers).length} 题，本机草稿已作答 {Object.keys(draft.answers).length} 题。</p><div className="reading-toolbar"><button disabled={busy} onClick={() => void reload(true)}>重新加载，保留草稿</button><button disabled={busy} onClick={() => void reload(false)}>使用服务器版本</button><button disabled={busy} onClick={() => void action(phase === "recall" ? "review_draft" : "draft")}>保存当前草稿</button></div></div>}
    {phase === "done" ? <div className="reading-completion">
      <Check size={30} /><h2>{session.last_review ? "这次复习已记录" : "阅读与订正已完成"}</h2>
      <p>首次作答 <strong>{session.first?.correct} / {session.first?.total}</strong>，{session.first?.used_help ? "使用过提示或答案" : "自述独立完成"}。后续结果不会覆盖首次答案。</p>
      {session.last_review && <><p>本次复习 {session.last_review.correct} / {session.last_review.total} · {session.last_review.early ? "提前练习，原复习日期保留" : session.last_review.used_help ? "借助提示，原复习日期保留" : "到期独立作答"}。</p><details className="reading-details"><summary>查看本次复习反馈</summary>{session.last_review.feedback?.map(q => <div key={q.id}><h3>{q.prompt}</h3><p>你的答案：{String.fromCharCode(65 + session.last_review!.answers[q.id])}；参考答案：{String.fromCharCode(65 + q.answer!)}。</p><p>{q.explanation}</p></div>)}</details></>}
      <div className="reading-next-review"><Clock3 size={20} /><div><strong>下次复习：{readingDate(session.review?.due_at)}</strong><p>再次进入这门课即可看到待办。当前为站内提醒，关闭网站后不会发送通知。</p></div></div>
      <div className="reading-toolbar"><button className="primary-action" onClick={onExit}>回到今日任务<ArrowRight size={16} /></button><button className="secondary-action" disabled={busy} onClick={() => void action("start_review")}>{session.review?.due_at && new Date(session.review.due_at).getTime() <= Date.now() ? "开始到期复习" : "提前练习一次"}</button></div>
      <details className="reading-details"><summary>首次作答与订正记录</summary>{session.feedback?.map(q => <div key={q.id}><h3>{q.prompt}</h3><p>首次选择 {String.fromCharCode(65 + session.first!.answers[q.id])} · 参考答案 {String.fromCharCode(65 + q.answer!)}</p><blockquote>{q.evidence?.quote}</blockquote><p>{q.explanation}</p></div>)}{session.note && <p>我的订正：{session.note}</p>}</details>
      {!!session.history.length && <details className="reading-details"><summary>全部复习记录 · {session.history.length} 次</summary>{session.history.map((r, n) => <p key={n}>{readingDate(r.submitted_at)} · {r.correct}/{r.total} · {r.early ? "提前练习" : r.used_help ? "借助提示" : "到期独立作答"} · {r.kind === "original" ? "原题重做" : "短题复习"}</p>)}</details>}
      <p className="reading-muted">完成记录和原题复习不等于新题能力；新材料上的首次表现会另行保留。</p>
    </div> : <>
      {phase === "recall" && <p className="reading-callout">{session.active_review?.early ? "这是提前练习，不推进原复习计划。" : "先不看旧解析，独立完成这次复习。"}原题重做与新题表现分开记录。</p>}
      <div className="reading-mobile-switch" role="group" aria-label="阅读区域切换"><button aria-pressed={mobilePane === "article"} onClick={() => setMobilePane("article")}><BookOpen size={16} />{isExercise ? "练习材料" : "文章原文"}</button><button aria-pressed={mobilePane === "question"} onClick={() => setMobilePane("question")}>题目与作答</button></div>
      <div className="reading-columns" data-mobile-pane={mobilePane}>
        <article className="reading-passage" aria-label={isExercise ? "练习材料" : "文章原文"}>
          <h2>{isExercise ? selected && "kind" in selected && selected.kind === "original" ? "原题重做" : "换个情境，再试一次" : session.material.englishTitle || "文章原文"}</h2>
          {isExercise ? <p lang="en" style={{ whiteSpace: "pre-line" }}>{(selected as ReadingExercise)?.context}</p> : session.material.paragraphs.map((p, i) => <p lang="en" key={i} data-evidence={phase === "feedback" && feedback?.evidence?.paragraph === i}><span className="reading-paragraph-number">{i + 1}</span>{p}</p>)}
        </article>
        <section className="reading-question-pane" aria-label="题目与作答">
          <div className="reading-question-nav" aria-label="选择题目">{answerSet.map((q, n) => <button key={q.id} aria-pressed={index === n} aria-label={`第 ${n + 1} 题${draft.answers[q.id] !== undefined ? "，已作答" : ""}`} onClick={() => setIndex(n)}>{n + 1}{(phase === "answer" || phase === "drill" || phase === "recall") && draft.answers[q.id] !== undefined && <span aria-hidden="true">·</span>}</button>)}</div>
          {selected && <><p className="reading-eyebrow">第 {index + 1} / {answerSet.length} 题{isExercise && "kind" in selected && selected.kind === "original" ? " · 原题订正 / 复习" : ""}</p><h2 className="reading-question-stem" lang="en">{selected.prompt}</h2>
            <fieldset className="reading-options" disabled={busy || phase === "feedback" || phase === "drill_feedback"}><legend className="sr-only">选择答案</legend>{selected.options.map((option, n) => <label key={n} data-selected={(phase === "feedback" ? session.first?.answers[selected.id] : draft.answers[selected.id]) === n}><input type="radio" name={`answer-${session.id}-${phase}-${selected.id}`} value={n} checked={(phase === "feedback" ? session.first?.answers[selected.id] : draft.answers[selected.id]) === n} onChange={() => edit({ answers: { ...draft.answers, [selected.id]: n } })} /><span className="reading-option-letter">{String.fromCharCode(65 + n)}</span><span lang="en">{option}</span></label>)}</fieldset>
            {phase === "answer" && <label className="reading-checkbox"><input type="checkbox" checked={draft.uncertain.includes(selected.id)} disabled={busy} onChange={e => edit({ uncertain: e.target.checked ? [...draft.uncertain, selected.id] : draft.uncertain.filter(id => id !== selected.id) })} />这题我不太确定，之后再复习</label>}
            {phase === "feedback" && feedback && <div className="reading-feedback"><strong>{session.first?.answers[current.id] === feedback.answer ? "本题答对" : "需要订正"} · 参考答案 {String.fromCharCode(65 + feedback.answer!)}</strong><p className="reading-muted">{session.demo ? "预置示例解析" : "导入者提供的解析"}；错因需要结合你的作答过程确认。</p><blockquote lang="en">{feedback.evidence?.quote}</blockquote><p>{feedback.explanation}</p>{!!feedback.optionFeedback?.length && <details><summary>逐项看看选项</summary>{feedback.optionFeedback.map((f, n) => <p key={n}><strong>{String.fromCharCode(65 + n)}.</strong> {f}</p>)}</details>}{feedback.takeaway && <p className="reading-takeaway">{feedback.takeaway}</p>}<button className="secondary-action" disabled={busy} onClick={ask}>带着这道题问小知</button></div>}
            {phase === "drill_feedback" && <div className="reading-feedback"><strong>{draft.answers[selected.id] === selected.answer ? "这次答对了" : "再对照一次依据"} · 参考答案 {String.fromCharCode(65 + selected.answer!)}</strong><p>{selected.explanation}</p><p className="reading-muted">这是刚看过解析后的练习，不计为首次成绩或隔时掌握。</p></div>}
          </>}
          <div className="reading-question-bottom"><button className="secondary-action" disabled={index === 0} onClick={() => setIndex(n => n - 1)}>上一题</button><button className="secondary-action" disabled={index + 1 >= answerSet.length} onClick={() => setIndex(n => n + 1)}>下一题</button></div>
        </section>
      </div>
      {phase === "feedback" && <label className="reading-reflection">记下一个容易忽略的地方（选填）<textarea rows={2} maxLength={2000} value={draft.note} disabled={busy} onChange={e => edit({ note: e.target.value })} placeholder="例如：选项中的 all 比原文说得更绝对。" /></label>}
      <footer className="reading-actions">
        {(phase === "answer" || phase === "recall") && <label className="reading-checkbox"><input type="checkbox" disabled={busy || session.used_help} checked={draft.used_help} onChange={e => edit({ used_help: e.target.checked })} />作答时查看过提示或答案</label>}
        <span className="reading-muted">{phase === "answer" || phase === "drill" || phase === "recall" ? `已答 ${Object.keys(draft.answers).length} / ${answerSet.length} 题` : "先理解依据，再用练习检查"}</span>
        <button className="primary-action" disabled={busy || blocked || ((phase === "answer" || phase === "drill" || phase === "recall") && !complete)} onClick={() => void action({ answer: "submit", feedback: "reflect", drill: "drill", drill_feedback: "finish", recall: "review_submit" }[phase] || "finish")}>{({ answer: "提交首次答案", feedback: "做一个短练习", drill: "提交短练习", drill_feedback: "完成订正，安排复习", recall: "提交复习答案" })[phase]}<ArrowRight size={16} /></button>
      </footer>
    </>}
  </section>;
}
