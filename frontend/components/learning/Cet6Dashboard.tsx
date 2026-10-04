"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Headphones, MessageCircle, PenLine, Settings2, Type } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { cet6Labels, cet6Route, type Cet6Overview, type Cet6Preferences, type Cet6Kind, type PracticeSummary } from "@/lib/cet6";
import { readingDate, readingError } from "@/lib/reading";
import ReadingTraining from "./ReadingTraining";
import Cet6Vocabulary from "./Cet6Vocabulary";
import Cet6Practice from "./Cet6Practice";
import Cet6Papers from "./Cet6Papers";
import Cet6Exams from "./Cet6Exams";
import Cet6Advice from "./Cet6Advice";
import type { AdviceAction } from "@/lib/cet6-advice";
import type { ExamKind } from "@/lib/cet6-exams";
import "./cet6-learning.css";

const kinds: Cet6Kind[] = ["listening", "reading", "writing", "translation", "vocabulary"];
const descriptions = { listening: "先听，再定位没听懂的地方", reading: "先做，再核对原文证据", writing: "保留初稿，自己修改一遍", translation: "先译，再检查信息与表达", vocabulary: "联系原句，分开练词义与拼写" };
type View = "home" | "reading" | "practice" | "vocabulary" | "papers" | "exams" | "examinfo" | "advice";
const initialRoute = (notebook: string) => {
  if (typeof window === "undefined") return { view: "home" as View, target: "" };
  const params = new URLSearchParams(window.location.search);
  if (params.get("notebook") !== notebook) return { view: "home" as View, target: "" };
  const requested = params.get("reading") ? "reading" : params.get("cet6");
  const view = requested === "examinfo" ? "advice" : requested;
  return { view: (["home", "reading", "practice", "vocabulary", "papers", "exams", "examinfo", "advice"].includes(view || "") ? view : "home") as View,
    target: params.get("cet6_word") || params.get("cet6_task") || params.get("cet6_paper") || params.get("reading") || "" };
};

export default function Cet6Dashboard({ notebookId, userId, onChat, onFocus, onReference, onReviews, chapterDue }: {
  notebookId: string; userId: string; onChat: (prompt: string) => void; onFocus: (active: boolean) => void;
  onReference: (id?: string) => void; onReviews: () => void; chapterDue: { id: string; title: string }[];
}) {
  const initial = useRef(initialRoute(notebookId));
  useEffect(() => { if (new URLSearchParams(window.location.search).get("cet6") === "examinfo") cet6Route(notebookId, "advice"); }, [notebookId]);
  const [view, setView] = useState<View>(initial.current.view), [target, setTarget] = useState(initial.current.target), [practiceKind, setPracticeKind] = useState<Cet6Kind | "all">("all");
  const [data, setData] = useState<Cet6Overview | null>(null), [settings, setSettings] = useState(false), [error, setError] = useState("");
  const [readingFocus, setReadingFocus] = useState(false), [refresh, setRefresh] = useState(0), [readingKey, setReadingKey] = useState(0);
  const [adviceRevision, setAdviceRevision] = useState<number | null>(null);
  const heading = useRef<HTMLHeadingElement>(null), introChecked = useRef(false);
  const skipKey = `learnloop:cet6-intake-skipped:${userId}:${notebookId}`;
  useEffect(() => { let cancelled = false; void apiGet<Cet6Overview>(`/notebooks/${notebookId}/cet6`).then(r => {
    if (cancelled) return; setData(r); setError("");
    if (!introChecked.current) { introChecked.current = true; let skipped = false; try { skipped = localStorage.getItem(skipKey) === "1"; } catch { /* optional browser preference */ }
      if (r.revision === 0 && initial.current.view === "home" && !skipped) setSettings(true);
    }
  }).catch(e => { if (!cancelled) setError(readingError(e)); }); return () => { cancelled = true; }; }, [notebookId, refresh, skipKey]);
  useEffect(() => { onFocus(readingFocus || view === "advice" || settings); return () => onFocus(false); }, [readingFocus, view, settings, onFocus]);
  const skipIntake = () => { setSettings(false); try { localStorage.setItem(skipKey, "1"); } catch { /* still allow learning */ } };
  const navigate = (next: View, id = "", review = false) => { introChecked.current = true; setView(next); setTarget(id); skipIntake(); setReadingFocus(false); if (next !== "advice") setAdviceRevision(null); cet6Route(notebookId, next, id, review); setRefresh(n => n + 1); if (next === "reading") setReadingKey(n => n + 1); requestAnimationFrame(() => heading.current?.focus()); };
  const startAdviceAction = (action: AdviceAction) => {
    if (action.kind === "vocabulary") { navigate("vocabulary"); return; }
    setPracticeKind(action.kind === "reading" ? "all" : action.kind); navigate("exams");
    const url = new URL(window.location.href); url.searchParams.set("exam_kind", action.kind === "reading" ? "reading_careful" : action.kind); url.searchParams.set("exam_paper", action.paper_id);
    window.history.replaceState(null, "", url.pathname + url.search);
  };
  const choose = (kind: Cet6Kind, id = "") => { if (kind === "vocabulary") navigate(kind); else { setPracticeKind(kind); navigate("exams"); } };
  return <div className="cet6-dashboard" aria-label="六级学习首页">
    <header className="cet6-header" hidden={readingFocus}><div><span className="cet6-eyebrow">大学英语六级 · CET-6</span><h1 ref={heading} tabIndex={-1}>六级备考中心</h1><p className="cet6-subtitle">原卷精练 · 词汇精学 · 个性化复习</p></div><button className="secondary-action" onClick={() => setSettings(true)} aria-expanded={settings}><Settings2 size={15} />学习偏好</button></header>
    {!readingFocus && <nav className="cet6-main-nav" aria-label="六级学习入口">{([["home", "今天"], ["advice", "备考建议"], ["exams", "真题练习"], ["vocabulary", "背单词"]] as const).map(([id, label]) => <button key={id} aria-current={view === id && !settings ? "page" : undefined} onClick={() => { if (id === "exams") setPracticeKind("all"); if (id === "advice") setAdviceRevision(null); navigate(id); }}>{label}</button>)}<button onClick={() => onChat("")}><MessageCircle size={14} />问小知</button></nav>}
    {error && <p role="alert" className="cet6-error">{error}<button onClick={() => setRefresh(n => n + 1)}>重试首页</button></p>}
    {settings && data && <Preferences key={`${notebookId}:${data.revision}`} notebookId={notebookId} initial={data} onSaved={saved => { setData(d => d ? { ...d, ...saved } : d); setAdviceRevision(saved.revision); navigate("advice"); }} onCancel={skipIntake} />}
    {view === "advice" && !settings && <>
      {data && <section className="cet6-advice-goal" aria-label="当前备考目标"><strong>当前目标</strong><p>{goalSummary(data.preferences)}</p></section>}
      <Cet6Advice key={notebookId} notebookId={notebookId} autoRevision={adviceRevision} onEdit={() => setSettings(true)} onStart={startAdviceAction} />
      <details className="cet6-source"><summary>考试说明与成绩要求</summary><h3>报考资格</h3><p>通常须符合在校生等报名条件，且大学英语四级成绩达到 425 分。具体报名范围、名额与时间以所在学校当次通知为准。</p><h3>成绩与练习</h3><p>六级报道分数满分 710，听力与阅读各 249，写作与翻译合计 212。报道分数经过转换，本站练习正确率不能直接换算成六级分数。</p><p>练习时分别检查听力关键信息、阅读原文依据，以及写作翻译中的信息、准确性与连贯性；再结合实际错题调整备考安排。</p><p><a href="https://cet.neea.edu.cn/html1/folder/16113/1588-1.htm" target="_blank" rel="noreferrer">官方考试大纲 ↗</a> · <a href="https://www.neea.edu.cn/html1/folder/19081/5124-1.htm" target="_blank" rel="noreferrer">官方分数解释 ↗</a></p></details>
    </>}
    {view === "home" && !settings && <>
      {!data ? <p role="status">正在整理你的学习安排…</p> : <>
        <div className="cet6-entry-grid"><button onClick={() => navigate("vocabulary")}><BookOpen size={23} /><strong>背单词</strong><span>每天新学 {data.preferences.daily_new_words} 个 · 闪卡回忆与精讲</span><ArrowRight size={18} /></button><button onClick={() => { setPracticeKind("all"); navigate("exams"); }}><PenLine size={23} /><strong>练真题</strong><span>先选板块与套卷 · 提交后查看逐题解析</span><ArrowRight size={18} /></button></div>
        <section className="cet6-today" aria-label="今天的学习建议"><div className="cet6-today-meta"><span>今天先做一件事</span><span>你设置了 {data.preferences.daily_minutes} 分钟 / 天</span></div><h2>{data.recommendation.kind === "vocabulary" ? data.recommendation.title : `选择一套${cet6Labels[data.recommendation.kind]}真题`}</h2><p>{data.recommendation.kind === "vocabulary" ? data.recommendation.reason : "先独立作答，再对照原卷理解答案。时间不够可以暂停，已保存的作答能够继续。"}</p><div className="cet6-actions"><button className="primary-action" onClick={() => choose(data.recommendation.kind, data.recommendation.id)}>开始 / 继续<ArrowRight size={17} /></button><button className="cet6-link-button" onClick={() => { setPracticeKind("all"); navigate("exams"); }}>我想自己选</button></div><p className="cet6-muted">{goalSummary(data.preferences)}</p></section>
        <div className="cet6-overview"><button onClick={() => navigate("vocabulary")}><strong>{data.stats.word_due}</strong><span>词卡到期 · 建议先用 {data.review_minutes} 分钟</span></button><button onClick={() => navigate("vocabulary")}><strong>{data.stats.collected}</strong><span>已收藏的词汇义项</span></button></div>
        <h2 className="cet6-small-title">今天更想练什么？</h2><div className="cet6-skill-grid">{kinds.map((kind, i) => { const Icon = [Headphones, BookOpen, PenLine, Type, BookOpen][i]; return <button key={kind} onClick={() => choose(kind)}><Icon size={21} /><strong>{cet6Labels[kind]}</strong><span>{descriptions[kind]}</span><ArrowRight size={16} /></button>; })}</div>
        {data.preferences.mode === "exam" && <p className="cet6-muted">每个真题板块标注原卷参考用时。练习结果只描述这次作答，不预测考试分数。</p>}
        {!!data.recent.length && <details className="cet6-source"><summary>最近的学习记录</summary>{data.recent.map((r, i) => <p key={i}>{cet6Labels[r.kind]} · {readingDate(r.at)} · {r.independent ? "自述独立作答" : "借助提示"}{r.ratio !== undefined ? ` · 本次正确率 ${Math.round(r.ratio * 100)}%` : ""}</p>)}<p>这里只描述这些练习，不预测考试分数；写作和翻译的自查不计为掌握度。</p></details>}
        <p className="cet6-footnote">新对话开启新话题，目标、生词与练习记录仍保留在本课程。学习偏好随时可改。</p>
      </>}
    </>}
    {view === "reading" && <ReadingTraining key={`${notebookId}:${readingKey}`} notebookId={notebookId} userId={userId} onFocus={setReadingFocus} onChat={onChat} chapterDue={chapterDue} onChapter={onReference} onReviews={onReviews} />}
    {view === "vocabulary" && <Cet6Vocabulary key={`${notebookId}:${target}`} notebookId={notebookId} initialWord={target} onChat={onChat} onChanged={() => setRefresh(n => n + 1)} onFocus={setReadingFocus} />}
    {view === "practice" && (target ? <Cet6Practice key={`${notebookId}:${target}`} notebookId={notebookId} userId={userId} taskId={target} onChat={onChat} onExit={() => navigate("practice")} /> : <PracticePicker notebookId={notebookId} kind={practiceKind} onKind={setPracticeKind} onReading={() => navigate("reading")} onOpen={id => navigate("practice", id)} />)}
    {view === "papers" && <Cet6Papers key={`${notebookId}:${target}`} notebookId={notebookId} initialPaper={target} />}
    {view === "exams" && <Cet6Exams key={`${notebookId}:${practiceKind}`} notebookId={notebookId} userId={userId} onFocus={setReadingFocus} initialKind={practiceKind !== "all" && practiceKind !== "vocabulary" ? practiceKind as ExamKind : undefined} />}
  </div>;
}

function goalSummary(preferences: Cet6Preferences) {
  return [preferences.goal, preferences.target_score !== null ? `目标 ${preferences.target_score} 分` : "",
    preferences.exam_date ? `考试日期 ${preferences.exam_date}` : ""].filter(Boolean).join(" · ") || "可以先开始学习，之后再补充目标。";
}

function Preferences({ notebookId, initial, onSaved, onCancel }: { notebookId: string; initial: Cet6Overview; onSaved: (saved: Pick<Cet6Overview, "revision" | "preferences">) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState(initial.preferences), [revision, setRevision] = useState(initial.revision), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [serverCopy, setServerCopy] = useState<Cet6Overview | null>(null);
  const alive = useRef(true); useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const edit = (patch: Partial<Cet6Preferences>) => setDraft(d => ({ ...d, ...patch }));
  const save = async (e: React.FormEvent) => { e.preventDefault(); if (serverCopy) return; setBusy(true); setError(""); try { const saved = await apiPost<Pick<Cet6Overview, "revision" | "preferences">>(`/notebooks/${notebookId}/cet6/preferences`, { revision, preferences: draft }); if (alive.current) onSaved(saved); } catch (e) { if (alive.current) setError(readingError(e)); } finally { if (alive.current) setBusy(false); } };
  return <form className="cet6-preferences" onSubmit={save} aria-label="学习偏好设置"><h2>你想怎样学？</h2><p>告诉小知你的情况，填完即可查看备考分析、各项学习方法和近期安排。成绩和日期都可以留空，也可以先开始学习。</p>
    <label className="cet6-field">我现在最想解决的问题<textarea rows={2} maxLength={300} value={draft.goal} onChange={e => edit({ goal: e.target.value })} placeholder="例如：词都认识，但阅读时找不到句子之间的关系。" /></label>
    <div className="cet6-form-grid"><label className="cet6-field">学习侧重点<select value={draft.mode} onChange={e => edit({ mode: e.target.value as Cet6Preferences["mode"] })}><option value="foundation">先补基础</option><option value="balanced">专项与综合结合</option><option value="exam">考前练习</option></select></label><label className="cet6-field">每天可用分钟<input type="number" min={5} max={180} required value={draft.daily_minutes} onChange={e => edit({ daily_minutes: Number(e.target.value) })} /></label><label className="cet6-field">目标分数（选填）<input type="number" min={0} max={710} value={draft.target_score ?? ""} onChange={e => edit({ target_score: e.target.value ? Number(e.target.value) : null })} /></label><label className="cet6-field">考试日期（选填）<input type="date" value={draft.exam_date || ""} onChange={e => edit({ exam_date: e.target.value || null })} /></label></div>
    <fieldset className="cet6-focus"><legend>希望优先练的内容（可多选，也可留空）</legend>{kinds.map(kind => <label key={kind}><input type="checkbox" checked={draft.focus.includes(kind)} onChange={e => edit({ focus: e.target.checked ? [...draft.focus, kind] : draft.focus.filter(k => k !== kind) })} />{cet6Labels[kind]}</label>)}</fieldset>
    <details className="cet6-source"><summary>参考历史成绩（选填）</summary><p>只有总分时不能判断单项短板。写作与翻译按成绩单合计填写，不拆成两项。</p><div className="cet6-form-grid">{([["total_score", "历史总分", 710], ["listening_score", "听力成绩", 249], ["reading_score", "阅读成绩", 249], ["writing_translation_score", "写作与翻译合计", 212]] as const).map(([field, label, max]) => <label className="cet6-field" key={field}>{label}<input type="number" min={0} max={max} value={draft[field] ?? ""} onChange={e => edit({ [field]: e.target.value ? Number(e.target.value) : null })} /></label>)}</div></details>
    <details className="cet6-source"><summary>补充上次备考情况（选填）</summary><div className="cet6-form-grid"><label className="cet6-field">上次怎样准备<select value={draft.preparation || "unknown"} onChange={e => edit({ preparation: e.target.value as Cet6Preferences["preparation"] })}><option value="unknown">暂不填写</option><option value="none">几乎没有准备</option><option value="irregular">断断续续准备过</option><option value="regular">持续安排过备考</option></select></label><label className="cet6-field">上次阅读完成情况<select value={draft.reading_completion || "unknown"} onChange={e => edit({ reading_completion: e.target.value as Cet6Preferences["reading_completion"] })}><option value="unknown">暂不填写</option><option value="finished">基本做完</option><option value="unfinished">有题没来得及做</option><option value="not_taken">还没考过六级</option></select></label></div></details>
    {error && <div role="alert" className="cet6-error"><p>{error}</p><button type="button" disabled={busy} onClick={async () => { try { const r = await apiGet<Cet6Overview>(`/notebooks/${notebookId}/cet6`); if (alive.current) { setServerCopy(r); setError("已读取另一页面保存的偏好。请比较后选择要保留的内容。"); } } catch (e) { if (alive.current) setError(readingError(e)); } }}>读取最新偏好，保留输入</button></div>}
    {serverCopy && <section className="cet6-source" aria-label="最新学习偏好"><h3>另一页面保存的偏好</h3><p>{serverCopy.preferences.goal || "目标未填写"} · 每天 {serverCopy.preferences.daily_minutes} 分钟 · {{ foundation: "先补基础", balanced: "专项与综合结合", exam: "考前练习" }[serverCopy.preferences.mode]}</p><p>优先：{serverCopy.preferences.focus.map(k => cet6Labels[k]).join("、") || "未指定"} · 目标 {serverCopy.preferences.target_score ?? "未填"} 分 · 考试日期 {serverCopy.preferences.exam_date || "未填"}</p><p>历史成绩：总分 {serverCopy.preferences.total_score ?? "未填"}；听力 {serverCopy.preferences.listening_score ?? "未填"}；阅读 {serverCopy.preferences.reading_score ?? "未填"}；写作与翻译 {serverCopy.preferences.writing_translation_score ?? "未填"}</p><div className="cet6-actions"><button type="button" className="secondary-action" onClick={() => { setDraft(serverCopy.preferences); setRevision(serverCopy.revision); setServerCopy(null); setError(""); }}>使用最新偏好</button><button type="button" className="secondary-action" onClick={() => { setRevision(serverCopy.revision); setServerCopy(null); setError("已保留本页输入，再次保存将替换上面读取的偏好。"); }}>保留本页输入，准备替换</button></div></section>}
    <div className="cet6-actions"><button className="primary-action" type="submit" disabled={busy || !!serverCopy}>{busy ? "正在保存…" : "保存并查看建议"}</button><button className="secondary-action" type="button" disabled={busy} onClick={onCancel}>{initial.revision === 0 ? "先开始学习" : "暂时不改"}</button></div>
  </form>;
}

function PracticePicker({ notebookId, kind, onKind, onReading, onOpen }: { notebookId: string; kind: Cet6Kind | "all"; onKind: (kind: Cet6Kind | "all") => void; onReading: () => void; onOpen: (id: string) => void }) {
  const [items, setItems] = useState<PracticeSummary[]>([]), [error, setError] = useState(""), [retry, setRetry] = useState(0);
  useEffect(() => { let alive = true; void apiGet<{ items: PracticeSummary[] }>(`/notebooks/${notebookId}/cet6/practice`).then(r => { if (alive) { setItems(r.items); setError(""); } }).catch(e => { if (alive) setError(readingError(e)); }); return () => { alive = false; }; }, [notebookId, retry]);
  return <section aria-label="选择专项练习"><h2>专项巩固练习</h2><p className="cet6-muted">这里是本站自编基础短练，非历年真题，难度尚未校准。官方样卷与历年材料请从“真题与模拟”进入。初稿、订正和复习分别保存。</p><nav className="cet6-tabs" aria-label="专项类别">{(["all", "listening", "reading", "writing", "translation"] as const).map(k => <button key={k} aria-pressed={kind === k} onClick={() => onKind(k)}>{k === "all" ? "全部" : cet6Labels[k]}</button>)}</nav>
    {error && <p role="alert" className="cet6-error">{error}<button onClick={() => setRetry(n => n + 1)}>重试练习列表</button></p>}
    {(kind === "all" || kind === "reading") && <button className="cet6-practice-item" onClick={onReading}><span><strong>阅读：原文证据与错因订正</strong><small>预置体验短文 / 自备材料 · 首次答案、订正、隔时复习</small></span><ArrowRight size={18} /></button>}
    {items.filter(t => kind === "all" || t.kind === kind).map(t => <button className="cet6-practice-item" key={t.id} onClick={() => onOpen(t.id)}><span><small>{cet6Labels[t.kind]} · 建议 {t.minutes} 分钟</small><strong>{t.title}</strong><small>{t.source}</small><small>{t.progress ? t.progress.phase === "done" ? `已订正 · 下次 ${readingDate(t.progress.due_at)}` : "上次尚未完成，可继续" : "尚未开始"}</small></span><ArrowRight size={18} /></button>)}
  </section>;
}
