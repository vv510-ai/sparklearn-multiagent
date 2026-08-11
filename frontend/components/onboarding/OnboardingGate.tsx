"use client";

import {
  ArrowRight,
  BookOpen,
  BrainCircuit,
  Check,
  Clock3,
  FileUp,
  Gauge,
  LogOut,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";
import CinematicBackground from "@/components/ui/CinematicBackground";
import type { AuthUser } from "@/components/auth/AuthGate";

export type OnboardingAnswers = {
  topic: string;
  current_level: string;
  goal: string;
  weekly_minutes: number;
  frequency: string;
  style: string;
  materials_status: string;
};

export type QuickStartKey = "recommended" | "diagnostic" | "upload" | "example";

const HERO_LEAD = Array.from("让世界享受");
const HERO_ACCENT = Array.from("学习");
const HERO_TAIL = Array.from("的乐趣");

const STEPS = [
  { key: "topic", label: "学习方向", title: "你现在最想学什么？", hint: "选一个最接近的方向，之后还可以修改。" },
  { key: "current_level", label: "当前基础", title: "你大概学到哪一步了？", hint: "不用考试，凭感觉选就好。" },
  { key: "goal", label: "学习目的", title: "这段时间最想得到什么？", hint: "目标会影响推荐的顺序和练习。" },
  { key: "weekly_minutes", label: "投入时间", title: "每周大概能留出多少时间？", hint: "我们会把任务拆成能完成的小段。" },
  { key: "style", label: "讲解方式", title: "你更喜欢怎样学？", hint: "选你愿意坚持的方式，不是能力测试。" },
  { key: "materials_status", label: "已有资料", title: "手边已经有学习资料吗？", hint: "没有也没关系，推荐内容可以直接开始。" },
] as const;

const OPTIONS: Record<string, { value: string; label: string; note: string }[]> = {
  topic: [
    { value: "从基础开始", label: "从基础开始", note: "复杂度、线性表、栈和队列" },
    { value: "排序与查找", label: "排序与查找", note: "基础排序、哈希和高级排序" },
    { value: "树与图", label: "树与图", note: "二叉树、图遍历和最短路径" },
    { value: "动态规划", label: "动态规划", note: "从递归、状态到转移" },
    { value: "还没想好", label: "还没想好", note: "先做一个轻量测试再决定" },
  ],
  current_level: [
    { value: "刚开始接触", label: "刚开始接触", note: "希望有人带着从头学" },
    { value: "学过一些概念", label: "学过一些概念", note: "看过课本，但容易混淆" },
    { value: "能做基础题", label: "能做基础题", note: "想练更有挑战的题" },
    { value: "能独立解决综合题", label: "能解决综合题", note: "希望直接攻克难点" },
    { value: "不确定", label: "不太确定", note: "先测一下再安排" },
  ],
  goal: [
    { value: "应试", label: "考试 / 作业", note: "按重点和常见题型推进" },
    { value: "竞赛", label: "竞赛 / 刷题", note: "多练思路和综合应用" },
    { value: "工程实践", label: "做项目", note: "多看代码和真实场景" },
    { value: "兴趣", label: "兴趣理解", note: "按自己的节奏慢慢学" },
  ],
  weekly_minutes: [
    { value: "60", label: "每周 1 小时", note: "每天约 8 分钟" },
    { value: "140", label: "每周 2 小时", note: "每天约 20 分钟" },
    { value: "210", label: "每周 3 小时", note: "每天约 30 分钟" },
    { value: "420", label: "每周 6 小时以上", note: "适合连续推进" },
  ],
  style: [
    { value: "图示和例子", label: "图示和例子", note: "先看清楚，再记住" },
    { value: "讲解和文字", label: "讲解和文字", note: "一步一步读懂原因" },
    { value: "边写代码边学", label: "边写代码边学", note: "边试边理解" },
    { value: "先做题再讲解", label: "先做题再讲解", note: "从不会的地方开始补" },
  ],
  materials_status: [
    { value: "已有资料", label: "有自己的资料", note: "上传后会围绕资料回答" },
    { value: "暂时没有", label: "暂时没有", note: "先从推荐课本开始" },
    { value: "稍后上传", label: "有，稍后上传", note: "先学习，之后随时补充" },
  ],
};

const DEFAULT_ANSWERS: OnboardingAnswers = {
  topic: "",
  current_level: "",
  goal: "",
  weekly_minutes: 140,
  frequency: "每天",
  style: "",
  materials_status: "",
};

export default function OnboardingGate({
  user,
  onComplete,
  onQuickStart,
  onLogout,
}: {
  user: AuthUser;
  onComplete: (answers: OnboardingAnswers, skipped: boolean) => Promise<void> | void;
  onQuickStart: (key: QuickStartKey) => Promise<void> | void;
  onLogout: () => void;
}) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<OnboardingAnswers>(DEFAULT_ANSWERS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const current = STEPS[step];
  const selected = String(answers[current.key as keyof OnboardingAnswers] ?? "");
  const progress = Math.round(((step + 1) / STEPS.length) * 100);
  const canContinue = Boolean(selected);
  const options = OPTIONS[current.key] || [];

  const quickCards = useMemo(() => [
    { key: "recommended" as const, icon: BookOpen, title: "从推荐课本开始", note: "直接打开课程内容，边学边调整" },
    { key: "diagnostic" as const, icon: Gauge, title: "先测一下我的水平", note: "用几道小题找到合适起点" },
    { key: "upload" as const, icon: FileUp, title: "上传自己的资料", note: "让回答围绕你的资料展开" },
    { key: "example" as const, icon: BrainCircuit, title: "看看我能问什么", note: "从二叉树、排序或动态规划开始" },
  ], []);

  const setValue = (value: string) => {
    setAnswers((currentAnswers) => ({
      ...currentAnswers,
      [current.key]: current.key === "weekly_minutes" ? Number(value) : value,
    }));
    setError("");
  };

  const finish = async (skipped: boolean) => {
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await onComplete(skipped ? DEFAULT_ANSWERS : answers, skipped);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setSubmitting(false);
    }
  };

  const quickStart = async (key: QuickStartKey) => {
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await onQuickStart(key);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setSubmitting(false);
    }
  };

  const next = () => {
    if (!canContinue) {
      setError("选一个最接近的答案就可以继续，也可以直接跳过。");
      return;
    }
    if (step === STEPS.length - 1) {
      void finish(false);
      return;
    }
    setStep((value) => value + 1);
  };

  return (
    <main className="learning-gate-shell relative min-h-dvh overflow-hidden text-white" aria-busy={submitting}>
      <CinematicBackground />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_30%,rgba(50,178,137,0.17),transparent_34%),linear-gradient(120deg,rgba(3,32,44,0.92),rgba(3,29,42,0.62))]" />
      <div className="relative z-10 mx-auto flex min-h-dvh w-full max-w-7xl flex-col px-4 py-5 sm:px-8 sm:py-6">
        <nav className="learning-gate-nav liquid-glass glass-readable flex items-center justify-between rounded-full px-5 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-white text-[#0F6B50]"><Sparkles size={15} /></span>
            <span className="text-xl text-white" style={{ fontFamily: "var(--font-display)" }}>SparkLearn<sup className="ml-0.5 text-[9px]">®</sup></span>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block"><div className="max-w-32 truncate text-sm font-semibold text-white">{user.name}</div><div className="max-w-40 truncate text-[10px] text-white/50">{user.email}</div></div>
            <button type="button" onClick={onLogout} disabled={submitting} className="liquid-glass grid h-10 w-10 place-items-center rounded-full text-white/75 transition hover:text-white disabled:opacity-50" aria-label="退出登录" title="退出登录"><LogOut size={17} /></button>
          </div>
        </nav>

        <div className="grid flex-1 items-center gap-8 py-8 lg:grid-cols-[minmax(0,1fr)_minmax(360px,0.9fr)] lg:gap-14">
          <section className="hidden max-w-xl lg:block">
            <h1 className="auth-hero-title" aria-label="让世界享受学习的乐趣">
              <span className="auth-hero-visual" aria-hidden="true">
                <span className="auth-hero-word">
                  {HERO_LEAD.map((character, index) => (
                    <span key={`lead-${character}-${index}`} className="auth-hero-character" style={{ animationDelay: `${180 + index * 72}ms` }}>{character}</span>
                  ))}
                </span>
                <span className="auth-hero-accent">
                  {HERO_ACCENT.map((character, index) => (
                    <span key={`accent-${character}-${index}`} className="auth-hero-character" style={{ animationDelay: `${180 + (HERO_LEAD.length + index) * 72}ms` }}>{character}</span>
                  ))}
                </span>
                <span className="auth-hero-word">
                  {HERO_TAIL.map((character, index) => (
                    <span key={`tail-${character}-${index}`} className="auth-hero-character" style={{ animationDelay: `${180 + (HERO_LEAD.length + HERO_ACCENT.length + index) * 72}ms` }}>{character}</span>
                  ))}
                </span>
                <span className="auth-hero-cursor" />
              </span>
            </h1>
          </section>

          <section className="w-full max-w-xl justify-self-center rounded-[28px] border border-white/20 bg-white/[0.13] p-2 shadow-[0_28px_90px_rgba(0,12,22,0.35)] backdrop-blur-2xl">
            <div className="rounded-[22px] bg-[#F8FAF8] p-5 text-[#182119] sm:p-7">
              <div className="flex items-center justify-between gap-4">
                <div><p className="text-xs font-bold tracking-[0.14em] text-[#0F6B50]">开始前的小了解</p><h2 className="mt-2 text-2xl font-bold tracking-tight">{current.title}</h2><p className="mt-1 text-sm text-[#6F776F]">{current.hint}</p></div>
                <div className="shrink-0 text-right"><span className="block text-xs font-semibold text-[#788078]">{step + 1} / {STEPS.length}</span><div className="mt-2 h-1.5 w-16 overflow-hidden rounded-full bg-[#DDE8E0]"><div className="h-full rounded-full bg-[#1E8A5F] transition-all" style={{ width: `${progress}%` }} /></div></div>
              </div>

              <div className="mt-6 grid gap-2.5 sm:grid-cols-2">
                {options.map((option) => {
                  const active = selected === option.value;
                  return <button key={option.value} type="button" onClick={() => setValue(option.value)} className={`group min-h-16 rounded-2xl border px-4 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-[#1E8A5F]/30 ${active ? "border-[#1E8A5F] bg-[#E8F4ED]" : "border-[#DDE5DE] bg-white hover:border-[#A8C6B3] hover:bg-[#F4F8F4]"}`} aria-pressed={active}><span className="flex items-start gap-3"><span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border ${active ? "border-[#1E8A5F] bg-[#1E8A5F] text-white" : "border-[#C7D2C9] text-transparent"}`}><Check size={12} strokeWidth={3} /></span><span><strong className="block text-sm text-[#253229]">{option.label}</strong><span className="mt-1 block text-xs leading-5 text-[#7A857C]">{option.note}</span></span></span></button>;
                })}
              </div>
              {error && <p role="alert" className="mt-3 rounded-xl bg-[#FFF3ED] px-3 py-2.5 text-xs leading-5 text-[#A0442C]">{error}</p>}

              <div className="mt-6 flex items-center justify-between gap-3">
                <button type="button" onClick={() => void finish(true)} disabled={submitting} className="min-h-11 rounded-xl px-3 text-sm font-semibold text-[#68736A] transition hover:bg-[#EEF3EF] hover:text-[#26382C] disabled:opacity-50">先跳过，直接进入</button>
                <button type="button" onClick={next} disabled={submitting} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#176C6B] px-5 text-sm font-bold text-white shadow-[0_8px_20px_rgba(23,108,107,0.20)] transition hover:-translate-y-0.5 hover:bg-[#125856] disabled:cursor-wait disabled:opacity-55">{submitting ? "正在准备…" : step === STEPS.length - 1 ? "保存并开始学习" : "下一题"}<ArrowRight size={16} /></button>
              </div>

              <div className="mt-6 border-t border-[#E5ECE6] pt-5">
                <div className="flex items-center gap-2 text-xs font-bold text-[#607064]"><Clock3 size={14} /> 也可以现在直接开始</div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {quickCards.map((card) => { const Icon = card.icon; return <button key={card.key} type="button" onClick={() => void quickStart(card.key)} disabled={submitting} className="flex min-h-12 items-center gap-3 rounded-xl border border-[#E2EAE3] bg-white px-3 text-left transition hover:border-[#A8C6B3] hover:bg-[#F4F8F4] disabled:opacity-50"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[#EEF6F0] text-[#176C6B]"><Icon size={16} /></span><span><strong className="block text-xs font-semibold text-[#34443A]">{card.title}</strong><span className="mt-0.5 block text-[11px] text-[#849087]">{card.note}</span></span></button>; })}
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
