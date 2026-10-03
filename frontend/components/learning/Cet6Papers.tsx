"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { cet6Route } from "@/lib/cet6";
import { readingDate, readingError, readingRequestId } from "@/lib/reading";
import ReadingVocabulary from "./ReadingVocabulary";

type Summary = { id: string; title: string; source_type: string; coverage: string; audio_status: string; checked_on: string;
  progress: null | { phase: string; answered: number } };
type Question = { number: number; section: string; page: number; evidence_page: number; options: string[]; answer?: string; explanation?: string };
type Section = { id: string; title: string; page: number; note: string };
type Paper = Summary & { source_url: string; source_note: string; answer_page: number; sections: Section[]; questions: Question[] };
type Draft = { answers: Record<string, string>; writing: string; translation: string; reflection: string; used_help: boolean };
type Saved = Draft & { paper: Paper; revision: number; phase: "answer" | "feedback"; due_at?: string;
  first?: { correct: number; answered: number; total: number; submitted_at: string; used_help: boolean };
  history: { first: { correct: number; answered: number; submitted_at: string } }[] };
type LocalDraft = Draft & { revision: number; token: string };
const draftOf = (s: Draft): Draft => ({ answers: s.answers, writing: s.writing, translation: s.translation, reflection: s.reflection, used_help: s.used_help });
function readLocal(key: string): LocalDraft | null {
  try { const value = JSON.parse(localStorage.getItem(key) || "null");
    return value && typeof value.token === "string" && Number.isInteger(value.revision) && typeof value.used_help === "boolean"
      && ["writing", "translation", "reflection"].every(k => typeof value[k] === "string" && value[k].length <= 10000)
      && value.answers && typeof value.answers === "object" && !Array.isArray(value.answers)
      && Object.entries(value.answers).every(([k, v]) => /^([2-4][0-9]|5[0-5])$/.test(k) && Number(k) >= 26 && typeof v === "string" && /^[A-O]$/.test(v)) ? value : null;
  } catch { return null; }
}
function clearLocal(key: string, token: string) {
  try { if (readLocal(key)?.token === token) localStorage.removeItem(key); } catch { /* Optional local storage. */ }
}

export default function Cet6Papers({ notebookId, initialPaper = "" }: { notebookId: string; initialPaper?: string }) {
  const [items, setItems] = useState<Summary[]>([]), [selected, setSelected] = useState(initialPaper), [error, setError] = useState(""), [retry, setRetry] = useState(0);
  useEffect(() => { let active = true; void apiGet<{ items: Summary[] }>(`/notebooks/${notebookId}/cet6/papers`).then(r => { if (active) { setItems(r.items); setError(""); } }).catch(e => { if (active) setError(readingError(e)); }); return () => { active = false; }; }, [notebookId, retry, selected]);
  const open = (id: string) => { setSelected(id); cet6Route(notebookId, "papers", id); };
  if (selected) return <PaperWorkspace key={selected} notebookId={notebookId} paperId={selected} onExit={() => open("")} />;
  return <section className="cet6-papers" aria-label="六级真题与模拟"><h2>真题与模拟</h2><p>先看来源，再练具体题型。打开原卷，在同一页保留作答和订正。</p>
    {error && <p role="alert" className="cet6-error">{error}<button onClick={() => setRetry(n => n + 1)}>重试试卷列表</button></p>}
    {items.map(p => <article key={p.id} className="cet6-paper-card"><span className="cet6-lesson-label">{p.source_type}</span><h3>{p.title}</h3><p>{p.coverage}</p><p className="cet6-muted">{p.audio_status} · 核验于 {p.checked_on}</p><button className="primary-action" onClick={() => open(p.id)}>{p.progress ? "继续原卷与答题" : "打开原卷并作答"}</button>{p.progress && <p className="cet6-muted">已保存 {p.progress.answered}/30 道阅读题 · {p.progress.phase === "feedback" ? "已提交，可订正或重练" : "尚未提交"}</p>}</article>)}
    <ExternalSources />
  </section>;
}

function PaperWorkspace({ notebookId, paperId, onExit }: { notebookId: string; paperId: string; onExit: () => void }) {
  const [state, setState] = useState<Saved | null>(null), [draft, setDraft] = useState<Draft | null>(null);
  const [section, setSection] = useState("cloze"), [pageNumber, setPageNumber] = useState(176), [wordQuestion, setWordQuestion] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [dirty, setDirty] = useState(false), [retry, setRetry] = useState(0);
  const [conflict, setConflict] = useState<LocalDraft | null>(null), [onlyWrong, setOnlyWrong] = useState(false);
  const alive = useRef(true), flight = useRef(false), receipt = useRef<{ key: string; id: string } | null>(null);
  const localToken = useRef("");
  const initialQuestion = useRef(typeof window === "undefined" ? 0 : Number(new URLSearchParams(window.location.search).get("cet6_paper_question")));
  const url = `/notebooks/${notebookId}/cet6/papers/${paperId}`, storageKey = `cet6-paper-draft:${notebookId}:${paperId}`;
  useEffect(() => { let active = true; alive.current = true;
    void apiGet<Saved>(url).then(s => { if (!active) return; setState(s); setDraft(draftOf(s)); setDirty(false); setError("");
      const q = s.paper.questions.find(q => q.number === initialQuestion.current);
      if (q) { setSection(q.section); setPageNumber(q.page); requestAnimationFrame(() => document.getElementById(`paper-q-${q.number}`)?.focus()); initialQuestion.current = 0; }
      setConflict(null);
      try { const local = readLocal(storageKey);
        if (local && local.revision === s.revision) { localToken.current = local.token; setDraft(draftOf(local)); setDirty(true); setNotice("已恢复本浏览器中尚未保存的输入。"); }
        else if (local) setConflict(local);
      } catch { /* Unavailable browser storage does not block account saves. */ }
    }).catch(e => { if (active) setError(readingError(e)); });
    return () => { active = false; alive.current = false; };
  }, [url, storageKey, retry]);
  const edit = (patch: Partial<Draft>) => {
    if (!draft || !state || flight.current) return;
    const next = { ...draft, ...patch }; setDraft(next); setDirty(true); setNotice("");
    localToken.current = readingRequestId();
    try { localStorage.setItem(storageKey, JSON.stringify({ ...next, revision: state.revision, token: localToken.current })); }
    catch { setNotice("浏览器未能暂存输入，请及时保存到账号。"); }
  };
  const save = async (action: "save" | "submit" | "restart") => {
    if (!state || !draft || flight.current) return;
    flight.current = true;
    setBusy(true); setError("");
    const body = { ...draft, revision: state.revision, action }, key = JSON.stringify(body);
    const submittedToken = localToken.current;
    if (receipt.current?.key !== key) receipt.current = { key, id: readingRequestId() };
    try { const saved = await apiPost<Saved>(url, { ...body, request_id: receipt.current.id });
      if (alive.current) { setState(saved); setDraft(draftOf(saved)); setDirty(false); setConflict(null); setOnlyWrong(false); setNotice(action === "submit" ? "首次答案已保存，可核对依据并记录错因。" : action === "restart" ? "已开始新一轮，上一轮记录保留。" : "已保存到账号");
        receipt.current = null;
        clearLocal(storageKey, submittedToken);
      }
    } catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  if (!state || !draft) return <section><button className="cet6-back" onClick={onExit}>返回试卷列表</button>{error ? <p role="alert">{error}<button onClick={() => setRetry(n => n + 1)}>重试原卷</button></p> : <p role="status">正在读取原卷与学习记录…</p>}</section>;
  const paper = state.paper, feedback = state.phase === "feedback";
  const selected = paper.sections.find(s => s.id === section)!;
  const jump = (s: Section) => { setSection(s.id); setPageNumber(s.page); };
  const questions = paper.questions.filter(q => q.section === section && (!onlyWrong || !feedback || draft.answers[q.number] !== q.answer));
  return <section className="cet6-paper-workspace" aria-label="官方样卷训练"><button className="cet6-back" disabled={busy} onClick={onExit}>← 返回试卷列表</button>
    <h2>{paper.title}</h2><p className="cet6-muted">{paper.source_note}</p>
    <p className="cet6-notice">{paper.audio_status}。当前开放阅读答题、写作与翻译草稿；听力题面可阅读，尚未开放原音训练。</p>
    <nav className="cet6-tabs" aria-label="原卷题型">{paper.sections.map(s => <button key={s.id} aria-pressed={section === s.id} onClick={() => jump(s)}>{s.title}</button>)}</nav>
    <div className="cet6-paper-layout"><div className="cet6-original"><div className="cet6-original-toolbar"><span>原卷 · PDF 第 {pageNumber} 页</span><a href={`${paper.source_url}#page=${pageNumber}`} target="_blank" rel="noreferrer">放大原卷 ↗</a></div>
      <iframe key={pageNumber} src={`${paper.source_url}#page=${pageNumber}&view=FitH`} title="教育考试院官方六级样卷原文" referrerPolicy="no-referrer" />
      <p className="cet6-muted">{selected.note} 若浏览器未显示 PDF，可点击“放大原卷”。页码按 PDF 物理页计。原卷包含答案与听力文本，本练习不属于封闭模考。</p>
    </div><div className="cet6-answer-sheet"><h3>{selected.title}</h3>
      {conflict && <section className="cet6-error" aria-label="原卷草稿冲突"><p>另一页面已更新记录。本浏览器仍有未保存输入，请先选择。</p><details><summary>查看保留的输入</summary><pre>{JSON.stringify(draftOf(conflict), null, 2)}</pre></details><button disabled={busy} className="secondary-action" onClick={() => { setConflict(null); setDirty(false); clearLocal(storageKey, conflict.token) }}>使用账号记录</button><button disabled={busy} className="secondary-action" onClick={() => { edit({ ...draftOf(conflict), answers: feedback ? state.answers : conflict.answers }); setConflict(null); }}>保留本页输入继续编辑</button></section>}
      {section === "writing" || section === "translation" ? <><p className="cet6-muted">按左侧原任务作答，点击保存保留草稿。参考文本需自行核对，系统不自动判为满分。</p><label className="cet6-field">{section === "writing" ? "样卷作文草稿" : "样卷翻译草稿"}<textarea rows={14} maxLength={10000} value={draft[section]} disabled={busy || !!conflict} onChange={e => edit({ [section]: e.target.value })} /></label>
        <button className="secondary-action" disabled={busy || !!conflict} onClick={() => { setPageNumber(section === "writing" ? 205 : 191); edit({ used_help: true }); }}>{section === "writing" ? "查看官方评分样卷（含不同分档）" : "查看官方参考译文"}</button><p className="cet6-muted">写作评分样卷有高低分档，请结合评分理由阅读，不能把所有文本都当作范文。</p></> : section === "listening" ? <p>完整听力题面在 PDF 第172–175页，文字稿在184–190页。原音尚待核验，暂不提供替代朗读或听力计分。</p> : <>
        <p className="cet6-muted">阅读共30题，已选 {Object.keys(draft.answers).length} 题。先独立完成，再提交核对。</p>
        {feedback && <label className="cet6-check"><input type="checkbox" checked={onlyWrong} onChange={e => setOnlyWrong(e.target.checked)} />只看错题与未答题</label>}
        {questions.map(q => <article key={q.number} className="cet6-paper-question"><div><label htmlFor={`paper-q-${q.number}`}>第 {q.number} 题</label><button className="cet6-link-button" onClick={() => setPageNumber(q.page)}>定位原题</button></div><select id={`paper-q-${q.number}`} aria-label={`第${q.number}题答案`} value={draft.answers[q.number] || ""} disabled={busy || feedback || !!conflict} onChange={e => { const answers = { ...draft.answers }; if (e.target.value) answers[q.number] = e.target.value; else delete answers[q.number]; edit({ answers }); }}><option value="">尚未选择</option>{q.options.map(option => <option key={option} value={option}>{option}</option>)}</select><button className="cet6-link-button" onClick={() => setWordQuestion(q.number)}>保存本题生词</button>
          {feedback && <div className="cet6-answer-feedback"><strong>{draft.answers[q.number] === q.answer ? "回答正确" : draft.answers[q.number] ? `你的选择：${draft.answers[q.number]}` : "本题未作答"} · 官方答案 {q.answer}</strong><p>{q.explanation}</p><span>本站定位提示；请结合原文核对。</span><button className="cet6-link-button" onClick={() => setPageNumber(q.evidence_page)}>查看依据原页</button></div>}
        </article>)}
      </>}
      {state.first && <div className="cet6-feedback" role="region" aria-label="阅读结果"><strong>已答 {state.first.answered}/30 题，答对 {state.first.correct} 题</strong><p>未答 {30 - state.first.answered} 题；这是本份样卷的答题记录，不换算六级报道分。{state.first.used_help ? "本轮查看过参考或借助了帮助。" : "按你的记录，本轮未勾选帮助。"}</p><button className="cet6-link-button" onClick={() => setPageNumber(paper.answer_page)}>对照官方答案原页</button></div>}
      {wordQuestion !== null && <fieldset disabled={busy || !!conflict} className="cet6-input-group"><ReadingVocabulary key={wordQuestion} notebookId={notebookId} paperId={paperId} readingId="" questionId="" questionNumber={wordQuestion} paragraphs={[]} duringAttempt={!feedback} onHelp={() => edit({ used_help: true })} /></fieldset>}
      <label className="cet6-field">错因与订正笔记<textarea rows={4} maxLength={3000} disabled={busy || !!conflict} value={draft.reflection} onChange={e => edit({ reflection: e.target.value })} placeholder="记录题号、漏看的条件、定位依据，以及下次如何避免。" /></label>
      {!feedback && <label className="cet6-check"><input type="checkbox" checked={draft.used_help} disabled={busy || !!conflict} onChange={e => edit({ used_help: e.target.checked })} />本轮查看了答案或借助提示</label>}
      <p role="status" className="cet6-muted">{busy ? "正在保存…" : dirty ? "有输入尚未保存到账号" : notice || "已读取账号记录"}</p>
      <div className="cet6-actions"><button className="primary-action" disabled={busy || !!conflict} onClick={() => void save("save")}>保存作答与笔记</button>{!feedback && <button className="secondary-action" disabled={busy || !!conflict || !Object.keys(draft.answers).length} onClick={() => void save("submit")}>提交阅读作答</button>}{feedback && <button className="secondary-action" disabled={busy || !!conflict || dirty} onClick={() => void save("restart")}>保留记录，重新作答</button>}</div>
      {feedback && <p className="cet6-muted">建议 {readingDate(state.due_at)} 后再试。重新作答前请先保存订正；这一入口不发送提醒。</p>}
      {error && <div role="alert" className="cet6-error"><p>{error}</p><button className="secondary-action" disabled={busy} onClick={() => setRetry(n => n + 1)}>保留输入，读取账号记录</button></div>}
      {!!state.history.length && <details className="cet6-source"><summary>之前的 {state.history.length} 轮作答</summary>{state.history.map((h, i) => <p key={i}>{readingDate(h.first.submitted_at)} · 已答 {h.first.answered}，答对 {h.first.correct}</p>)}</details>}
    </div></div>
  </section>;
}

function ExternalSources() {
  const [items, setItems] = useState<{ id: string; title: string; url: string; kind: string; course: string; access: string; source_role: string }[]>([]), [kind, setKind] = useState("past_paper"), [error, setError] = useState("");
  useEffect(() => { let active = true; void apiGet<{ items: typeof items }>("/materials").then(r => { if (active) setItems(r.items.filter(m => m.course === "cet6")); }).catch(e => { if (active) setError(readingError(e)); }); return () => { active = false; }; }, []);
  return <details className="cet6-source"><summary>更多历年真题与机构资料 · 原站入口</summary><p>以下保留来源站点的访问方式，尚未全部完成题卷、答案、原音与本站使用条件核验。</p><label className="cet6-field">资料类型<select value={kind} onChange={e => setKind(e.target.value)}><option value="past_paper">历年真题</option><option value="mock">机构专项模拟</option><option value="book">图书配套</option><option value="">全部资料</option></select></label>{error && <p role="alert">{error}</p>}{items.filter(m => !kind || m.kind === kind).map(m => <details className="cet6-source" key={m.id}><summary>{m.title}</summary><p>{m.source_role} · {m.access}</p><a href={m.url} target="_blank" rel="noreferrer">打开原站材料 ↗</a></details>)}</details>;
}
