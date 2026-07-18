"use client";

import { Pause, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type Stage = { label: string; detail: string };

function clean(value: string): string {
  return value
    .replace(/\[\^\d+\]/g, "")
    .replace(/[`*_>#]/g, "")
    .replace(/^\s*(?:[-+•]|\d+[.、])\s*/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function animationStages(text: string): Stage[] {
  const isImplementationLine = (line: string) => /^(?:def |class |return\b|if\b|for\b|while\b|self\.|[A-Za-z_]\w*\s*=)|[{}]|\.append\(|\.left\b|\.right\b/.test(line);
  const lines = text
    .split(/\r?\n/)
    .map(clean)
    .filter((line) => line.length >= 8 && line.length <= 120 && !isImplementationLine(line));
  const sentences = clean(text)
    .split(/(?<=[。！？!?；;])\s*/)
    .map(clean)
    .filter((line) => line.length >= 10 && !isImplementationLine(line));
  const candidates = [...lines, ...sentences].filter((line, index, items) => (
    items.findIndex((item) => item.slice(0, 32) === line.slice(0, 32)) === index
  ));
  const selected = candidates.slice(0, 4);
  if (!selected.length) return [];
  while (selected.length < 3) selected.push(selected[selected.length - 1]);
  const labels = ["先抓核心", "看清变化", "走完步骤", "检查边界"];
  return selected.map((detail, index) => ({
    label: labels[index] || `第 ${index + 1} 步`,
    detail: detail.length > 86 ? `${detail.slice(0, 86)}…` : detail,
  }));
}

function isLearningAnswer(text: string, stages: Stage[]): boolean {
  const compact = clean(text);
  if (compact.length < 60 || stages.length < 3) return false;
  return !/^(你好|您好|嗨|谢谢|不客气|再见|拜拜)/.test(compact);
}

export default function InlineConceptAnimation({ question, text }: { question: string; text: string }) {
  const stages = useMemo(() => animationStages(text), [text]);
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(true);
  const visible = isLearningAnswer(text, stages);

  useEffect(() => {
    setActive(0);
    setPlaying(true);
  }, [text]);

  useEffect(() => {
    if (!visible || !playing || stages.length < 2) return;
    const timer = window.setInterval(() => setActive((index) => (index + 1) % stages.length), 1700);
    return () => window.clearInterval(timer);
  }, [playing, stages.length, visible]);

  if (!visible) return null;
  const title = clean(question).slice(0, 34) || "这个知识点";

  return (
    <section className="overflow-hidden rounded-[14px] border border-emerald-200 bg-gradient-to-br from-[#F3FBF6] to-[#E8F5EE] shadow-sm" aria-label={`${title}动态理解`}>
      <div className="flex items-center justify-between gap-3 border-b border-emerald-200/70 px-4 py-3">
        <div>
          <div className="text-[10px] font-bold tracking-[0.18em] text-emerald-700">动态理解</div>
          <strong className="mt-0.5 block text-sm text-slate-900">{title}</strong>
        </div>
        <button type="button" onClick={() => setPlaying((value) => !value)} className="grid h-8 w-8 place-items-center rounded-full border border-emerald-200 bg-white text-emerald-700 transition hover:bg-emerald-50" aria-label={playing ? "暂停动态演示" : "播放动态演示"}>
          {playing ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
        </button>
      </div>
      <div className="px-4 py-4">
        <div className="relative flex items-start justify-between gap-1">
          <div className="absolute left-5 right-5 top-4 h-0.5 bg-emerald-200" aria-hidden />
          {stages.map((stage, index) => (
            <button key={`${stage.label}-${index}`} type="button" onClick={() => { setActive(index); setPlaying(false); }} className="relative flex min-w-0 flex-1 flex-col items-center text-center">
              <span className={`grid h-8 w-8 place-items-center rounded-full border-2 text-xs font-black transition ${index <= active ? "border-emerald-600 bg-emerald-600 text-white" : "border-emerald-200 bg-white text-emerald-400"}`}>{index + 1}</span>
              <span className={`mt-2 line-clamp-1 text-[10px] font-bold ${index === active ? "text-emerald-800" : "text-slate-400"}`}>{stage.label}</span>
            </button>
          ))}
        </div>
        <div className="mt-4 rounded-xl border border-white/80 bg-white/85 px-4 py-3 text-center">
          <strong className="text-xs text-emerald-800">{stages[active]?.label}</strong>
          <p className="mt-1 text-xs leading-5 text-slate-600">{stages[active]?.detail}</p>
        </div>
      </div>
    </section>
  );
}
