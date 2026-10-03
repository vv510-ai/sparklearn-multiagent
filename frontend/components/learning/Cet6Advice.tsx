"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Check, RefreshCw } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { cet6Labels } from "@/lib/cet6";
import type { AdviceAction, AdviceSection, Cet6AdviceData } from "@/lib/cet6-advice";
import { readingDate, readingError } from "@/lib/reading";
import "./cet6-advice.css";

const questions = { preparation: "上次考试前，你大致怎样准备？", reading_completion: "上次考试的阅读有没有做完？" };

export default function Cet6Advice({ notebookId, autoRevision, onEdit, onStart }: {
  notebookId: string; autoRevision: number | null; onEdit: () => void; onStart: (action: AdviceAction) => void;
}) {
  const base = `/notebooks/${notebookId}/cet6/advice`;
  const [data, setData] = useState<Cet6AdviceData | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const active = useRef(true), heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const saved = await apiGet<Cet6AdviceData>(base);
        if (cancelled) return;
        setData(saved); setError("");
        if (autoRevision !== null) {
          setBusy(true);
          const next = await apiPost<Cet6AdviceData>(base, { profile_revision: autoRevision });
          if (!cancelled) setData(next);
        }
      } catch (e) { if (!cancelled) setError(readingError(e)); }
      finally { if (!cancelled) setBusy(false); }
    })();
    heading.current?.focus();
    return () => { cancelled = true; };
  }, [base, autoRevision]);

  useEffect(() => {
    if (data?.status !== "running") return;
    let cancelled = false, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await apiGet<Cet6AdviceData>(base);
        if (cancelled) return;
        setData(next); setError("");
        if (next.status !== "running") return;
      } catch { if (!cancelled) setError("暂时无法读取生成进度，正在重连。已填信息保留，你也可以稍后回来查看。"); }
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 1500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [base, data?.status]);

  const generate = async () => {
    if (busy || data?.status === "running") return;
    setBusy(true); setError("");
    try {
      const current = await apiGet<Cet6AdviceData>(base);
      if (!active.current) return;
      if (!current.profile_revision) { onEdit(); return; }
      const next = await apiPost<Cet6AdviceData>(base, { profile_revision: current.profile_revision });
      if (active.current) setData(next);
    } catch (e) { if (active.current) setError(readingError(e)); }
    finally { if (active.current) setBusy(false); }
  };
  const running = data?.status === "running" || busy;
  const ready = data?.status === "ready";
  const primary = data?.actions.find(a => a.kind === data.content.priority_kind) || data?.actions[0];

  return <article className="cet6-advice" aria-label="我的六级备考建议">
    <header className="advice-heading"><span className="cet6-eyebrow">从你的情况出发</span><h2 ref={heading} tabIndex={-1}>你的六级备考建议</h2><p>先看清起点，再安排下一步。这里的建议会随你补充的情况调整。</p></header>
    {error && <div role="alert" className="cet6-error">{error}<button disabled={running} onClick={() => void generate()}>重新读取并生成</button></div>}
    {!data ? <p role="status">正在读取你的学习情况…</p> : <>
      {data.stale && <div className="advice-notice" role="status"><strong>你的学习情况已更新</strong><p>下面保留的是上一份建议。按最新情况生成后，新的安排会显示在这里。</p><button className="secondary-action" disabled={running} onClick={() => void generate()}>按最新情况更新建议</button></div>}
      <section className="advice-intake" aria-label="建议依据">
        <div className="advice-intake-title"><h3>你填写的情况</h3><button className="cet6-link-button" onClick={onEdit}>调整我的情况</button></div>
        {data.input.goal && <p className="advice-goal">“{data.input.goal}”</p>}
        <dl className="advice-constraints"><div><dt>每天可用</dt><dd>{data.input.daily_minutes} 分钟</dd></div><div><dt>目标分数</dt><dd>{data.input.target_score ?? "暂未设置"}{data.input.target_score !== null ? " 分" : ""}</dd></div><div><dt>考试日期</dt><dd>{data.input.exam_date || "暂未设置"}</dd></div></dl>
        <dl className="advice-scores">{([["total_score", "历史总分"], ["listening_score", "听力"], ["reading_score", "阅读"], ["writing_translation_score", "写作与翻译合计"]] as const).map(([k, label]) => <div key={k}><dt>{label}</dt><dd>{data.input[k] ?? "未填"}</dd></div>)}</dl>
        {data.facts.score_gap !== null && <p className="cet6-muted">{data.facts.score_gap > 0 ? `目标比历史总分高 ${data.facts.score_gap} 分。这是成绩差距，不是提分预测。` : "历史总分已达到你填写的目标，可以结合实际练习调整下一阶段重点。"}</p>}
        <p className="cet6-muted">{data.facts.basis}。分项成绩按<a href={data.sources[0].url} target="_blank" rel="noreferrer">官方分数解释 ↗</a>参考，写作与翻译合计分不能拆成两项诊断。</p>
      </section>
      {running && <section className="advice-loading" role="status" aria-live="polite"><RefreshCw size={20} className="advice-spin"/><div><strong>已保存，正在为你整理备考建议</strong><p>正在结合你的目标、时间和历史成绩整理方法与安排。你可以先开始学习，稍后从“备考建议”回来查看。</p></div></section>}
      {data.status === "empty" && <div className="advice-notice"><p>填写学习情况后，小知会为你整理完整的备考建议。成绩和日期都可以留空。</p><button className="primary-action" onClick={() => void generate()} disabled={running}>生成我的备考建议</button></div>}
      {(data.status === "failed" || data.status === "unavailable") && <div className="advice-notice" role="status"><strong>基础安排已保留</strong><p>{data.message}</p><button className="secondary-action" disabled={running} onClick={() => void generate()}>重试 AI 建议</button></div>}
      {!running && <>
        <section className="advice-summary" aria-label={ready ? "小知的初步建议" : "基础起步建议"}>
          <span className="cet6-eyebrow">{ready ? "小知的初步建议" : "基础起步建议 · 尚未完成 AI 分析"}</span><p className="advice-lead">{data.content.summary}</p>
          <h3>先从{cet6Labels[data.content.priority_kind]}开始</h3><p>{data.content.rationale}</p><p className="advice-boundary">{data.content.uncertainty}</p>
          {primary && <div className="cet6-actions"><button className="primary-action" onClick={() => onStart(primary)}>{primary.label}<ArrowRight size={17}/></button><a className="advice-inline-link" href="#advice-week">先看近期安排</a></div>}
        </section>
        <nav className="advice-toc" aria-label="备考建议目录">{data.content.sections.map(s => <a key={s.kind} href={`#advice-${s.kind}`}>{cet6Labels[s.kind]}怎么练</a>)}<a href="#advice-week">近期安排</a></nav>
        {data.content.sections.map(s => <Method key={s.kind} section={s} action={data.actions.find(a => a.kind === s.kind)} onStart={onStart}/>) }
        <section className="advice-section" id="advice-week" aria-label="近期学习安排">
          <span className="cet6-eyebrow">让方法落实到时间里</span><h3>{data.week.length < 7 ? "考试前的起步安排" : "从开始学习算起的第一周"}</h3>
          <p>{data.content.week_note}</p>
          {data.facts.date_state === "missing" && <p className="advice-boundary">考试日期尚未填写，先安排第一周；补充日期后再调整备考阶段。</p>}
          {data.facts.date_state === "past" && <p className="advice-boundary">你填写的考试日期已经过去。请调整日期；下面暂按新一周的起步学习安排。</p>}
          {data.facts.date_state === "today" && <p className="advice-boundary">你填写的考试日期是今天。按实际考试时间决定是否学习，下面的任务可以跳过，不必临时加量。</p>}
          <div className="advice-week">{data.week.map(day => <section className="advice-day" key={day.day}><div><span>第 {day.day} 天</span><strong>{cet6Labels[day.kind]}为主</strong><small>共 {day.minutes} 分钟</small></div><ul>{day.tasks.map((t, i) => <li key={i}><span>{t.title}</span><strong>{t.minutes} 分钟</strong></li>)}</ul></section>)}</div>
          <p className="cet6-muted">时间包含做题与核对。只完成当前时间内的一小段，原卷可暂停续做；完整模拟需要另外留出完整时段。</p>
          <div className="advice-stages">{data.content.stages.map((s, i) => <section key={i}><h4>{s.title}</h4><p>{s.text}</p></section>)}</div>
        </section>
        {!!data.content.followup_keys.length && <section className="advice-section advice-followup"><h3>补充一点情况，建议会更贴近你</h3><ul>{data.content.followup_keys.map(k => <li key={k}>{questions[k]}</li>)}</ul><p className="cet6-muted">这些问题可以晚点回答，不影响你现在开始学习。</p><button className="secondary-action" onClick={onEdit}>补充备考情况</button></section>}
      </>}
      <section className="advice-next" aria-label="开始学习"><BookOpen size={23}/><div><h3>从一次实际学习开始</h3><p>先独立尝试，留下卡点，再用反馈调整下一步。</p></div><div className="cet6-actions">{data.actions.slice(0, 3).map(a => <button key={a.kind} className="secondary-action" onClick={() => onStart(a)}>{a.label}<ArrowRight size={15}/></button>)}</div></section>
      <details className="cet6-source"><summary>建议依据与生成信息</summary>{data.sources.map(s => <p key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.title} ↗</a><br/>{s.supports}<br/>资料核验日期：{s.checked_on}</p>)}<p>考试事实由上述来源支持，针对你的训练方法和安排属于学习建议。真题入口按本站已开放范围提供，材料来源见练习页面。</p><p>{ready ? `AI 建议 · ${data.model || "已连接的学习模型"} · ${readingDate(data.generated_at || "")}` : "当前内容为基础安排"}。这里只使用填写的信息，不代表官方评分或能力测评。</p></details>
      {data.previous && <details className="cet6-source advice-previous"><summary>查看上一版建议</summary><p>当时每天可用 {data.previous.input.daily_minutes} 分钟 · {readingDate(data.previous.generated_at || "")}</p><p>{data.previous.content.summary}</p>{data.previous.content.sections.map(s => <section key={s.kind}><h4>{s.title}</h4><p>{s.analysis}</p><ol>{s.steps.map((step, i) => <li key={i}>{step}</li>)}</ol><p>{s.check}</p></section>)}</details>}
    </>}
  </article>;
}

function Method({ section, action, onStart }: { section: AdviceSection; action?: AdviceAction; onStart: (a: AdviceAction) => void }) {
  return <section className="advice-section" id={`advice-${section.kind}`} aria-label={`${cet6Labels[section.kind]}学习方法`}>
    <span className="cet6-eyebrow">{cet6Labels[section.kind]}</span><h3>{section.title}</h3><p>{section.analysis}</p>
    <ol className="advice-steps">{section.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
    <div className="advice-check"><Check size={17}/><p><strong>怎样检查：</strong>{section.check}</p></div>
    {action && <button className="advice-practice-link" onClick={() => onStart(action)}>{action.label}<ArrowRight size={15}/></button>}
  </section>;
}
