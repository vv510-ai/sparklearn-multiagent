"use client";

import { ArrowLeft, ArrowRight, Check, Compass, Lightbulb, Play, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Assessment, StudySurvey } from "@/lib/assessment";

export const DEFAULT_SURVEY: StudySurvey = {
  daily_minutes: 20, study_days: [1, 2, 3, 4, 5], goal: "掌握课程基础",
  goals: [], barriers: [], supports: [], stage: "大学课程", prior_experience: "不确定",
  pressure: "skip", study_habit: "skip", support: "", target_date: null,
  study_cue: "", materials_status: "暂时没有", intro_practiced: false,
};

const GOALS = [
  ["掌握课程基础", "跟上课程，补齐基础", "把概念和例题一步步学明白"],
  ["准备课程考试", "准备课程考试", "围绕考点、题型和剩余时间安排"],
  ["考研 408 复习", "准备考研 408", "先查基础，再做综合辨析"],
  ["竞赛与算法练习", "提升算法解题能力", "多比较解法，练习迁移与推理"],
  ["编程项目应用", "用于项目或技术面试", "连接代码、应用场景与边界条件"],
  ["兴趣理解", "出于兴趣，系统了解", "按自己的节奏探索"],
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
const TITLES = ["这次来，你最希望解决什么？", "从你的学习经历开始", "哪些地方需要我们多帮一步？", "给学习留一段真实的时间", "你的起点探索，准备好了"];
type Option = readonly [string, string, string];

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
  const set = <K extends keyof StudySurvey>(key: K, value: StudySurvey[K]) => { setSurvey(s => ({ ...s, [key]: value })); setError(""); };
  const goals = survey.goals || [];
  const locked = busy || localBusy;
  const validate = () => {
    if (!goals.length || !goals.includes(survey.goal)) return "请至少选择一个目标，并确认当前优先目标。";
    if (!survey.study_days.length) return "请至少留出一个学习日。";
    if (!Number.isInteger(survey.daily_minutes) || survey.daily_minutes < 8 || survey.daily_minutes > 180) return "每次学习时间请填写 8–180 分钟。";
    const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
    if (survey.target_date && survey.target_date < today) return "目标日期已过去，请调整日期或留空。";
    return "";
  };
  const next = () => {
    const problem = validate();
    if ((step === 0 && !goals.length) || ((step === 3 || step === 4) && problem)) { setError(problem); return; }
    setError(""); setStep(s => Math.min(4, s + 1));
  };
  const submit = async () => {
    const problem = validate(); if (problem) { setError(problem); return; }
    setLocalBusy(true); setError("");
    try { await onSubmit(survey, mode); if (draftKey) try { localStorage.removeItem(draftKey); } catch { /* Optional browser storage. */ } }
    catch (e) { setError(e instanceof Error ? e.message : "保存失败，请重试。你的选择还在这里。"); }
    finally { setLocalBusy(false); }
  };
  if (!ready) return <p role="status">正在恢复你的选择…</p>;
  return <div className="learning-intake" aria-busy={locked}>
    <div className="intake-step-label"><span>{isReplan ? "调整你的学习安排" : "一起找到适合你的起点"}</span><span>{step + 1} / 5</span></div>
    <progress value={step + 1} max={5} aria-label="学习引导进度" />
    <h2 ref={heading} tabIndex={-1}>{TITLES[step]}</h2>
    <fieldset className="intake-body" disabled={locked}>
      {step === 0 && <>
        <p className="intake-hint">可以同时选择几个目标。我们会先解决最重要的一项，其余一起纳入安排。</p>
        <ChoiceGroup legend="你的学习目标" options={GOALS} values={goals} onChange={values => {
          const latest = values[values.length - 1];
          const cleaned = latest === "探索学习起点" ? [latest] : values.filter(v => v !== "探索学习起点");
          setSurvey(s => ({ ...s, goals: cleaned, goal: cleaned.includes(s.goal) ? s.goal : cleaned[0] || "掌握课程基础" })); setError("");
        }} />
        {goals.length > 1 && <label className="intake-field">当前优先解决<select value={survey.goal} onChange={e => set("goal", e.target.value)}>{goals.map(g => <option key={g}>{g}</option>)}</select></label>}
        {!!goals.length && <p className="intake-response" role="status"><Compass size={17} /> 将优先围绕“{survey.goal}”安排；具体难度等你做题后确定。</p>}
      </>}
      {step === 1 && <>
        <p className="intake-hint">这些信息用来调整课程背景与解释方式。实际起点由题目确认。</p>
        <label className="intake-field">你现在的学习场景<select value={survey.stage} onChange={e => set("stage", e.target.value)}>{STAGES.map(s => <option key={s}>{s}</option>)}</select></label>
        <label className="intake-field">以前接触过多少？<select value={survey.prior_experience} onChange={e => set("prior_experience", e.target.value)}>{EXPERIENCE.map(s => <option key={s}>{s}</option>)}</select></label>
        <fieldset className="intake-radio-group"><legend>手边有自己的课件或资料吗？</legend>{["暂时没有", "已有资料", "稍后上传"].map(s => <label key={s}><input type="radio" name="intake-materials" checked={survey.materials_status === s} onChange={() => set("materials_status", s as StudySurvey["materials_status"])} />{s}</label>)}</fieldset>
        <p className="intake-response">{survey.materials_status === "暂时没有" ? "我们已经准备了数据结构与算法的课程讲义和练习，可以直接开始。" : "进入学习后可以上传课件。起点测评先检查本课程基础，上传后再对齐你的具体范围。"}</p>
      </>}
      {step === 2 && <>
        <p className="intake-hint">选最贴近最近经历的几项，也可以不选。帮助方式之后随时能改。</p>
        <ChoiceGroup legend="常见的困难" options={BARRIERS} values={survey.barriers || []} onChange={v => set("barriers", v)} optional />
        <ChoiceGroup legend="你希望怎样得到帮助" options={SUPPORTS} values={survey.supports || []} onChange={v => set("supports", v)} optional />
        {!!survey.barriers?.length && <div className="intake-response" role="status">{BARRIERS.filter(o => survey.barriers?.includes(o[0])).map(o => <p key={o[0]}>{o[2]}。</p>)}</div>}
        <label className="intake-field">还有想告诉学伴的吗？<input maxLength={120} value={survey.support} onChange={e => set("support", e.target.value)} placeholder="选填，例如：请解释英文术语" /></label>
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
          <details className="intake-example-details"><summary><Play size={15} /> 先体验一次学伴怎样讲解（可选）</summary><IntroExample onPracticed={() => set("intro_practiced", true)} /></details>
          <fieldset className="intake-mode"><legend>这次想了解多少？</legend>{[
            ["screening", "先找学习起点", "最多 12 题 · 先检查 4 个关键知识点，其他内容之后补测"],
            ["foundation", "检查入门基础", "通常 18 题，跳过时最多 22 题 · 可暂停续答"],
            ["comprehensive", "课程全面摸底", "最多 48 题 · 覆盖 16 个知识点，可分次完成"],
          ].map(([v, title, note]) => <label key={v} className={mode === v ? "is-selected" : ""}><input type="radio" name="intake-mode" checked={mode === v} onChange={() => setMode(v as Assessment["mode"])} /><span><strong>{title}{v === "screening" && <em>推荐</em>}</strong><small>{note}</small></span></label>)}</fieldset>
          <p className="intake-hint">独立作答，没有单题倒计时。可以选择“还不会”或暂停；完成后会解释依据，并准备第一项任务。</p>
        </>}
      </>}
    </fieldset>
    {error && <p className="intake-error" role="alert">{error}</p>}
    <div className="intake-footer"><button type="button" className="intake-secondary" disabled={locked} onClick={() => step ? (setStep(s => s - 1), setError("")) : onCancel()}><ArrowLeft size={16} />{step ? "上一步" : "返回"}</button>
      <button type="button" className="intake-primary" disabled={locked} onClick={() => step < 4 ? next() : void submit()}>{locked ? "正在保存…" : step < 4 ? "继续" : isReplan ? "保存并重新安排" : "开始独立作答"}<ArrowRight size={18} /></button></div>
    {draftKey && <p className="intake-draft-note">当前选择会保存在本浏览器，回来可以继续。</p>}
  </div>;
}
