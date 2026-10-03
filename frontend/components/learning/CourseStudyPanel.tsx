"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, ExternalLink } from "lucide-react";
import Cet6Dashboard from "./Cet6Dashboard";
import Markdown from "@/components/chat/Markdown";
import { apiGet, apiPost } from "@/lib/api";
import type { CourseStudy, StudyProgress, UnitRecord } from "@/lib/course-study";
import { cet6Route } from "@/lib/cet6";

const blank = (): UnitRecord => ({ read: false, practiced: false, checked: false, completed: false, notes: "", next_review: null });
const readable = (e: unknown) => e instanceof Error ? e.message.replace(/^(GET|POST) \S+ → \d+:\s*/, "") : "暂时无法保存，请重试。";

export default function CourseStudyPanel({ notebookId, userId, requestedUnit, onChat, onUpload, onFocus, onReviews }: {
  notebookId: string; userId: string; requestedUnit: { id: string; request: number };
  onChat: (prompt: string) => void; onUpload: () => void; onFocus: (active: boolean) => void; onReviews: () => void;
}) {
  const [readingActive, setReadingActive] = useState(false);
  const [showReferences, setShowReferences] = useState(() => typeof window !== "undefined" && new URLSearchParams(window.location.search).get("notebook") === notebookId && new URLSearchParams(window.location.search).get("cet6") === "references");
  useEffect(() => { onFocus(readingActive); return () => onFocus(false); }, [readingActive, onFocus]);
  const [data, setData] = useState<CourseStudy | null>(null);
  const [unitId, setUnitId] = useState("");
  const [draft, setDraft] = useState<UnitRecord>(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [hasDraft, setHasDraft] = useState(false);
  const [materials, setMaterials] = useState<{ id: string; title: string; url: string; course: string; kind: string; source_role: string; access: string }[]>([]);
  const [materialKind, setMaterialKind] = useState("past_paper");
  const alive = useRef(true);
  const saving = useRef(false);
  const latestRequest = useRef(requestedUnit);
  latestRequest.current = requestedUnit;
  const consumedRequest = useRef(-1);
  const loadVersion = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const key = (id: string) => `learnloop:unit-draft:${userId}:${notebookId}:${id}`;
  const pick = (current: CourseStudy, id: string) => {
    const selected = current.path.units.find(u => u.id === id) || current.path.units[0];
    setUnitId(selected.id); setError(""); setNotice("");
    let restored: UnitRecord | undefined;
    try { const stored = JSON.parse(sessionStorage.getItem(key(selected.id)) || "null"); if (stored?.version === current.path.version) restored = stored.record; } catch { /* Draft storage is optional. */ }
    setDraft(restored || current.progress.units[selected.id] || blank()); setHasDraft(Boolean(restored));
  };
  const load = async (preserveDraft = false) => {
    const ticket = ++loadVersion.current;
    setBusy(true); setError("");
    try {
      const result = await apiGet<CourseStudy>(`/notebooks/${notebookId}/study`);
      if (!alive.current || ticket !== loadVersion.current) return;
      setData(result);
      const last = result.path.units.findIndex(u => u.id === result.progress.last_unit);
      const resume = last >= 0 && result.progress.units[result.progress.last_unit]?.completed
        ? result.path.units.slice(last + 1).find(u => !result.progress.units[u.id]?.completed)?.id || result.progress.last_unit
        : result.progress.last_unit;
      if (!preserveDraft) { pick(result, latestRequest.current.id || resume || result.path.units[0].id); consumedRequest.current = latestRequest.current.request; if (result.path.units.some(u => u.id === latestRequest.current.id)) { setShowReferences(true); if (result.path.course === "cet6") cet6Route(notebookId, "references"); } }
      else setNotice("已读取服务器进度。当前草稿保留；你可以核对后重新保存，或放弃草稿。");
    } catch (e) { if (alive.current && ticket === loadVersion.current) setError(readable(e)); }
    finally { if (alive.current && ticket === loadVersion.current) setBusy(false); }
  };
  useEffect(() => {
    alive.current = true; void load();
    return () => { alive.current = false; loadVersion.current++; };
    // The parent keys this panel by account and notebook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useLayoutEffect(() => {
    if (data && !busy && !saving.current && consumedRequest.current !== requestedUnit.request) {
      consumedRequest.current = requestedUnit.request;
      if (requestedUnit.id) { pick(data, requestedUnit.id); setShowReferences(true); if (data.path.course === "cet6") cet6Route(notebookId, "references"); }
      else { setShowReferences(false); setReadingActive(false); }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedUnit.request, data, busy]);
  const edit = (value: Partial<UnitRecord>) => {
    const updated = { ...draft, ...value };
    if (!updated.read || !updated.practiced || !updated.checked) updated.completed = false;
    setDraft(updated); setHasDraft(true); setNotice("");
    try { sessionStorage.setItem(key(unitId), JSON.stringify({ version: data?.path.version, record: updated })); } catch { /* In-memory copy remains available. */ }
  };
  const at = data?.path.units.findIndex(u => u.id === unitId) ?? -1;
  const unit = data?.path.units[at];
  const save = async (completed: boolean, next = false) => {
    if (!data || !unit || saving.current) return;
    saving.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const record = { ...draft, completed };
      const progress = await apiPost<StudyProgress>(`/notebooks/${notebookId}/study/${unit.id}`, { ...record, version: data.path.version, revision: data.progress.revision });
      if (!alive.current) return;
      const updated = { ...data, progress }; setData(updated); setDraft(record); setHasDraft(false);
      try { sessionStorage.removeItem(key(unit.id)); } catch { /* Optional local draft. */ }
      if (latestRequest.current.request !== consumedRequest.current && latestRequest.current.id) {
        consumedRequest.current = latestRequest.current.request; pick(updated, latestRequest.current.id);
        setNotice("进度已保存。");
      } else if (next && data.path.units[at + 1]) {
        pick(updated, data.path.units[at + 1].id);
        setNotice("本节已保存，开始下一节。");
        requestAnimationFrame(() => heading.current?.focus());
      } else setNotice(completed ? "已记录本节完成。需要时可回来复习。" : "进度已保存，下次从这里继续。");
    } catch (e) { if (alive.current) setError(readable(e)); }
    finally { saving.current = false; if (alive.current) setBusy(false); }
  };
  if (!data || !unit) return <div className="course-study-scroll"><p role="status">{busy ? "正在恢复本课进度…" : error || "本课暂时无法打开。"}</p>{!busy && <button className="secondary-action" onClick={() => void load()}>重新加载课程</button>}</div>;
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
  const due = data.path.units.filter(u => data.progress.units[u.id]?.next_review && data.progress.units[u.id].next_review! <= today);
  const canComplete = draft.read && draft.practiced && draft.checked && draft.notes.trim().length >= 3;
  const completedCount = data.path.units.filter(u => data.progress.units[u.id]?.completed).length;
  if (data.path.course === "cet6") return <div className={`course-study-scroll ${readingActive ? "cet6-study-focus" : ""}`}><Cet6Dashboard key={requestedUnit.request} notebookId={notebookId} userId={userId} onChat={onChat} onFocus={setReadingActive} onReviews={onReviews} chapterDue={[]} onReference={() => { cet6Route(notebookId, "home"); setReadingActive(false); }} /></div>;
  return <div className="course-study-scroll" aria-label="当前课程学习">
    {data.path.course === "cet6" && <button className="secondary-action" onClick={() => { cet6Route(notebookId, "home"); setShowReferences(false); setReadingActive(false); }}>返回六级学习首页</button>}
    <header className="course-study-top" hidden={readingActive}><div><span>{data.path.title}</span><p>已完成 {completedCount} / {data.path.units.length} 节</p></div><button className="secondary-action" onClick={() => onChat("")}>学习对话</button></header>
    <div hidden={readingActive}>
    {!!due.length && data.path.course !== "cet6" && <details className="course-study-review"><summary>有 {due.length} 节到了复习日期</summary>{due.map(u => <button key={u.id} disabled={busy} onClick={() => pick(data, u.id)}>{u.title}</button>)}</details>}
    <article className="course-study-card">
      <div className="course-study-position"><span>{unit.group} · 第 {at + 1} 节</span><span>建议 {unit.minutes} 分钟，可分次完成</span></div>
      <h1 ref={heading} tabIndex={-1}>{unit.title}</h1>
      <p className="course-study-location">{unit.location}</p>
      <section className="course-study-source" aria-label="本节原始材料"><BookOpen size={20} /><div><strong>{unit.source.title}</strong><span>{unit.source.source_role}</span><a href={unit.source.url} target="_blank" rel="noopener noreferrer">打开本节材料 <ExternalLink size={14} /></a></div></section>
      {!!unit.excerpts.length && <details className="course-study-excerpts"><summary>直接阅读相关 Python 官方原文</summary>{unit.excerpts.map(s => <section key={s.id}><h3>{s.title}</h3><Markdown text={s.text} /><small>{s.version} · <a href={s.url} target="_blank" rel="noreferrer">原文出处</a> · <a href={s.license_url} target="_blank" rel="noreferrer">{s.license}</a></small></section>)}</details>}
      <ol className="course-study-steps"><li><strong>阅读或听材料</strong><p>打开上方材料，找到“{unit.location}”。</p></li><li><strong>独立练习</strong><p>{unit.task}</p></li><li><strong>核对与订正</strong><p>{unit.check}</p></li></ol>
      <details className="course-study-source-details"><summary>材料访问与来源说明</summary><p>{unit.source.access}</p><p>{unit.source.verification}</p><p>{data.path.subtitle}</p><p>外站原文未自动导入。需要讲解时，请上传或提供具体原题。</p></details>
      <section className="course-study-record"><h2>记下这次学到哪里</h2>
        <fieldset disabled={busy}><legend className="sr-only">本节完成情况</legend>{([["read", "已读 / 已听材料"], ["practiced", "已完成本节任务"], ["checked", "已核对与订正"]] as const).map(([field, label]) => <label key={field}><input type="checkbox" checked={draft[field]} onChange={e => edit({ [field]: e.target.checked })} />{label}</label>)}</fieldset>
        <label htmlFor={`study-notes-${notebookId}`}>题号、学习结果或还不懂的地方</label><textarea id={`study-notes-${notebookId}`} disabled={busy} rows={4} maxLength={8000} value={draft.notes} onChange={e => edit({ notes: e.target.value })} placeholder="例如：第47题误选B；重新定位后发现漏看了转折。" />
        <label className="course-study-date">下次复习<input type="date" value={draft.next_review || ""} disabled={busy} onChange={e => edit({ next_review: e.target.value || null })} /></label>
        {hasDraft && <p className="course-study-small">当前有未保存草稿，请保存后再关闭浏览器。</p>}
        {error && <div className="course-study-error" role="alert"><p>{error}</p><button disabled={busy} onClick={() => void load(true)}>重新加载进度，保留草稿</button></div>}
        {notice && <p role="status" className="course-study-notice">{notice}</p>}
        <div className="course-study-actions"><button className="secondary-action" disabled={busy} onClick={() => void save(draft.completed)}>保存进度</button><button className="primary-action" disabled={busy || !canComplete} onClick={() => void save(true, true)}>{at + 1 < data.path.units.length ? "完成本节，继续下一节" : "完成本节"}</button></div>
        <p className="course-study-small">完成记录来自你的自查，不计为测评掌握度。</p>
        {hasDraft && <button className="course-study-text-button" disabled={busy} onClick={() => { try { sessionStorage.removeItem(key(unit.id)); } catch {} pick(data, unit.id); }}>放弃草稿，恢复已保存记录</button>}
      </section>
      <div className="course-study-help"><button className="secondary-action" onClick={onUpload}>上传原题 / 教材</button><button className="secondary-action" onClick={() => onChat(`我正在学习${data.path.title}的“${unit.title}”，材料是${unit.source.title}，位置：${unit.location}。请先让我提供原题、原文或截图，再根据实际内容讲解；不要假定你已读过链接。`)}>带着这节课问小知</button></div>
      <nav className="course-study-navigation" aria-label="前后章节"><button disabled={busy || at === 0} onClick={() => pick(data, data.path.units[at - 1].id)}><ArrowLeft size={15} />上一节</button><button disabled={busy || at + 1 >= data.path.units.length} onClick={() => pick(data, data.path.units[at + 1].id)}>先看下一节<ArrowRight size={15} /></button></nav>
    </article>
    <details className="course-study-more" onToggle={e => { if (e.currentTarget.open && !materials.length) void apiGet<{ items: typeof materials }>("/materials").then(r => { if (alive.current) setMaterials(r.items.filter(m => m.course === data.path.course)); }).catch(() => { if (alive.current) setNotice("更多资料暂时无法加载，请稍后重试。"); }); }}><summary>本课更多教材与真题</summary>{data.path.course === "cet6" && <label>资料类型<select value={materialKind} onChange={e => setMaterialKind(e.target.value)}><option value="past_paper">历年真题</option><option value="mock">专项模拟</option><option value="book">图书配套</option><option value="">全部</option></select></label>}{materials.filter(m => data.path.course !== "cet6" || !materialKind || m.kind === materialKind).map(m => <details key={m.id}><summary>{m.title}</summary><p>{m.source_role} · {m.access}</p><a href={m.url} target="_blank" rel="noopener noreferrer">打开原始材料 ↗</a></details>)}</details>
    </div>
  </div>;
}
