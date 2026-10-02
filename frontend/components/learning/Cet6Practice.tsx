"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { apiGet, apiPost, apiAssetUrl } from "@/lib/api";
import { readingDate, readingError, readingRequestId } from "@/lib/reading";
import { readStudyDraft, writeStudyDraft } from "@/lib/study-workspace";
import { cet6Labels, type PracticeSession } from "@/lib/cet6";

type Draft = { answer: string; revision_text: string; reflection: string; used_help: boolean; timed: boolean; baseRevision: number; phase: string; token: string };
const fresh = (s: PracticeSession): Draft => ({ answer: s.answer, revision_text: s.revision_text || "", reflection: s.reflection || "", used_help: s.used_help || false, timed: s.timed || false, baseRevision: s.revision, phase: s.phase, token: readingRequestId() });
const valid = (v: unknown): v is Draft => !!v && typeof v === "object" && ["answer", "revision_text", "reflection", "phase", "token"].every(k => typeof (v as Record<string, unknown>)[k] === "string") && Number.isInteger((v as Draft).baseRevision) && (v as Draft).answer.length <= 10000 && (v as Draft).revision_text.length <= 10000 && (v as Draft).reflection.length <= 1500;

export default function Cet6Practice({ notebookId, userId, taskId, onExit, onChat }: {
  notebookId: string; userId: string; taskId: string; onExit: () => void; onChat: (prompt: string) => void;
}) {
  const [session, setSession] = useState<PracticeSession | null>(null), [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [blocked, setBlocked] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [heard, setHeard] = useState(false);
  const [recovery, setRecovery] = useState<Draft | null>(null), [pendingAction, setPendingAction] = useState("");
  const [showPrevious, setShowPrevious] = useState(false);
  const phaseChange = useRef(false);
  const alive = useRef(true), flight = useRef(false), changes = useRef(0), receipt = useRef<{ key: string; id: string } | null>(null);
  const draftRef = useRef(draft); draftRef.current = draft;
  const url = `/notebooks/${notebookId}/cet6/practice/${taskId}`, key = `learnloop:cet6-practice:${userId}:${notebookId}:${taskId}`;
  const load = async (discard = false) => {
    setBusy(true); setError("");
    try {
      let s = await apiGet<PracticeSession>(url);
      if (!s.revision) s = await apiPost<PracticeSession>(url, { action: "draft", revision: 0, request_id: readingRequestId() });
      if (!alive.current) return;
      const local = discard ? null : readStudyDraft<Draft>(key, valid);
      const restored = local?.phase === s.phase ? local : null;
      const changedPhase = !!local && local.phase !== s.phase;
      setRecovery(changedPhase ? local : null);
      setShowPrevious(s.phase === "feedback");
      setSession(s); setDraft(restored || fresh(s)); setDirty(Boolean(restored)); setBlocked(changedPhase || Boolean(restored && restored.baseRevision !== s.revision));
      if (changedPhase) setError("另一页面已推进练习阶段。本机未同步内容保留在下方，请先复制需要的文字，再使用已保存记录继续。");
      if (restored && restored.baseRevision !== s.revision) setError("服务器已有新记录。本机草稿保留，请先复制需要的文字，或使用已保存记录。");
      if (discard) { try { localStorage.removeItem(key); } catch { /* Optional local drafts. */ } receipt.current = null; }
    } catch (e) { if (alive.current) setError(readingError(e)); }
    finally { if (alive.current) setBusy(false); }
  };
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; /* Account/notebook/task changes remount this panel. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const edit = (patch: Partial<Draft>) => {
    if (!draftRef.current || !session || phaseChange.current || blocked) return;
    const next = { ...draftRef.current, ...patch, baseRevision: session.revision, token: readingRequestId() };
    changes.current++; draftRef.current = next; setDraft(next); setDirty(true); setNotice(""); writeStudyDraft(key, next);
  };
  const action = async (kind: string) => {
    if (!session || !draftRef.current || flight.current || blocked) return false;
    flight.current = true; phaseChange.current = kind !== "draft"; setPendingAction(kind); setBusy(true); setError("");
    const value = draftRef.current, generation = changes.current;
    const body = { action: kind, revision: session.revision, answer: value.answer, revision_text: value.revision_text, reflection: value.reflection, used_help: kind === "restart" ? showPrevious : value.used_help, timed: value.timed };
    const encoded = JSON.stringify(body); if (receipt.current?.key !== encoded) receipt.current = { key: encoded, id: readingRequestId() };
    try {
      const s = await apiPost<PracticeSession>(url, { ...body, request_id: receipt.current.id });
      if (!alive.current) return false;
      setSession(s); setBlocked(false); receipt.current = null;
      if (generation === changes.current || s.phase !== session.phase) {
        const next = fresh(s); draftRef.current = next; setDraft(next); setDirty(false);
        try { if (readStudyDraft<Draft>(key, valid)?.token === value.token) localStorage.removeItem(key); } catch { /* Optional draft storage. */ }
      } else { const pending = { ...draftRef.current!, baseRevision: s.revision }; draftRef.current = pending; setDraft(pending); writeStudyDraft(key, pending); }
      setNotice("已保存到账号"); if (kind === "finish") setShowPrevious(true); if (kind === "restart") { setHeard(false); setShowPrevious(false); } return true;
    } catch (e) { if (alive.current) { setError(readingError(e)); setBlocked(true); } return false; }
    finally { flight.current = false; phaseChange.current = false; if (alive.current) { setBusy(false); setPendingAction(""); } }
  };
  useEffect(() => { if (!dirty || blocked || busy || !draft || session?.phase === "done") return; const timer = setTimeout(() => { void action("draft"); }, 850); return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, blocked, busy, draft, session?.revision]);
  const exit = async () => { if (!dirty || await action("draft")) onExit(); };
  const ask = async () => {
    if (!session?.first || (dirty && !await action("draft"))) return;
    onChat(`请帮助我复盘${cet6Labels[session.task.kind]}练习。材料身份：${session.task.source}。\n题目：${session.task.prompt}\n${session.task.speech_text ? `听力文本：${session.task.speech_text}\n` : ""}我的首次作答：${session.first.answer}\n参考或核对建议：${session.task.reference}\n我目前的修改稿：${draftRef.current?.revision_text || "尚未修改"}\n我记的卡点：${draftRef.current?.reflection || "尚未说明"}\n请先指出最值得改的两个问题和依据，必要时问我当时的思路，再让我自己重写或重听。把AI建议与参考材料分清，不给官方考试分数。`);
  };
  const task = session?.task, isListening = task?.kind === "listening";
  const inputsDisabled = blocked || !!pendingAction && pendingAction !== "draft";
  return <section className="cet6-practice" aria-label="六级专项练习">
    <div className="cet6-section-heading"><button className="cet6-back" disabled={busy} onClick={() => void exit()}><ArrowLeft size={16} />返回专项练习</button><span className="cet6-muted" role="status">{busy ? "正在保存…" : dirty ? "本机草稿保留，正在同步" : notice}</span></div>
    {!session || !draft || !task ? <p role="status">{error || "正在恢复练习…"}</p> : <>
      <p className="cet6-eyebrow">{cet6Labels[task.kind]} · 建议 {task.minutes} 分钟，可分次完成</p><h2>{task.title}</h2><p className="reading-source-badge">{task.source}</p>
      <p className="cet6-prompt" lang={task.kind === "translation" ? "zh-CN" : "en"}>{task.prompt}</p>
      {isListening && <div className="cet6-audio"><audio controls preload="metadata" src={apiAssetUrl(task.audio_url)} onPlay={() => setHeard(true)} onError={() => setError("音频暂时无法播放，请重试或从真题资料入口打开原站音频。")} aria-label="听力短练音频" /><p className="cet6-muted">英语合成语音，非真人考试录音；学习时可重听。计时模式下请自行控制播放次数。</p></div>}
      {session.phase === "answer" && <fieldset disabled={inputsDisabled} className="cet6-input-group">
        <fieldset className="cet6-mode"><legend>作答方式</legend><label><input type="radio" name="practice-mode" checked={!draft.timed} onChange={() => edit({ timed: false })} />学习模式 · 可慢慢尝试</label><label><input type="radio" name="practice-mode" checked={draft.timed} onChange={() => edit({ timed: true })} />计时练习 · 自主计时</label></fieldset>
        {isListening ? <fieldset className="reading-options"><legend className="sr-only">听力选择</legend>{task.options?.map((option, i) => <label key={i}><input type="radio" name="listening-answer" checked={draft.answer === String(i)} onChange={() => edit({ answer: String(i) })} /><span lang="en">{String.fromCharCode(65 + i)}. {option}</span></label>)}</fieldset> : <label className="cet6-field">我的初稿<textarea lang="en" rows={10} maxLength={10000} value={draft.answer} onChange={e => edit({ answer: e.target.value })} placeholder="先自己写，提交后再对照建议修改。" /><small>{draft.answer.trim() ? draft.answer.trim().split(/\s+/).length : 0} 个空格分隔词，仅作长度参考</small></label>}
        <label className="cet6-check"><input type="checkbox" checked={draft.used_help} onChange={e => edit({ used_help: e.target.checked })} />这次作答借助了提示或参考</label>
        <div className="cet6-actions"><button className="secondary-action" disabled={busy || blocked} onClick={() => void action("draft")}>保存初稿</button><button className="primary-action" disabled={busy || blocked || (isListening ? draft.answer === "" || (!heard && !draft.used_help) : draft.answer.trim().length < 10)} onClick={() => void action("submit")}>提交我的作答</button></div>
        {isListening && !heard && <p className="cet6-muted">先播放音频再作答。若已经借助文本或他人提示，请如实勾选。</p>}
      </fieldset>}
      {(session.phase === "feedback" || (session.phase === "done" && showPrevious)) && <>
        <div className="cet6-feedback"><h3>先核对，再改一遍</h3>{isListening && <p>{session.first?.correct ? "这次选择正确" : "这次需要订正"} · 不换算六级成绩</p>}<p>{task.reference}</p>
          {isListening && <details><summary>按需查看听力文本</summary><p lang="en">{task.speech_text}</p><p>看过后收起文本，再重听上方音频。</p></details>}
          <ul>{task.checklist?.map((item, i) => <li key={i}>{item}</li>)}</ul></div>
        <details className="cet6-source"><summary>我的首次作答 · {session.first?.used_help ? "借助提示" : "自述独立"}</summary><p lang="en">{isListening ? task.options?.[Number(session.first?.answer)] : session.first?.answer}</p><p>首次作答已保存，后面的修改单独记录。</p></details>
      </>}
      {session.phase === "feedback" && <fieldset disabled={inputsDisabled} className="cet6-input-group">
        {!isListening && <label className="cet6-field">我的修改稿<textarea lang="en" rows={8} maxLength={10000} value={draft.revision_text} onChange={e => edit({ revision_text: e.target.value })} /></label>}
        <label className="cet6-field">记下一处修改或重听后的发现<textarea rows={3} maxLength={1500} value={draft.reflection} onChange={e => edit({ reflection: e.target.value })} placeholder={isListening ? "哪句话一开始没听懂？不看文本重听后发现了什么？" : "我改了哪句话，为什么改？"} /></label>
        <div className="cet6-actions"><button className="secondary-action" disabled={busy || blocked} onClick={() => void ask()}>带着初稿问小知</button><button className="primary-action" disabled={busy || blocked || draft.reflection.trim().length < 3 || (!isListening && draft.revision_text.trim().length < 10)} onClick={() => void action("finish")}>保存订正，安排复习</button></div>
      </fieldset>}
      {session.phase === "done" && <div className="cet6-complete"><h3>这次练习已保存</h3>{showPrevious && <><p>{session.reflection}</p>{!isListening && <details><summary>查看修改稿</summary><p lang="en">{session.revision_text}</p></details>}</>}<p>下次独立尝试：{readingDate(session.due_at)}。{session.last_early ? "本次提前练习，原日期保留。" : ""}关闭网站后不会发送通知。</p><p className="cet6-muted">同一道题的重做用于巩固；也可以返回练习列表换题检查，不据此认定掌握。</p><div className="cet6-actions"><button className="secondary-action" disabled={busy || blocked} onClick={() => void action("restart")}>{showPrevious ? "看过参考，重新练习" : "隐藏参考，重新独立尝试"}</button><button className="secondary-action" disabled={busy} onClick={() => setShowPrevious(true)}>查看上次记录与参考</button><button className="primary-action" onClick={onExit}>换一题练习</button></div></div>}
      {(session.phase === "feedback" || showPrevious) && !!session.history.length && <details className="cet6-source"><summary>此前练习记录 · {session.history.length} 次</summary>{session.history.map((h, i) => <article key={i}><p>{readingDate(h.first.submitted_at)} · {h.first.used_help ? "借助提示" : "自述独立"}</p><p>{h.first.answer}</p><p>{h.reflection}</p></article>)}</details>}
    </>}
    {recovery && <section className="cet6-source" aria-label="未同步草稿恢复"><h3>本机未同步的草稿</h3>{[["初稿", recovery.answer], ["修改稿", recovery.revision_text], ["发现与笔记", recovery.reflection]].filter(([, text]) => text).map(([label, text]) => <label key={label} className="cet6-field">保留的{label}<textarea readOnly rows={4} value={text} /></label>)}</section>}
    {error && <div className="cet6-error" role="alert"><p>{error}</p><p>当前输入仍在本机草稿中；需要的内容可以先复制。下方操作将放弃本机草稿，恢复服务器记录。</p><button disabled={busy} onClick={() => void load(true)}>使用已保存的记录</button></div>}
  </section>;
}
