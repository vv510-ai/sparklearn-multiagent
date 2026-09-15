"use client";

import { ArrowRight, BookOpen, Compass, LogOut, Play, Sparkles, Target } from "lucide-react";
import { useEffect, useState } from "react";
import CinematicBackground from "@/components/ui/CinematicBackground";
import type { AuthUser } from "@/components/auth/AuthGate";
import type { Assessment, StudySurvey } from "@/lib/assessment";
import LearningIntake, { IntroExample } from "./LearningIntake";

export default function OnboardingGate({ user, onComplete, onSkip, onLogout }: {
  user: AuthUser;
  onComplete: (survey: StudySurvey, mode: Assessment["mode"]) => Promise<void>;
  onSkip: (introPracticed: boolean) => Promise<void>;
  onLogout: () => void;
}) {
  const [started, setStarted] = useState(false);
  const [example, setExample] = useState(false);
  const [practiced, setPracticed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const draftKey = `sparklearn-intake-v2:${user.id}`;
  useEffect(() => {
    try { if (localStorage.getItem(draftKey)) setStarted(true); } catch { /* Drafts are optional. */ }
  }, [draftKey]);
  const skip = async () => {
    setBusy(true); setError("");
    try {
      let exposed = practiced;
      try { exposed ||= Boolean(JSON.parse(localStorage.getItem(draftKey) || "null")?.survey?.intro_practiced); } catch { /* Optional draft. */ }
      await onSkip(exposed);
    } catch (e) { setError(e instanceof Error ? e.message : "暂时无法进入，请重试。"); }
    finally { setBusy(false); }
  };
  return <main className="onboarding-shell learning-gate-shell">
    <CinematicBackground />
    <div className="onboarding-shade" />
    <div className="onboarding-frame">
      <nav className="onboarding-nav"><div><Sparkles size={23} /><strong>知行循证<span>LearnLoop</span></strong></div><div><span>{user.name}</span><button type="button" aria-label="退出登录" onClick={onLogout} disabled={busy}><LogOut size={19} /></button></div></nav>
      <div className="onboarding-layout">
        <section className="onboarding-story">
          <p className="onboarding-kicker">数据结构与算法 · 你的学习伙伴</p>
          <h1>从卡住的那一步，<br /><span>开始真正学会。</span></h1>
          <p>先了解你想解决什么，用题目找到起点，再把讲解、练习和复习排进你真实的生活。</p>
          <ol><li><Compass size={20} /><div><strong>说说你的目标</strong><span>多选你的需要，明确当前优先项</span></div></li><li><Target size={20} /><div><strong>用题目找到起点</strong><span>从短测开始，需要时再深入</span></div></li><li><BookOpen size={20} /><div><strong>带着计划开始学习</strong><span>第一项任务、对应资料一起准备好</span></div></li></ol>
          <small>你可以调整节奏、暂停测评，或随时换一种帮助方式。</small>
        </section>
        <section className="onboarding-card" aria-label="学习起点引导">
          {started ? <LearningIntake initial={{ intro_practiced: practiced }} draftKey={draftKey} onCancel={() => setStarted(false)} onSubmit={onComplete} /> : <div className="onboarding-welcome">
            <p className="intake-eyebrow"><Sparkles size={17} /> 欢迎来到知行循证</p>
            <h2>先找到适合你的第一步</h2>
            <p>不确定从哪学，或者看懂了却做不出？告诉我们你的目标和困难，接下来用实际题目一起确认。</p>
            <div className="onboarding-preview"><span>你会得到</span><strong>一份有作答依据的起点建议</strong><p>能完成的学习计划 · 针对卡点的资料 · 马上可开始的任务</p></div>
            <button type="button" className="intake-primary onboarding-start" disabled={busy} onClick={() => setStarted(true)}>找到我的学习起点 <ArrowRight size={20} /></button>
            <button type="button" className="intake-secondary onboarding-example" disabled={busy} aria-expanded={example} onClick={() => setExample(v => !v)}><Play size={17} />先体验一次讲解</button>
            {example && <IntroExample onPracticed={() => setPracticed(true)} />}
            <button type="button" className="onboarding-skip" disabled={busy} onClick={() => void skip()}>{busy ? "正在进入…" : "已有明确方向，直接进入"}</button>
            <small>默认起点短测最多 12 题；也可以选择分次完成全面摸底。</small>
            {error && <p className="intake-error" role="alert">{error}</p>}
          </div>}
        </section>
      </div>
    </div>
  </main>;
}
