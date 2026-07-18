"use client";

import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Copy, Eye, RotateCcw } from "lucide-react";
import { Badge, Notice } from "@/components/ui";
import { apiAssetUrl } from "@/lib/api";
import type { ResourceItem } from "@/lib/types";

type Payload = ResourceItem["payload"];

export function FlashcardsBlock({ artifact }: { artifact: NonNullable<Payload["flashcards"]> }) {
  const cards = artifact.cards || [];
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [known, setKnown] = useState<Set<string>>(new Set());
  const card = cards[index];

  if (artifact.blocked) return <Notice tone="warn" title="闪卡暂未生成" desc={artifact.blocked_reason || "所选资料没有可用内容。"} />;
  if (!card) return <Notice tone="warn" title="闪卡为空" desc="请重新生成这组闪卡。" />;

  const move = (delta: number) => {
    setIndex((current) => (current + delta + cards.length) % cards.length);
    setFlipped(false);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div><div className="text-[10px] font-bold tracking-[0.18em] text-fuchsia-700">ACTIVE RECALL</div><strong className="text-sm text-slate-900">{artifact.title || "复习闪卡"}</strong></div>
        <Badge variant="info">已掌握 {known.size}/{cards.length}</Badge>
      </div>
      <button
        type="button"
        onClick={() => setFlipped((value) => !value)}
        className={`group relative flex min-h-56 w-full flex-col justify-between overflow-hidden rounded-2xl border p-5 text-left shadow-sm transition ${flipped ? "border-emerald-200 bg-emerald-50" : "border-fuchsia-200 bg-gradient-to-br from-fuchsia-50 via-white to-violet-50"}`}
        aria-label={flipped ? "查看闪卡正面" : "翻面查看答案"}
      >
        <div className="absolute -right-10 -top-12 h-36 w-36 rounded-full bg-white/70" />
        <div className="relative flex items-center justify-between text-[11px] font-bold tracking-[0.15em] text-slate-500">
          <span>{flipped ? "BACK · 答案" : "FRONT · 问题"}</span><span>{index + 1}/{cards.length}</span>
        </div>
        <div className={`relative my-6 text-center font-bold leading-8 ${flipped ? "text-base text-emerald-950" : "text-xl text-slate-950"}`}>
          {flipped ? card.back : card.front}
        </div>
        <div className="relative flex items-center justify-between gap-3 text-xs text-slate-500">
          <span>{!flipped && card.hint ? `提示：${card.hint}` : card.source_index ? `依据 [${card.source_index}]` : "来源约束内容"}</span>
          <span className="flex items-center gap-1 font-semibold text-fuchsia-700"><RotateCcw size={14} /> 点击翻面</span>
        </div>
      </button>
      <div className="flex items-center justify-between gap-2">
        <button type="button" onClick={() => move(-1)} className="secondary-action"><ArrowLeft size={14} /> 上一张</button>
        <button
          type="button"
          onClick={() => setKnown((current) => {
            const next = new Set(current);
            if (next.has(card.id)) next.delete(card.id); else next.add(card.id);
            return next;
          })}
          className={known.has(card.id) ? "primary-action" : "secondary-action"}
        >
          <Check size={14} /> {known.has(card.id) ? "已掌握" : "标记掌握"}
        </button>
        <button type="button" onClick={() => move(1)} className="secondary-action">下一张 <ArrowRight size={14} /></button>
      </div>
    </div>
  );
}

export function InfographicBlock({ artifact }: { artifact: NonNullable<Payload["infographic"]> }) {
  const sections = artifact.sections || [];
  if (artifact.blocked) return <Notice tone="warn" title="信息图暂未生成" desc={artifact.blocked_reason || "所选资料没有可用内容。"} />;
  return (
    <figure className="overflow-hidden rounded-2xl border border-violet-200 bg-[#F8F6FF]">
      <div className="relative overflow-hidden bg-gradient-to-br from-[#251A49] via-[#423078] to-[#6950A0] px-5 py-6 text-white">
        <div className="absolute -right-8 -top-14 h-40 w-40 rounded-full border-[22px] border-white/10" />
        <div className="relative text-[10px] font-bold tracking-[0.2em] text-violet-200">SOURCE-GROUNDED INFOGRAPHIC</div>
        <h3 className="relative mt-2 text-2xl font-black">{artifact.title || "学习信息图"}</h3>
        {artifact.summary && <p className="relative mt-2 max-w-2xl text-sm leading-6 text-violet-100">{artifact.summary}</p>}
      </div>
      {(artifact.steps || []).length > 0 && (
        <div className="flex gap-1 overflow-x-auto border-b border-violet-200 bg-white p-3">
          {(artifact.steps || []).map((step, index) => (
            <div key={`${step}-${index}`} className="flex min-w-max items-center gap-1.5 text-xs font-semibold text-violet-800">
              <span className="grid h-6 w-6 place-items-center rounded-full bg-violet-100 font-mono text-[10px]">{index + 1}</span>
              <span>{step}</span>{index < (artifact.steps || []).length - 1 && <ArrowRight size={13} className="mx-1 text-violet-300" />}
            </div>
          ))}
        </div>
      )}
      <div className="grid gap-3 p-4 sm:grid-cols-2">
        {sections.map((section, index) => (
          <div key={`${section.title}-${index}`} className={`rounded-xl border bg-white p-4 shadow-sm ${index === 0 ? "border-amber-200 sm:col-span-2" : "border-violet-100"}`}>
            <div className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-violet-100 font-mono text-xs font-black text-violet-700">{String(index + 1).padStart(2, "0")}</span><strong className="text-sm text-slate-950">{section.title}</strong></div>
            <p className="mt-2 text-xs leading-6 text-slate-600">{section.body}</p>
            {section.source_index && <div className="mt-2 font-mono text-[10px] text-violet-500">依据 [{section.source_index}]</div>}
          </div>
        ))}
      </div>
      <figcaption className="border-t border-violet-100 bg-white px-4 py-2 text-[10px] text-slate-400">图中事实仅来自当前课程知识库或你选择的资料。</figcaption>
    </figure>
  );
}

export function DataTableBlock({ artifact }: { artifact: NonNullable<Payload["data_table"]> }) {
  const [copied, setCopied] = useState(false);
  const columns = artifact.columns || [];
  const rows = artifact.rows || [];
  const csv = useMemo(() => [columns, ...rows].map((row) => row.map((cell) => `"${String(cell || "").replace(/"/g, '""')}"`).join(",")).join("\n"), [columns, rows]);
  if (artifact.blocked) return <Notice tone="warn" title="数据表暂未生成" desc={artifact.blocked_reason || "所选资料没有可用内容。"} />;
  return (
    <div className="overflow-hidden rounded-2xl border border-sky-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-sky-100 bg-sky-50 px-4 py-3">
        <div><div className="text-[10px] font-bold tracking-[0.18em] text-sky-700">KNOWLEDGE DATA TABLE</div><strong className="text-sm text-slate-950">{artifact.title || "知识数据表"}</strong></div>
        <button type="button" onClick={() => navigator.clipboard?.writeText(csv).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); })} className="secondary-action"><Copy size={14} /> {copied ? "已复制 CSV" : "复制 CSV"}</button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse text-left text-xs">
          <thead><tr>{columns.map((column) => <th key={column} className="border-b border-sky-100 bg-slate-50 px-4 py-3 font-black text-slate-700">{column}</th>)}</tr></thead>
          <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex} className="odd:bg-white even:bg-sky-50/40">{columns.map((_, columnIndex) => <td key={columnIndex} className="border-b border-slate-100 px-4 py-3 align-top leading-5 text-slate-600">{row[columnIndex] || "—"}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <div className="px-4 py-2 text-[10px] text-slate-400">{rows.length} 行 · {columns.length} 列 · 可复制后在 Excel 或表格工具中继续整理</div>
    </div>
  );
}

export function OnePageVisual({ visual }: { visual: NonNullable<Payload["one_page_visual"]> }) {
  const nodes = visual.nodes || [];
  const imageUrl = apiAssetUrl(visual.image_url);
  if (imageUrl) {
    return (
      <figure className="mb-4 overflow-hidden rounded-2xl border border-emerald-200 bg-[#FAF9F6] shadow-sm" aria-label={`${visual.title || "当前主题"}一图看懂`}>
        <div className="flex items-center justify-between gap-3 border-b border-emerald-100 px-4 py-3">
          <div><div className="text-[10px] font-bold tracking-[0.18em] text-emerald-700">一图看懂</div><h3 className="mt-1 text-lg font-black text-slate-950">{visual.title || "知识图"}</h3></div>
          <Badge variant="success">{visual.provider === "xiaoyunque" ? "小云雀生成" : "AI 知识图"}</Badge>
        </div>
        <a href={imageUrl} target="_blank" rel="noreferrer" className="block bg-[#FAF9F6]" title="打开高清原图">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imageUrl} alt={`一图看懂${visual.title || "当前主题"}`} className="aspect-video h-auto w-full object-contain" />
        </a>
        <figcaption className="px-4 py-2 text-center text-[10px] text-slate-400">点击图片可查看高清原图；内容依据当前资料生成。</figcaption>
      </figure>
    );
  }
  return (
    <figure className="mb-4 overflow-hidden rounded-2xl border border-emerald-200 bg-gradient-to-br from-[#EFF8F3] via-white to-[#F7F2E8] p-4" aria-label={`${visual.title || "当前主题"}结构图`}>
      <div className="flex items-center justify-between gap-3"><div><div className="text-[10px] font-bold tracking-[0.18em] text-emerald-700">一图看懂 · 内置清晰版</div><h3 className="mt-1 text-lg font-black text-slate-950">{visual.title || "知识结构图"}</h3></div><span className="grid h-10 w-10 place-items-center rounded-full bg-emerald-100 text-emerald-700"><Eye size={19} /></span></div>
      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_170px_1fr] lg:items-center">
        <div className="space-y-3">{nodes.filter((_, index) => index % 2 === 0).map((node) => <VisualNode key={node.label} node={node} />)}</div>
        <div className="relative grid min-h-32 place-items-center rounded-full border-4 border-emerald-100 bg-[#163E32] p-5 text-center text-xs font-bold leading-5 text-white shadow-lg"><span>{visual.center || visual.title}</span></div>
        <div className="space-y-3">{nodes.filter((_, index) => index % 2 === 1).map((node) => <VisualNode key={node.label} node={node} />)}</div>
      </div>
      {(visual.steps || []).length > 0 && <div className="mt-4 flex flex-wrap items-center justify-center gap-2">{(visual.steps || []).map((step, index) => <div key={step} className="flex items-center gap-2"><span className="rounded-full border border-emerald-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-emerald-900">{index + 1}. {step}</span>{index < (visual.steps || []).length - 1 && <ArrowRight size={13} className="text-emerald-400" />}</div>)}</div>}
      <figcaption className="mt-3 text-center text-[10px] text-slate-400">小云雀暂时不可用时保留可读结构，不让学习资源中断。</figcaption>
    </figure>
  );
}

function VisualNode({ node }: { node: { label: string; text: string } }) {
  return <div className="rounded-xl border border-emerald-100 bg-white p-3 shadow-sm"><div className="text-[11px] font-black text-emerald-800">{node.label}</div><p className="mt-1 text-[11px] leading-5 text-slate-600">{node.text}</p></div>;
}
