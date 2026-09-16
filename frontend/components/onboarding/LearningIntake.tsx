"use client";

import { ArrowLeft, ArrowRight, Check, Compass, Lightbulb, Play, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Assessment, StudySurvey, CourseScope } from "@/lib/assessment";
import { apiGet, apiPost, apiUpload, USER_ID } from "@/lib/api";

export const DEFAULT_SURVEY: StudySurvey = {
  daily_minutes: 20, study_days: [1, 2, 3, 4, 5], goal: "掌握课程基础",
  goals: [], barriers: [], supports: [], stage: "大学课程", prior_experience: "不确定",
  pressure: "skip", study_habit: "skip", support: "", target_date: null,
  study_cue: "", materials_status: "暂时没有", intro_practiced: false,
  course_key: "custom", course_title: "", notebook_id: "", source_ids: [], course_revision: "",
};

const GOALS = [
  ["看懂学习资料", "看懂手头的课件或教材", "围绕你的资料解释概念、例子与难点"],
  ["掌握课程基础", "从零开始，系统学习", "把概念和例题一步步学明白"],
  ["准备课程考试", "准备课程考试", "围绕考点、题型和剩余时间安排"],
  ["独立解题与纠错", "听懂了，但自己不会做", "找到卡点，练到可以独立完成"],
  ["安排计划与复习", "制定计划，安排复习", "把学习放进实际可用的时间"],
  ["完成项目或实践", "完成项目或实际任务", "拆分任务，用具体成果检查进步"],
  ["探索学习起点", "还不确定，帮我找起点", "先用小题了解，再一起决定"],
] as const;
const BARRIERS = [
  ["concepts", "概念和符号看不懂", "先解释含义，再连接例子"],
  ["application", "看懂答案，自己不会做", "例题 → 补步骤 → 独立练习"],
  ["coding", "思路懂，代码写不出", "逐行追踪，练习伪代码和边界"],
  ["forgetting", "学过很快就忘", "加入回忆、换题与分日复习"],
  ["starting", "任务太大，难以开始", "把第一步拆小，完成后再继续"],
] as const;
const SUPPORTS = [
  ["visual", "图示和状态变化", "看清每一步怎样变化"],
  ["steps", "符号与步骤讲细些", "新符号和推理都说明白"],
  ["examples", "先看完整例题", "理解后逐渐减少帮助"],
  ["hints", "先给提示，让我自己想", "遇到困难再逐级帮助"],
  ["small_steps", "任务短一些", "先完成一个够得着的小步骤"],
] as const;
const STAGES = ["大学课程", "高中提前学习", "考研复习", "工作后自学", "不方便回答"];
const EXPERIENCE = ["不确定", "第一次系统学习", "学过概念但做题困难", "能做基础题", "做过综合题或项目", "不方便回答"];
const TITLES = ["你希望小知先帮你完成什么？", "这次，我们一起学什么？", "哪些地方需要小知多帮一步？", "给学习留一段真实的时间", "核对范围，再找到学习起点"];
const COURSES = [["ds_algo", "数据结构与算法"], ["python", "Python 入门"], ["calculus", "高等数学入门"], ["custom", "其他课程或主题"]] as const;
type IntakeSource = { id: string; title: string; selectable?: boolean; status_detail?: string };
type Option = readonly [string, string, string];

function intakeError(error: unknown, fallback: string): string {
  return (error instanceof Error ? error.message.replace(/^(?:POST|GET) \S+ → \d+(?::\s*)?/, "") : "") || fallback;
}

function ChoiceGroup({ legend, options, values, onChange, optional = false }: {
  legend: string; options: readonly Option[]; values: string[];
  onChange: (values: string[]) => void; optional?: boolean;
}) {
  return <fieldset className="intake-choice-group"><legend>{legend} <span>可多选{optional ? " · 选填" : ""}</span></legend>
    <div className="intake-options">{options.map(([value, title, note]) => <label key={value} className={values.includes(value) ? "is-selected" : ""}>
      <input type="checkbox" checked={values.includes(value)} onChange={() => onChange(values.includes(value) ? values.filter(v => v !== value) : [...values, value])} />
      <span><strong>{title}</strong><small>{note}</small></span>{values.includes(value) && <Check size={17} aria-hidden="true" />}
    </label>)}</div>
  </fieldset>;
}

export function IntroExample({ onPracticed }: { onPracticed: () => void }) {
  const [choice, setChoice] = useState("");
  const [shown, setShown] = useState(false);
  return <section className="intake-demo" aria-label="一分钟学习体验">
    <p className="intake-eyebrow"><Lightbulb size={16} /> 先体验一次怎样学</p>
    <h3>浏览器的“后退”，先回到哪一页？</h3>
    <p>依次打开页面 A → B → C，现在停留在 C。点击一次后退，会回到哪一页？</p>
    <fieldset disabled={shown}><legend className="sr-only">体验题答案</legend><div className="intake-demo-choices">{["A", "B", "C"].map(v => <label key={v}><input type="radio" name="intro-example" checked={choice === v} onChange={() => setChoice(v)} /> 页面 {v}</label>)}</div></fieldset>
    {!shown ? <button type="button" className="intake-secondary" disabled={!choice} onClick={() => { setShown(true); onPracticed(); }}>看看原因 <ArrowRight size={16} /></button> : <div className="intake-feedback" role="status">
      <strong>{choice === "B" ? "对，你抓住了最近访问的顺序。" : "先回到 B。一起看一下变化。"}</strong>
      <p>只考虑连续后退：当前页 C 离开后，最近访问的 B 成为当前页，再后退才是 A。保存历史页面时，可以用“最后放入、最先取出”的栈来理解。</p>
      <p>换一个例子：依次放上红、蓝、绿三本书，先取最上面的一本，会取到绿色的。这也是后进先出。</p>
      <small>这次是有讲解的学习体验，不给你的初始水平加分。正式测评会使用其他题目。</small>
    </div>}
  </section>;
}

export default function LearningIntake({ initial = {}, busy = false, isReplan = false, draftKey, onSubmit, onCancel }: {
  initial?: Partial<StudySurvey>; busy?: boolean; isReplan?: boolean; draftKey?: string;
  onSubmit: (survey: StudySurvey, mode: Assessment["mode"]) => Promise<void> | void;
  onCancel: () => void;
}) {
  const [survey, setSurvey] = useState<StudySurvey>(() => ({ ...DEFAULT_SURVEY, ...initial, goals: initial.goals?.length ? initial.goals : initial.goal ? [initial.goal] : [] }));
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<Assessment["mode"]>("screening");
  const [ready, setReady] = useState(!draftKey);
  const [localBusy, setLocalBusy] = useState(false);
  const [error, setError] = useState("");
  const [course, setCourse] = useState<CourseScope | null>(null);
  const [sources, setSources] = useState<IntakeSource[]>([]);
  const [uploadNote, setUploadNote] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (draftKey) {
      try {
        const draft = JSON.parse(localStorage.getItem(draftKey) || "null");
        if (draft?.version === 2 && draft.survey && Array.isArray(draft.survey.study_days)) {
          const s = draft.survey;
          setSurvey(current => ({ ...current, ...s, intro_practiced: Boolean(current.intro_practiced || s.intro_practiced), goals: Array.isArray(s.goals) ? s.goals.filter((v: string) => GOALS.some(o => o[0] === v)) : [],
            barriers: Array.isArray(s.barriers) ? s.barriers.filter((v: string) => BARRIERS.some(o => o[0] === v)) : [],
            supports: Array.isArray(s.supports) ? s.supports.filter((v: string) => SUPPORTS.some(o => o[0] === v)) : [] }));
          setStep(Math.max(0, Math.min(4, Number(draft.step) || 0)));
          if (["screening", "foundation", "comprehensive"].includes(draft.mode)) setMode(draft.mode);
        }
      } catch { /* An unavailable or stale local draft never blocks learning. */ }
      setReady(true);
    }
  }, [draftKey]);
  useEffect(() => {
    if (ready && draftKey) try { localStorage.setItem(draftKey, JSON.stringify({ version: 2, survey, step, mode })); } catch { /* Server stores the final context. */ }
  }, [draftKey, ready, survey, step, mode]);
  useEffect(() => {
    if (ready) {
      heading.current?.focus({ preventScroll: true });
      heading.current?.scrollIntoView({ block: "nearest" });
    }
  }, [step, ready]);
  useEffect(() => {
    if (!survey.notebook_id) return;
    let cancelled = false;
    void apiGet<{ items: IntakeSource[] }>(`/knowledge/sources?user_id=${USER_ID}&notebook_id=${encodeURIComponent(survey.notebook_id)}`).then(result => {
      if (!cancelled) setSources(result.items || []);
    }).catch(() => { if (!cancelled) setError("暂时无法读取本课程资料，请稍后重试。"); });
    return () => { cancelled = true; };
  }, [survey.notebook_id]);
  const set = <K extends keyof StudySurvey>(key: K, value: StudySurvey[K]) => { setSurvey(s => ({ ...s, [key]: value })); setCourse(null); setError(""); };
  const ensureNotebook = async () => {
    if (survey.notebook_id) return survey.notebook_id;
    if (!survey.course_title?.trim()) throw new Error("请先选择课程或填写学习主题。");
    const notebook = await apiPost<{ id: string }>("/notebooks", { user_id: USER_ID, title: survey.course_title.trim() });
    setSurvey(s => ({ ...s, notebook_id: notebook.id }));
    return notebook.id;
  };
  const upload = async (files: File[]) => {
    if (!files.length) return;
    setLocalBusy(true); setError(""); setCourse(null);
    try {
      const id = await ensureNotebook();
      for (const file of files.slice(0, 6)) {
        setUploadNote(`正在解析 ${file.name}…`);
        const form = new FormData(); form.append("file", file); form.append("user_id", USER_ID); form.append("notebook_id", id); form.append("title", file.name);
        const result = await apiUpload<{ source: IntakeSource }>("/knowledge/upload", form);
        setSources(rows => [...rows.filter(s => s.id !== result.source.id), result.source]);
        if (result.source.selectable) setSurvey(s => ({ ...s, materials_status: "已有资料", source_ids: Array.from(new Set([...(s.source_ids || []), result.source.id])).slice(0, 6) }));
        else throw new Error(result.source.status_detail || "资料尚未解析完成，请重新检查。");
      }
      setUploadNote("解析完成，已选中的资料将用于准备课程范围与起点题。");
    } catch (e) { setError(e instanceof Error ? e.message : "资料上传失败，请重试。"); }
    finally { setLocalBusy(false); }
  };
  const prepare = async () => {
    setLocalBusy(true); setError("");
    try {
      const id = await ensureNotebook();
      const result = await apiPost<CourseScope>(`/notebooks/${id}/learning/prepare`, {
        title: survey.course_title, course_key: survey.course_key, source_ids: survey.source_ids || [], survey: { ...survey, notebook_id: id },
      });
      setCourse(result);
      setSurvey(s => ({ ...s, notebook_id: id, course_title: result.title, course_revision: result.revision, target_kps: result.outline.map(n => n.id) }));
    } catch (e) { setError(intakeError(e, "课程范围暂时没有准备好，请重试。")); }
    finally { setLocalBusy(false); }
  };
  const goals = survey.goals || [];
  const locked = busy || localBusy;
  const validate = () => {
    if (!goals.length || !goals.includes(survey.goal)) return "请至少选择一个目标，并确认当前优先目标。";
    if (!survey.course_title?.trim()) return "请先选择课程或填写学习主题。";
    if (!survey.study_days.length) return "请至少留出一个学习日。";
    if (!Number.isInteger(survey.daily_minutes) || survey.daily_minutes < 8 || survey.daily_minutes > 180) return "每次学习时间请填写 8–180 分钟。";
    const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
    if (survey.target_date && survey.target_date < today) return "目标日期已过去，请调整日期或留空。";
    return "";
  };
  const next = () => {
    const problem = validate();
    if ((step === 0 && !goals.length) || (step === 1 && !survey.course_title?.trim()) || ((step === 3 || step === 4) && problem)) { setError(problem); return; }
    setError(""); setStep(s => Math.min(4, s + 1));
  };
  const submit = async () => {
    const problem = validate(); if (problem) { setError(problem); return; }
    if (!isReplan && !course) { await prepare(); return; }
    if (!isReplan && !survey.target_kps?.length) { setError("请至少保留一个要检查的知识点。"); return; }
    setLocalBusy(true); setError("");
    try { await onSubmit(survey, mode); if (draftKey) try { localStorage.removeItem(draftKey); } catch { /* Optional browser storage. */ } }
    catch (e) { setError(intakeError(e, "保存失败，请重试。你的选择还在这里。")); }
    finally { setLocalBusy(false); }
  };
  if (!ready) return <p role="status">正在恢复你的选择…</p>;
  return <div className="learning-intake" aria-busy={locked}>
    <div className="intake-step-label"><span>{isReplan ? "调整你的学习安排" : "一起找到适合你的起点"}</span><span>{step + 1} / 5</span></div>
    <progress value={step + 1} max={5} aria-label="学习引导进度" />
    <h2 ref={heading} tabIndex={-1}>{TITLES[step]}</h2>
    {localBusy && step === 4 && !course && !isReplan && <p className="intake-response" role="status">正在根据目标与资料准备知识点和题目，通常需要几十秒。准备好后，请先核对范围，再开始作答。</p>}
    <fieldset className="intake-body" disabled={locked}>
      {step === 0 && <>
        <p className="intake-value">带上你的目标和资料。小知会用题目找起点，把讲解、练习和复习安排成你今天就能开始的一步。</p>
        <p className="intake-hint">可以同时选择几个目标。我们会先解决最重要的一项，其余一起纳入安排。</p>
        <ChoiceGroup legend="你的学习目标" options={GOALS} values={goals} onChange={values => {
          const latest = values[values.length - 1];
          const cleaned = latest === "探索学习起点" ? [latest] : values.filter(v => v !== "探索学习起点");
          setSurvey(s => ({ ...s, goals: cleaned, goal: cleaned.includes(s.goal) ? s.goal : cleaned[0] || "掌握课程基础" })); setCourse(null); setError("");
        }} />
        {goals.length > 1 && <label className="intake-field">当前优先解决<select value={survey.goal} onChange={e => set("goal", e.target.value)}>{goals.map(g => <option key={g}>{g}</option>)}</select></label>}
        {!!goals.length && <p className="intake-response" role="status"><Compass size={17} /> 将优先围绕“{survey.goal}”安排；具体难度等你做题后确定。</p>}
      </>}
      {step === 1 && <>
        <p className="intake-hint">你希望优先“{survey.goal}”。下面选定这次的课程和资料，之后的测评、计划与讲解会围绕它们展开。</p>
        {!isReplan ? <>
          <fieldset className="intake-radio-group"><legend>选择课程起点</legend>{COURSES.map(([key, title]) => <label key={key}><input type="radio" name="intake-course" checked={survey.course_key === key} onChange={() => { setSurvey(s => ({ ...s, course_key: key, course_title: key === "custom" ? "" : title, course_revision: "" })); setCourse(null); }} />{title}</label>)}</fieldset>
          <label className="intake-field">课程或学习主题<input maxLength={120} value={survey.course_title || ""} readOnly={survey.course_key !== "custom"} onChange={e => set("course_title", e.target.value)} placeholder="例如：细胞生物学、英语阅读、市场营销" /></label>
          <div className="intake-materials"><label className="intake-upload">上传本次学习资料<input type="file" multiple accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" disabled={locked || !survey.course_title?.trim()} onChange={e => { const files = Array.from(e.target.files || []); e.target.value = ""; void upload(files); }} /></label><small>支持 PDF、Word、文字与图片。可选最多 6 份已解析资料；也可以先使用内置课程。</small>
            {uploadNote && <p role="status">{uploadNote}</p>}
            {sources.map(source => <label key={source.id} className="intake-source"><input type="checkbox" disabled={!source.selectable} checked={!!survey.source_ids?.includes(source.id)} onChange={e => set("source_ids", e.target.checked ? [...(survey.source_ids || []), source.id].slice(0, 6) : survey.source_ids?.filter(id => id !== source.id))} /><span>{source.title}<small>{source.selectable ? "已解析，可用于本次学习" : source.status_detail}</small></span></label>)}
          </div>
        </> : <p className="intake-response">本次调整“{survey.course_title || "当前课程"}”的目标和安排，测评范围及原始作答保留。</p>}
        <label className="intake-field">你现在的学习场景<select value={survey.stage} onChange={e => set("stage", e.target.value)}>{STAGES.map(s => <option key={s}>{s}</option>)}</select></label>
        <label className="intake-field">以前接触过多少？<select value={survey.prior_experience} onChange={e => set("prior_experience", e.target.value)}>{EXPERIENCE.map(s => <option key={s}>{s}</option>)}</select></label>
        <fieldset className="intake-radio-group"><legend>手边有自己的课件或资料吗？</legend>{["暂时没有", "已有资料", "稍后上传"].map(s => <label key={s}><input type="radio" name="intake-materials" checked={survey.materials_status === s} onChange={() => set("materials_status", s as StudySurvey["materials_status"])} />{s}</label>)}</fieldset>
        <p className="intake-response">{survey.source_ids?.length ? `已选 ${survey.source_ids.length} 份资料。我们将列出实际读取的范围，请你核对后再测。` : survey.course_key === "custom" ? "还没有资料：将围绕这个主题生成初步检查，并说明适用范围。" : "将使用所选课程的自编入门讲义和题目。"}</p>
      </>}
      {step === 2 && <>
        <p className="intake-hint">选最贴近最近经历的几项，也可以不选。帮助方式之后随时能改。</p>
        <ChoiceGroup legend="常见的困难" options={BARRIERS} values={survey.barriers || []} onChange={v => set("barriers", v)} optional />
        <ChoiceGroup legend="你希望怎样得到帮助" options={SUPPORTS} values={survey.supports || []} onChange={v => set("supports", v)} optional />
        {!!survey.barriers?.length && <div className="intake-response" role="status">{BARRIERS.filter(o => survey.barriers?.includes(o[0])).map(o => <p key={o[0]}>{o[2]}。</p>)}</div>}
        <label className="intake-field">还有想告诉小知的吗？<input maxLength={120} value={survey.support} onChange={e => set("support", e.target.value)} placeholder="选填，例如：请解释英文术语" /></label>
      </>}
      {step === 3 && <>
        <p className="intake-hint">从能坚持的时间开始。计划会给休息日留白，安排不下的内容会明确列出。</p>
        <label className="intake-field">每个学习日可用时间（分钟）<input type="number" min={8} max={180} value={survey.daily_minutes || ""} onChange={e => set("daily_minutes", Number(e.target.value))} /></label>
        <fieldset className="intake-week"><legend>哪些天方便学习？ <span>可多选</span></legend><div>{["一", "二", "三", "四", "五", "六", "日"].map((d, i) => <label key={d} className={survey.study_days.includes(i + 1) ? "is-selected" : ""}><input type="checkbox" aria-label={`周${d}`} checked={survey.study_days.includes(i + 1)} onChange={e => set("study_days", e.target.checked ? [...survey.study_days, i + 1].sort() : survey.study_days.filter(v => v !== i + 1))} />周{d}</label>)}</div></fieldset>
        <label className="intake-field">{goals.some(g => /考试|408/.test(g)) ? "考试／目标日期（选填）" : "希望完成目标的日期（选填）"}<input type="date" value={survey.target_date || ""} onChange={e => set("target_date", e.target.value || null)} /></label>
        <label className="intake-field">什么时机会比较容易开始？<input maxLength={60} value={survey.study_cue || ""} onChange={e => set("study_cue", e.target.value)} placeholder="选填，例如：晚饭后坐到书桌前" /></label>
        <p className="intake-response">每周 {survey.study_days.length} 天 × {survey.daily_minutes || 0} 分钟。计划会按这个预算拆分任务。</p>
      </>}
      {step === 4 && <>
        <div className="intake-summary"><Sparkles size={20} /><div><strong>优先：{survey.goal}</strong><p>{goals.filter(g => g !== survey.goal).length ? `同时兼顾：${goals.filter(g => g !== survey.goal).join("、")}。` : ""}每周 {survey.study_days.length} 天，每个学习日 {survey.daily_minutes} 分钟。</p><small>你的目标、困难与帮助选择会进入计划和资料，下一步无需重复填写。</small></div></div>
        {!isReplan && <>
          {survey.course_key === "ds_algo" && <details className="intake-example-details"><summary><Play size={15} /> 先体验一次小知怎样讲解（可选）</summary><IntroExample onPracticed={() => set("intro_practiced", true)} /></details>}
          {course ? <section className="intake-outline" aria-label="本次学习范围"><h3>{course.title} · 核对学习范围</h3><p>{course.coverage_note}</p>
            {course.outline.map(node => <label key={node.id}><input type="checkbox" checked={survey.target_kps?.includes(node.id) || false} onChange={e => setSurvey(s => ({ ...s, target_kps: e.target.checked ? [...(s.target_kps || []), node.id] : s.target_kps?.filter(id => id !== node.id) }))} /><span><strong>{node.name}</strong><small>{node.objective}</small></span></label>)}
            {!!course.sources?.length && <details><summary>这次使用了哪些资料？</summary>{course.sources.map(source => <p key={source.id}>{source.title}：读取 {source.sampled_chunks}/{source.total_chunks} 个解析片段；{source.location_kind} {source.locations.join("、")}。</p>)}</details>}
            <small>{course.boundary}</small></section> : <p className="intake-response">下一步先准备“{survey.course_title}”的知识点范围，供你选择和核对；确认之后才开始作答。</p>}
          <fieldset className="intake-mode"><legend>这次想了解多少？</legend>{[
            ["screening", "先找学习起点", "最多 12 题 · 先检查至多 4 个知识点，可暂停"],
            ...(survey.course_key === "ds_algo" && !survey.source_ids?.length ? [["foundation", "检查入门基础", "通常 18 题，跳过时最多 22 题 · 可暂停续答"]] : []),
            ["comprehensive", "完成所选范围摸底", course ? `${Math.min(48, (survey.target_kps?.length || course.outline.length) * 3)} 题左右 · 分模块检查，可暂停续答` : "按核对后的知识点范围出题，可分次完成"],
          ].map(([v, title, note]) => <label key={v} className={mode === v ? "is-selected" : ""}><input type="radio" name="intake-mode" checked={mode === v} onChange={() => setMode(v as Assessment["mode"])} /><span><strong>{title}{v === "screening" && <em>推荐</em>}</strong><small>{note}</small></span></label>)}</fieldset>
          <p className="intake-hint">独立作答，没有单题倒计时。可以选择“还不会”或暂停；完成后会解释依据，并准备第一项任务。</p>
        </>}
      </>}
    </fieldset>
    {error && <p className="intake-error" role="alert">{error}</p>}
    <div className="intake-footer"><button type="button" className="intake-secondary" disabled={locked} onClick={() => step ? (setStep(s => s - 1), setError("")) : onCancel()}><ArrowLeft size={16} />{step ? "上一步" : "返回"}</button>
      <button type="button" className="intake-primary" disabled={locked} onClick={() => step < 4 ? next() : void submit()}>{locked ? (step === 4 && !course ? "正在准备课程范围…" : "正在保存…") : step < 4 ? "继续" : isReplan ? "保存并重新安排" : course ? "确认范围，开始独立作答" : "生成并核对学习范围"}<ArrowRight size={18} /></button></div>
    {draftKey && <p className="intake-draft-note">当前选择会保存在本浏览器，回来可以继续。</p>}
  </div>;
}
