"use client";

import { useEffect, useRef, useState } from "react";
import AuthGate, { type AuthUser } from "@/components/auth/AuthGate";
import { apiGet, apiPost, UNAUTHORIZED_EVENT } from "@/lib/api";
import "./materials.css";

type Material = { id: string; course: string; title: string; provider: string; source_role: string; kind: string; year?: string; url: string; scope: string; access: string; checked_on: string; verification: string; task: string; skills: string[] };
type Catalog = { courses: Record<string, string>; kinds: Record<string, string>; items: Material[]; boundary: string };
type Study = { id: string; material_id: string; revision: number; task: string; location: string; notes: string; minutes: number; next_review: string | null; status: "planned" | "learning" | "review" | "done" };
const statuses = { planned: "准备开始", learning: "正在学习", review: "需要复习", done: "本次任务已完成" };
const errorText = (e: unknown) => e instanceof Error ? e.message.replace(/^(GET|POST) \S+ → \d+:\s*/, "") : "暂时无法连接，请重试。";
const localDate = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

export default function MaterialsPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);
  const [login, setLogin] = useState(false);
  const [studies, setStudies] = useState<Study[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Study>>({});
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState("catalog");
  const [course, setCourse] = useState("");
  const [kind, setKind] = useState("");
  const [provider, setProvider] = useState("");
  const [year, setYear] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(12);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const epoch = useRef(0);
  const pending = useRef("");
  const dirty = useRef(false);
  const draftSnapshot = useRef({ owner: "", drafts, selected });
  const recovery = useRef<typeof draftSnapshot.current | null>(null);
  draftSnapshot.current = { owner: user?.id || "", drafts, selected };
  dirty.current = Object.keys(drafts).length > 0 || !!recovery.current;

  const loadCatalog = () => apiGet<Catalog>("/materials").then(setCatalog).catch(e => setError(errorText(e)));
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    setCourse(q.get("course") || ""); setKind(q.get("kind") || ""); setProvider(q.get("provider") || ""); setYear(q.get("year") || ""); setQuery(q.get("q") || ""); setTab(q.get("tab") === "studies" ? "studies" : "catalog");
    let active = true;
    void loadCatalog();
    // An anonymous browse is normal and should not dispatch a global expired-session event.
    void fetch("/api/auth/me").then(r => r.ok ? r.json() : null).then(u => { if (active) setUser(u); }).catch(() => {}).finally(() => { if (active) setReady(true); });
    const expired = () => {
      if (draftSnapshot.current.owner && Object.keys(draftSnapshot.current.drafts).length) recovery.current = draftSnapshot.current;
      epoch.current++; setUser(null); setStudies([]); setDrafts({}); setSelected(""); setBusy(false);
      setError("登录已失效。请重新登录；当前页的未保存草稿将在同一账号登录后恢复，关闭此页会丢失草稿。");
    };
    const warn = (e: BeforeUnloadEvent) => { if (dirty.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener(UNAUTHORIZED_EVENT, expired); window.addEventListener("beforeunload", warn);
    return () => { active = false; epoch.current++; window.removeEventListener(UNAUTHORIZED_EVENT, expired); window.removeEventListener("beforeunload", warn); };
  }, []);

  useEffect(() => {
    if (!ready) return;
    const q = new URLSearchParams();
    for (const [key, value] of Object.entries({ course, kind, provider, year, q: query, tab: tab === "studies" ? tab : "" })) if (value) q.set(key, value);
    window.history.replaceState(null, "", `/materials${q.size ? `?${q}` : ""}`); setLimit(12);
  }, [ready, course, kind, provider, year, query, tab]);

  useEffect(() => {
    if (!user) return;
    const ticket = ++epoch.current;
    setBusy(true);
    void (async () => {
      const data = await apiGet<{ items: Study[] }>("/materials/studies");
      if (ticket !== epoch.current) return;
      setStudies(data.items);
      if (recovery.current) {
        if (recovery.current.owner === user.id) { setDrafts(recovery.current.drafts); setSelected(recovery.current.selected); setNotice("已恢复当前账号的未保存草稿，请核对后保存。"); }
        recovery.current = null;
      }
      setError("");
      if (pending.current) {
        const id = pending.current; pending.current = "";
        const saved = await apiPost<Study>("/materials/studies", { material_id: id });
        if (ticket !== epoch.current) return;
        setStudies(prev => [...prev.filter(x => x.id !== saved.id), saved]); setSelected(saved.id); setTab("studies"); setNotice("已加入学习清单。打开原始资料后，把题号或章节记在这里。");
      }
    })().catch(e => { if (ticket === epoch.current) setError(errorText(e)); }).finally(() => { if (ticket === epoch.current) setBusy(false); });
    return () => { epoch.current++; };
  }, [user]);

  const add = async (material: Material) => {
    setError(""); setNotice("");
    if (!user) { pending.current = material.id; setLogin(true); return; }
    const ticket = epoch.current; setBusy(true);
    try {
      const saved = await apiPost<Study>("/materials/studies", { material_id: material.id });
      if (ticket !== epoch.current) return;
      setStudies(prev => [...prev.filter(x => x.id !== saved.id), saved]); setSelected(saved.id); setTab("studies"); setNotice("已加入学习清单。先打开原文，再记录今天的任务。");
    } catch (e) { if (ticket === epoch.current) setError(errorText(e)); } finally { if (ticket === epoch.current) setBusy(false); }
  };
  const save = async (draft: Study) => {
    const ticket = epoch.current; setBusy(true); setError(""); setNotice("");
    try {
      const { id, material_id: _material, ...data } = draft;
      const saved = await apiPost<Study>(`/materials/studies/${id}`, data);
      if (ticket !== epoch.current) return;
      setStudies(prev => prev.map(s => s.id === id ? saved : s)); setDrafts(prev => { const next = { ...prev }; delete next[id]; return next; });
      setNotice("学习记录已保存。完成与用时由你记录，不计入测评能力分数。");
    } catch (e) { if (ticket === epoch.current) setError(errorText(e)); } finally { if (ticket === epoch.current) setBusy(false); }
  };
  const reload = async () => {
    const ticket = epoch.current; setBusy(true);
    try { const data = await apiGet<{ items: Study[] }>("/materials/studies"); if (ticket === epoch.current) { setStudies(data.items); setError(""); setNotice("已加载服务器记录。未保存的草稿仍保留；可复制后选择放弃草稿。"); } }
    catch (e) { if (ticket === epoch.current) setError(errorText(e)); } finally { if (ticket === epoch.current) setBusy(false); }
  };
  const logout = async () => { try { await apiPost("/auth/logout", {}); epoch.current++; setUser(null); setStudies([]); setDrafts({}); setSelected(""); setNotice(""); } catch (e) { setError(errorText(e)); } };
  const edit = (row: Study, patch: Partial<Study>) => setDrafts(prev => ({ ...prev, [row.id]: { ...(prev[row.id] || row), ...patch } }));

  if (login) return <><button className="materials-back" onClick={() => { setLogin(false); pending.current = ""; }}>← 返回资料中心</button><AuthGate onAuthenticated={u => { setUser(u); setLogin(false); }} /></>;
  const items = catalog?.items || [];
  const visible = items.filter(m => (!course || m.course === course) && (!kind || m.kind === kind) && (!provider || m.provider === provider) && (!year || m.year === year) && (!query || `${m.title} ${m.provider} ${m.scope} ${m.skills.join(" ")}`.toLowerCase().includes(query.toLowerCase())));
  const saved = studies.find(s => s.id === selected);
  const current = saved && (drafts[saved.id] || saved);
  const currentMaterial = current && items.find(m => m.id === current.material_id);
  const due = studies.filter(s => s.next_review && s.next_review <= localDate());
  const resetFilters = () => { setCourse(""); setKind(""); setProvider(""); setYear(""); setQuery(""); };
  return <main id="main" className="materials-page">
    <header className="materials-header"><a href="/">知行循证 <span>LearnLoop</span></a><nav aria-label="学习导航"><a href="/library">课程目录</a><a href="/">学习工作区</a>{user ? <button disabled={busy || dirty.current} onClick={() => void logout()}>退出登录</button> : <button disabled={!ready} onClick={() => setLogin(true)}>登录保存进度</button>}</nav></header>
    <section className="materials-intro"><p className="materials-eyebrow">从可靠的原始资料开始</p><h1>找到真资料，把学习做下去。</h1><p>六级真题、配套音频、官方教材和大学习题。先到原站学习，再回到这里记录题号、错因和下一次复习。</p><p className="materials-boundary">{catalog?.boundary || "正在载入已核查的资料目录…"}</p></section>
    <div className="materials-tabs" aria-label="资料视图"><button aria-pressed={tab === "catalog"} onClick={() => setTab("catalog")}>找资料</button><button aria-pressed={tab === "studies"} onClick={() => setTab("studies")}>我的学习清单{studies.length > 0 ? ` · ${studies.length}` : ""}</button>{due.length > 0 && <span>有 {due.length} 项到了复习日期</span>}</div>
    {error && <div className="materials-error" role="alert">{error}</div>}{notice && <p className="materials-notice" role="status">{notice}</p>}
    {busy && <p role="status">正在保存或载入学习记录…</p>}
    {tab === "catalog" ? <>
      <section className="materials-filters" aria-label="筛选资料"><label className="materials-search">搜索资料<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="例如：阅读、2025、词汇、函数" /></label>
        <label>课程<select value={course} onChange={e => setCourse(e.target.value)}><option value="">全部课程</option>{Object.entries(catalog?.courses || {}).map(([id, title]) => <option key={id} value={id}>{title}</option>)}</select></label>
        <label>资料类型<select value={kind} onChange={e => setKind(e.target.value)}><option value="">全部类型</option>{Object.entries(catalog?.kinds || {}).map(([id, title]) => <option key={id} value={id}>{title}</option>)}</select></label>
        <label>来源<select value={provider} onChange={e => setProvider(e.target.value)}><option value="">全部来源</option>{Array.from(new Set(items.map(m => m.provider))).map(p => <option key={p}>{p}</option>)}</select></label>
        <label>考期 / 版本<select value={year} onChange={e => setYear(e.target.value)}><option value="">全部考期</option>{Array.from(new Set(items.map(m => m.year).filter((y): y is string => !!y))).sort().reverse().map(y => <option key={y}>{y}</option>)}</select></label>
      </section>
      <div className="materials-result"><p>{catalog ? `${visible.length} 个资料入口` : "正在载入…"} <small>入口数量不代表完整试卷套数</small></p><button onClick={resetFilters}>清除筛选</button></div>
      {!catalog && <button onClick={() => void loadCatalog()}>重新加载目录</button>}
      {catalog && visible.length === 0 && <p className="materials-empty">暂未收录符合条件的资料。可以减少筛选条件，或到已收录的出版方目录继续查找。</p>}
      <div className="materials-grid">{visible.slice(0, limit).map(m => <article className="material-card" key={m.id}>
        <p className="materials-eyebrow">{catalog?.courses[m.course]} · {catalog?.kinds[m.kind]}{m.year ? ` · ${m.year}` : ""}</p><h2>{m.title}</h2><p className="material-provider">{m.provider} · {m.source_role}</p><p>{m.scope}</p><p className="material-access">{m.access}</p>
        <details><summary>怎么用 · 核查范围</summary><p><strong>建议任务：</strong>{m.task}</p><p>{m.verification}</p><small>核查日期：{m.checked_on}。原站内容与访问条件可能变化。</small></details>
        <footer>{m.provider === "Python 官方文档" && <a className="materials-primary" href="/library#course-python_foundations">先读站内官方教程摘录</a>}<a className="materials-primary" href={m.url} target="_blank" rel="noopener noreferrer">打开原始资料 ↗</a><button disabled={busy || !ready} onClick={() => void add(m)}>{studies.some(s => s.material_id === m.id) ? "查看学习记录" : "加入学习清单"}</button></footer>
      </article>)}</div>
      {visible.length > limit && <button className="materials-more" onClick={() => setLimit(l => l + 12)}>再看 12 项资料</button>}
    </> : !user ? <section className="materials-empty"><h2>把学习记录留在自己的账号里</h2><p>浏览和打开资料无需登录。登录后可以保存任务、错题与复习日期。</p><button onClick={() => setLogin(true)}>登录 / 创建账号</button></section> : <section className="material-study-layout" aria-label="我的学习清单">
      <aside><h2>我的学习清单</h2><button disabled={busy} onClick={() => void reload()}>重新加载记录</button>{studies.length === 0 && <p>还没有资料。先到“找资料”加入今天要学的一项。</p>}{studies.map(s => <button className="material-study-choice" aria-pressed={selected === s.id} key={s.id} onClick={() => setSelected(s.id)}><strong>{items.find(m => m.id === s.material_id)?.title || "以前保存的资料"}</strong><small>{statuses[s.status]}{drafts[s.id] ? " · 有未保存草稿" : ""}</small>{s.next_review && <small>复习：{s.next_review}{s.next_review <= localDate() ? " · 已到期" : ""}</small>}</button>)}</aside>
      {current ? <form className="material-study-editor" onSubmit={e => { e.preventDefault(); void save(current); }}><h2>{currentMaterial?.title || "学习记录"}</h2>{currentMaterial && <a href={currentMaterial.url} target="_blank" rel="noopener noreferrer">打开原始资料 ↗</a>}<p>记录你实际完成的题目与章节。资料链接不会自动变成 AI 已读的知识库。</p>
        <fieldset disabled={busy}><label>本次任务<input maxLength={500} value={current.task} onChange={e => edit(current, { task: e.target.value })} /></label><label>做到哪里（题号 / 页码 / 章节）<input maxLength={300} value={current.location} onChange={e => edit(current, { location: e.target.value })} placeholder="例如：第一套阅读 46—50 题" /></label><label>错题与复盘<textarea rows={6} maxLength={8000} value={current.notes} onChange={e => edit(current, { notes: e.target.value })} placeholder="我的答案 → 原站参考答案 → 错因 → 下次怎样验证" /></label>
        <div className="material-study-fields"><label>累计用时（分钟）<input type="number" min={0} max={100000} required value={current.minutes} onChange={e => edit(current, { minutes: Number(e.target.value) })} /></label><label>下次复习日期<input type="date" value={current.next_review || ""} onChange={e => edit(current, { next_review: e.target.value || null })} /></label><label>任务状态<select value={current.status} onChange={e => edit(current, { status: e.target.value as Study["status"] })}>{Object.entries(statuses).map(([id, title]) => <option key={id} value={id}>{title}</option>)}</select></label></div>
        <button className="materials-primary" type="submit">保存学习记录</button>{drafts[current.id] && <button type="button" onClick={() => setDrafts(prev => { const next = { ...prev }; delete next[current.id]; return next; })}>放弃草稿，显示已保存记录</button>}</fieldset>
        <p className="materials-boundary">这里保存自述学习记录，不推算六级成绩，也不把“完成”视为掌握。</p><details><summary>需要小知帮忙复盘？</summary><p>在学习工作区上传你有权使用的题目，或粘贴题干、你的答案和原站参考解析，再请小知解释错因。只有链接时，小知不能声称已读完整试卷。</p><a href="/">进入学习工作区 →</a></details>
      </form> : <p className="materials-empty">选择一项资料，记录今天的学习。</p>}
    </section>}
  </main>;
}
