"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Lightbulb,
  LockKeyhole,
  Network,
  RotateCcw,
  Route,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import type { PathNode, PathPlan } from "@/lib/types";

const VIEW_W = 1120;
const VIEW_H = 640;
const NODE_W = 144;
const NODE_H = 68;
const ALL_CHAPTERS = "全部章节";
const CHAPTER_COLORS = [
  "#38E8FF",
  "#FFD166",
  "#45F0A2",
  "#FF7AC8",
  "#FF9F43",
  "#A78BFA",
  "#60A5FA",
  "#2DD4BF",
  "#FB7185",
  "#C084FC",
];

type Point = { x: number; y: number };
type ViewMode = "graph" | "route";

const STATUS = {
  done: {
    label: "已掌握",
    icon: CheckCircle2,
    fill: "#0B3B33",
    border: "#45F0A2",
    text: "#E8FFF8",
    bar: "#45F0A2",
  },
  ready: {
    label: "可学习",
    icon: CircleDot,
    fill: "#0A3244",
    border: "#38E8FF",
    text: "#ECFCFF",
    bar: "#38E8FF",
  },
  locked: {
    label: "待解锁",
    icon: LockKeyhole,
    fill: "#1A2434",
    border: "#64748B",
    text: "#CBD5E1",
    bar: "#64748B",
  },
} satisfies Record<PathNode["status"], object>;

function chapterOf(node: PathNode) {
  return node.chapter?.trim() || "学习主题";
}

function graphLayout(plan: PathPlan): Record<string, Point> {
  const chapters = Array.from(new Set(plan.nodes.map(chapterOf)));
  const groups = new Map<string, PathNode[]>();
  plan.nodes.forEach((node) => {
    const chapter = chapterOf(node);
    groups.set(chapter, [...(groups.get(chapter) || []), node]);
  });

  const pos: Record<string, Point> = {};
  const center = { x: VIEW_W / 2, y: VIEW_H / 2 + 2 };
  const radiusX = 400;
  const radiusY = 228;
  chapters.forEach((chapter, chapterIndex) => {
    const angle = -Math.PI / 2 + (chapterIndex * Math.PI * 2) / Math.max(1, chapters.length);
    const cx = center.x + Math.cos(angle) * radiusX;
    const cy = center.y + Math.sin(angle) * radiusY;
    const nodes = groups.get(chapter) || [];
    nodes.forEach((node, nodeIndex) => {
      const offset = (nodeIndex - (nodes.length - 1) / 2) * 82;
      pos[node.id] = {
        x: cx + -Math.sin(angle) * offset,
        y: cy + Math.cos(angle) * offset,
      };
    });
  });
  return pos;
}

function routeLayout(plan: PathPlan): Record<string, Point> {
  const ids = plan.nodes.map((node) => node.id);
  const indegree = Object.fromEntries(ids.map((id) => [id, 0])) as Record<string, number>;
  const outgoing = Object.fromEntries(ids.map((id) => [id, []])) as Record<string, string[]>;
  plan.edges.forEach((edge) => {
    if (edge.from in outgoing && edge.to in indegree) {
      outgoing[edge.from].push(edge.to);
      indegree[edge.to] += 1;
    }
  });

  const depth: Record<string, number> = {};
  const queue = ids.filter((id) => indegree[id] === 0);
  queue.forEach((id) => { depth[id] = 0; });
  while (queue.length) {
    const current = queue.shift()!;
    outgoing[current].forEach((next) => {
      depth[next] = Math.max(depth[next] ?? 0, (depth[current] ?? 0) + 1);
      indegree[next] -= 1;
      if (indegree[next] === 0) queue.push(next);
    });
  }

  const maxDepth = Math.max(0, ...Object.values(depth));
  const columns: string[][] = [];
  ids.forEach((id) => (columns[depth[id] ?? 0] ||= []).push(id));
  const pos: Record<string, Point> = {};
  columns.forEach((column, columnIndex) => {
    column.forEach((id, rowIndex) => {
      pos[id] = {
        x: 84 + (columnIndex * (VIEW_W - 168)) / Math.max(1, maxDepth),
        y: 76 + ((rowIndex + 1) * (VIEW_H - 152)) / (column.length + 1),
      };
    });
  });
  return pos;
}

function masteryLabel(value: number) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function buttonClass(active = false) {
  return `inline-flex items-center gap-1.5 rounded-full border px-3 py-2 text-xs font-bold transition ${
    active
      ? "border-cyan-300/70 bg-cyan-300/15 text-cyan-50 shadow-[0_0_24px_rgba(56,232,255,.12)]"
      : "border-white/10 bg-white/[0.055] text-slate-300 hover:-translate-y-0.5 hover:border-cyan-300/45 hover:text-white"
  }`;
}

export default function PathDag({
  plan,
  selected,
  onSelect,
}: {
  plan: PathPlan;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [mode, setMode] = useState<ViewMode>("graph");
  const [query, setQuery] = useState("");
  const [chapter, setChapter] = useState(ALL_CHAPTERS);
  const [showRecallHint, setShowRecallHint] = useState(false);

  const byId = useMemo(
    () => Object.fromEntries(plan.nodes.map((node) => [node.id, node])) as Record<string, PathNode>,
    [plan.nodes],
  );
  const chapters = useMemo(() => Array.from(new Set(plan.nodes.map(chapterOf))), [plan.nodes]);
  const chapterCounts = useMemo(
    () => plan.nodes.reduce<Record<string, number>>((counts, node) => {
      const name = chapterOf(node);
      counts[name] = (counts[name] || 0) + 1;
      return counts;
    }, {}),
    [plan.nodes],
  );
  const chapterColors = useMemo(
    () => Object.fromEntries(chapters.map((name, index) => [name, CHAPTER_COLORS[index % CHAPTER_COLORS.length]])),
    [chapters],
  );
  const positions = useMemo(() => (mode === "graph" ? graphLayout(plan) : routeLayout(plan)), [mode, plan]);
  const activeNode = selected ? byId[selected] : undefined;
  const routeNodes = useMemo(
    () => plan.nodes.filter((node) => node.order != null).sort((a, b) => (a.order || 99) - (b.order || 99)).slice(0, 6),
    [plan.nodes],
  );
  const routeIds = useMemo(() => new Set(routeNodes.map((node) => node.id)), [routeNodes]);
  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    plan.nodes.forEach((node) => map.set(node.id, new Set()));
    plan.edges.forEach((edge) => {
      map.get(edge.from)?.add(edge.to);
      map.get(edge.to)?.add(edge.from);
    });
    return map;
  }, [plan.edges, plan.nodes]);

  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const queryHits = useMemo(() => {
    if (!normalizedQuery) return new Set<string>();
    return new Set(plan.nodes.filter((node) => (
      `${node.name} ${node.chapter || ""} ${node.desc || ""} ${node.reason || ""}`
        .toLocaleLowerCase("zh-CN")
        .includes(normalizedQuery)
    )).map((node) => node.id));
  }, [normalizedQuery, plan.nodes]);

  const focus = useMemo(() => {
    const ids = new Set<string>();
    if (normalizedQuery) {
      queryHits.forEach((id) => {
        ids.add(id);
        neighbours.get(id)?.forEach((neighbour) => ids.add(neighbour));
      });
      return { active: true, ids };
    }
    if (chapter !== ALL_CHAPTERS) {
      plan.nodes.filter((node) => chapterOf(node) === chapter).forEach((node) => ids.add(node.id));
      return { active: true, ids };
    }
    if (mode === "route" && routeIds.size) {
      routeIds.forEach((id) => ids.add(id));
      if (plan.next_kp) neighbours.get(plan.next_kp)?.forEach((id) => ids.add(id));
      return { active: true, ids };
    }
    if (selected && byId[selected]) {
      ids.add(selected);
      neighbours.get(selected)?.forEach((id) => ids.add(id));
      return { active: true, ids };
    }
    return { active: false, ids };
  }, [byId, chapter, mode, neighbours, normalizedQuery, plan.next_kp, plan.nodes, queryHits, routeIds, selected]);

  const prerequisites = useMemo(
    () => activeNode
      ? plan.edges.filter((edge) => edge.to === activeNode.id).map((edge) => byId[edge.from]).filter(Boolean)
      : [],
    [activeNode, byId, plan.edges],
  );
  const unlocks = useMemo(
    () => activeNode
      ? plan.edges.filter((edge) => edge.from === activeNode.id).map((edge) => byId[edge.to]).filter(Boolean)
      : [],
    [activeNode, byId, plan.edges],
  );

  useEffect(() => setShowRecallHint(false), [selected]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setQuery("");
      setChapter(ALL_CHAPTERS);
      onSelect(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSelect]);

  const reset = () => {
    setQuery("");
    setChapter(ALL_CHAPTERS);
    setMode("graph");
    onSelect(null);
  };
  const courseLocked = plan.course_id === "data_structures_algorithms";
  const readyCount = plan.nodes.filter((node) => node.status === "ready").length;

  return (
    <div className="overflow-hidden rounded-[18px] border border-slate-800 bg-[#06101E] text-white shadow-[0_24px_80px_rgba(2,8,23,.2)]">
      <div className="relative overflow-hidden border-b border-white/10 px-4 py-5 sm:px-6">
        <div className="pointer-events-none absolute -left-16 -top-24 h-60 w-60 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="relative flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-black tracking-[0.2em] text-cyan-300">INTERACTIVE KNOWLEDGE GRAPH</span>
              <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-bold ${courseLocked ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-200" : "border-violet-300/25 bg-violet-300/10 text-violet-200"}`}>
                <ShieldCheck size={12} /> {courseLocked ? "课程范围已锁定" : "本书对话范围"}
              </span>
            </div>
            <h2 className="mt-2 text-xl font-black tracking-tight sm:text-2xl">{plan.course || "知识关系图"}</h2>
            <p className="mt-1 max-w-2xl text-xs leading-6 text-slate-400 sm:text-sm">点击节点进入聚光灯模式，查看先修关系、掌握证据和下一步；无关节点会自动降噪。</p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              [plan.nodes.length, "知识点"],
              [plan.edges.length, "先修关系"],
              [readyCount, "可学习"],
            ].map(([value, label]) => (
              <div key={String(label)} className="min-w-[76px] rounded-xl border border-white/10 bg-white/[0.055] px-3 py-2">
                <strong className="block text-lg text-white">{value}</strong>
                <span className="text-[10px] text-slate-400">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="border-b border-white/10 bg-slate-950/25 px-4 py-4 sm:px-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-slate-400 focus-within:border-cyan-300/60 focus-within:ring-2 focus-within:ring-cyan-300/10 xl:max-w-[380px]">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                if (event.target.value.trim()) setChapter(ALL_CHAPTERS);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSelect(Array.from(queryHits)[0] || null);
              }}
              className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-600"
              placeholder="搜索：栈、二叉树、Dijkstra…"
              aria-label="搜索知识点"
            />
            {query && <button type="button" onClick={() => setQuery("")} className="text-slate-500 hover:text-white" aria-label="清空搜索"><X size={15} /></button>}
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonClass(mode === "graph")} onClick={() => { setMode("graph"); setQuery(""); setChapter(ALL_CHAPTERS); }}><Network size={14} />章节图谱</button>
            <button type="button" className={buttonClass(mode === "route")} onClick={() => { setMode("route"); setQuery(""); setChapter(ALL_CHAPTERS); }}><Route size={14} />学习主线</button>
            <button type="button" className={buttonClass(false)} onClick={reset}><RotateCcw size={14} />重置</button>
          </div>
        </div>
        <div className="mt-3 rounded-2xl border border-white/[0.07] bg-black/15 p-2.5 sm:p-3">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-1.5 px-0.5">
            <span className="text-[10px] font-black tracking-[0.16em] text-slate-400">章节导航</span>
            <span className="text-[10px] font-bold text-slate-500">{chapters.length} 个章节 · {plan.nodes.length} 个知识点 · 全部可见</span>
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="按章节筛选知识图谱">
            <button type="button" onClick={() => { setChapter(ALL_CHAPTERS); setQuery(""); }} className={buttonClass(chapter === ALL_CHAPTERS)}>
              {ALL_CHAPTERS}
              <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-300">{plan.nodes.length}</span>
            </button>
            {chapters.map((name) => (
              <button type="button" key={name} onClick={() => { setChapter(name); setQuery(""); }} className={buttonClass(chapter === name)}>
                <i className="h-2 w-2 shrink-0 rounded-full shadow-[0_0_12px_currentColor]" style={{ backgroundColor: chapterColors[name], color: chapterColors[name] }} />
                <span>{name.replace(/^第\d+章\s*/, "")}</span>
                <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-300">{chapterCounts[name]}</span>
              </button>
            ))}
          </div>
        </div>
        {normalizedQuery && (
          <div className={`mt-3 text-xs ${queryHits.size ? "text-cyan-200" : "text-amber-200"}`}>
            {queryHits.size ? `找到 ${queryHits.size} 个知识点；按 Enter 打开第一个结果。` : "当前课程内没有匹配知识点。"}
          </div>
        )}
      </div>

      {routeNodes.length > 0 && (
        <div className="border-b border-white/10 px-4 py-3 sm:px-6">
          <div className="no-scrollbar flex items-center gap-3 overflow-x-auto pb-1">
            <span className="shrink-0 text-[10px] font-black tracking-[0.16em] text-amber-300">你的学习主线</span>
            {routeNodes.map((node, index) => (
              <div key={node.id} className="flex shrink-0 items-center gap-2">
                <button type="button" onClick={() => { setMode("route"); setQuery(""); setChapter(ALL_CHAPTERS); onSelect(node.id); }} className="rounded-full border border-amber-200/20 bg-amber-200/[0.07] px-3 py-1.5 text-xs font-bold text-amber-50 hover:border-amber-200/50">
                  {node.order}. {node.name}
                </button>
                {index < routeNodes.length - 1 && <ChevronRight size={13} className="text-amber-300/50" />}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid 2xl:grid-cols-[minmax(0,1fr)_292px]">
        <div className="relative min-w-0 overflow-x-auto border-b border-white/10 2xl:border-b-0 2xl:border-r">
          <div className="absolute left-4 top-4 z-10 rounded-full border border-white/10 bg-slate-950/75 px-3 py-1.5 text-[10px] font-bold text-slate-300 backdrop-blur">
            {normalizedQuery
              ? `搜索聚焦 · ${queryHits.size} 个命中`
              : chapter !== ALL_CHAPTERS
                ? `章节聚焦 · ${chapter}`
                : mode === "route"
                  ? "个性化学习主线"
                  : selected
                    ? `关系聚焦 · ${byId[selected]?.name || "知识点"}`
                    : "课程全图"}
          </div>
          <svg
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            className="block h-auto min-h-[480px] min-w-[760px] w-full"
            role="img"
            aria-label={`${plan.course || "课程"}交互式知识图谱`}
            onClick={() => onSelect(null)}
          >
            <defs>
              <radialGradient id="graph-background" cx="50%" cy="48%" r="70%">
                <stop offset="0%" stopColor="#10253D" stopOpacity="0.86" />
                <stop offset="100%" stopColor="#06101E" stopOpacity="0" />
              </radialGradient>
              <filter id="node-glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <marker id="knowledge-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M0,0 L8,4 L0,8 z" fill="#8293AA" />
              </marker>
            </defs>
            <rect width={VIEW_W} height={VIEW_H} fill="url(#graph-background)" />
            <g opacity="0.15">
              {Array.from({ length: 22 }).map((_, index) => (
                <circle key={index} cx={(index * 167) % VIEW_W} cy={(index * 97) % VIEW_H} r={(index % 3) + 1} fill="#BFEFFF" />
              ))}
            </g>

            {plan.edges.map((edge, index) => {
              const from = positions[edge.from];
              const to = positions[edge.to];
              if (!from || !to) return null;
              const selectedEdge = Boolean(selected && (edge.from === selected || edge.to === selected));
              const routeEdge = mode === "route" && routeIds.has(edge.from) && routeIds.has(edge.to);
              const dim = focus.active && !(focus.ids.has(edge.from) && focus.ids.has(edge.to));
              const stroke = routeEdge ? "#FFD166" : selectedEdge ? "#E9FAFF" : "#8293AA";
              const path = mode === "route"
                ? `M ${from.x + NODE_W / 2 - 8} ${from.y} C ${(from.x + to.x) / 2} ${from.y}, ${(from.x + to.x) / 2} ${to.y}, ${to.x - NODE_W / 2 + 8} ${to.y}`
                : `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
              return (
                <g key={`${edge.from}-${edge.to}-${index}`} opacity={dim ? 0.08 : selectedEdge || routeEdge ? 0.95 : 0.34}>
                  <path d={path} fill="none" stroke={stroke} strokeWidth={selectedEdge || routeEdge ? 2.6 : 1.25} markerEnd="url(#knowledge-arrow)" />
                  {selectedEdge && (
                    <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 7} textAnchor="middle" fontSize="10" fontWeight="800" fill="#EAFBFF" stroke="#06101E" strokeWidth="4" paintOrder="stroke">
                      先修
                    </text>
                  )}
                </g>
              );
            })}

            {plan.nodes.map((node) => {
              const point = positions[node.id];
              if (!point) return null;
              const style = STATUS[node.status];
              const chapterColor = chapterColors[chapterOf(node)] || CHAPTER_COLORS[0];
              const dim = focus.active && !focus.ids.has(node.id);
              const isSelected = selected === node.id;
              const isHit = queryHits.has(node.id);
              const isRoute = mode === "route" && routeIds.has(node.id);
              const isNext = plan.next_kp === node.id;
              const statusSymbol = node.status === "done" ? "✓" : node.status === "locked" ? "·" : "●";
              return (
                <g
                  key={node.id}
                  transform={`translate(${point.x - NODE_W / 2}, ${point.y - NODE_H / 2})`}
                  opacity={dim ? 0.12 : 1}
                  className="cursor-pointer transition-opacity"
                  onClick={(event) => { event.stopPropagation(); onSelect(node.id); }}
                  role="button"
                  aria-label={`${node.name}，${style.label}，掌握度 ${masteryLabel(node.mastery)}`}
                >
                  {(isSelected || isHit || isRoute) && (
                    <rect x="-5" y="-5" width={NODE_W + 10} height={NODE_H + 10} rx="18" fill="none" stroke={isRoute ? "#FFD166" : isHit ? "#FFF5A6" : "#FFFFFF"} strokeWidth="2" strokeDasharray={isRoute ? "5 4" : undefined} filter="url(#node-glow)" />
                  )}
                  <rect width={NODE_W} height={NODE_H} rx="14" fill={style.fill} stroke={isSelected ? "#FFFFFF" : style.border} strokeWidth={isSelected ? 2.5 : 1.35} />
                  <rect x="1" y="1" width={NODE_W - 2} height="4" rx="2" fill={chapterColor} opacity="0.95" />
                  <circle cx="15" cy="18" r="7" fill={style.border} opacity="0.18" />
                  <text x="15" y="21" textAnchor="middle" fontSize="9" fontWeight="900" fill={style.border}>{statusSymbol}</text>
                  <text x={NODE_W / 2} y="27" textAnchor="middle" fontSize="14" fontWeight="900" fill={style.text}>{node.name}</text>
                  <text x="12" y="47" fontSize="9.5" fontWeight="700" fill="#9FB2C9">{style.label}</text>
                  <text x={NODE_W - 12} y="47" textAnchor="end" fontSize="10" fontWeight="900" fill={style.border}>{masteryLabel(node.mastery)}</text>
                  <rect x="12" y={NODE_H - 10} width={NODE_W - 24} height="4" rx="2" fill="#334155" />
                  <rect x="12" y={NODE_H - 10} width={(NODE_W - 24) * Math.max(0, Math.min(1, node.mastery))} height="4" rx="2" fill={style.bar} />
                  {isNext && (
                    <g transform={`translate(${NODE_W - 21}, -8)`}>
                      <rect width="42" height="16" rx="8" fill="#0F6B50" stroke="#8CF4CD" strokeWidth="0.6" />
                      <text x="21" y="11.5" textAnchor="middle" fontSize="8.5" fontWeight="900" fill="#FFFFFF">下一步</text>
                    </g>
                  )}
                  {node.order && (
                    <g transform="translate(-4,-4)">
                      <circle r="11" fill="#FFD166" stroke="#FFF2C2" strokeWidth="1" />
                      <text y="3.5" textAnchor="middle" fontSize="10" fontWeight="900" fill="#1B2430">{node.order}</text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>
          <div className="flex flex-wrap gap-x-4 gap-y-2 border-t border-white/10 px-4 py-3 text-[10px] text-slate-400 sm:px-6">
            {(Object.entries(STATUS) as [PathNode["status"], typeof STATUS[PathNode["status"]]][]).map(([key, item]) => (
              <span key={key} className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: item.border }} />{item.label}</span>
            ))}
            <span className="ml-auto">点击空白处清除聚焦 · Esc 重置搜索</span>
          </div>
        </div>

        <aside className="bg-slate-950/25 p-5">
          {activeNode ? (
            <div>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black tracking-[0.16em] text-cyan-300">NODE DETAIL</div>
                  <h3 className="mt-2 text-xl font-black">{activeNode.name}</h3>
                </div>
                <span className="rounded-full border px-2.5 py-1 text-[10px] font-bold" style={{ color: STATUS[activeNode.status].border, borderColor: `${STATUS[activeNode.status].border}55`, backgroundColor: `${STATUS[activeNode.status].border}14` }}>
                  {STATUS[activeNode.status].label}
                </span>
              </div>
              <p className="mt-2 text-xs leading-6 text-slate-400">{activeNode.chapter || "学习主题"}</p>
              <p className="mt-3 text-sm leading-6 text-slate-300">{activeNode.desc || activeNode.reason}</p>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-white/10 bg-white/[0.045] p-3"><strong className="block text-lg">{masteryLabel(activeNode.mastery)}</strong><span className="text-[10px] text-slate-500">当前掌握度</span></div>
                <div className="rounded-xl border border-white/10 bg-white/[0.045] p-3"><strong className="block text-lg">{activeNode.difficulty}/5</strong><span className="text-[10px] text-slate-500">学习难度</span></div>
              </div>

              <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.045] p-3">
                <div className="flex items-center gap-2 text-xs font-black text-white"><BookOpen size={14} className="text-cyan-300" />为什么现在推荐</div>
                <p className="mt-2 text-xs leading-5 text-slate-400">{activeNode.reason}</p>
              </div>

              <div className="mt-4">
                <div className="text-[10px] font-black tracking-[0.14em] text-slate-500">前置知识</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {prerequisites.length ? prerequisites.map((node) => (
                    <button type="button" key={node.id} onClick={() => onSelect(node.id)} className="rounded-full border border-cyan-300/15 bg-cyan-300/[0.07] px-2.5 py-1.5 text-xs text-cyan-100 hover:border-cyan-300/50">{node.name}</button>
                  )) : <span className="text-xs text-slate-500">本课程起点，无课程内前置要求</span>}
                </div>
              </div>

              <div className="mt-4">
                <div className="text-[10px] font-black tracking-[0.14em] text-slate-500">学完可解锁</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {unlocks.length ? unlocks.map((node) => (
                    <button type="button" key={node.id} onClick={() => onSelect(node.id)} className="rounded-full border border-violet-300/15 bg-violet-300/[0.07] px-2.5 py-1.5 text-xs text-violet-100 hover:border-violet-300/50">{node.name}</button>
                  )) : <span className="text-xs text-slate-500">当前为这条学习分支的终点</span>}
                </div>
              </div>

              <div className="mt-5 rounded-xl border border-amber-200/15 bg-gradient-to-br from-amber-200/[0.07] to-cyan-300/[0.05] p-4">
                <div className="flex items-center gap-2 text-xs font-black text-amber-100"><Lightbulb size={14} />主动回忆</div>
                <p className="mt-2 text-xs leading-5 text-slate-300">
                  {prerequisites[0]
                    ? `不看图回答：为什么学习「${activeNode.name}」前要先理解「${prerequisites[0].name}」？`
                    : `不看图回答：「${activeNode.name}」在本课程中为哪些后续知识打基础？`}
                </p>
                <button type="button" onClick={() => setShowRecallHint((value) => !value)} className="mt-3 rounded-lg border border-amber-200/20 px-2.5 py-1.5 text-[10px] font-bold text-amber-100 hover:border-amber-200/50">
                  {showRecallHint ? "收起提示" : "给我提示"}
                </button>
                {showRecallHint && <p className="mt-2 text-[11px] leading-5 text-amber-100/70">先说两者的关系，再举一个操作过程、复杂度或典型题型中的例子。</p>}
              </div>
            </div>
          ) : (
            <div className="flex min-h-[420px] flex-col justify-center">
              <Network size={30} className="text-cyan-300" />
              <div className="mt-4 text-[10px] font-black tracking-[0.16em] text-cyan-300">COURSE OVERVIEW</div>
              <h3 className="mt-2 text-xl font-black">从一张图看懂课程边界</h3>
              <p className="mt-3 text-sm leading-7 text-slate-400">当前图谱只包含「{plan.course || "本课程"}」的知识点。搜索或点击任一节点，可查看前置关系、掌握度和主动回忆问题。</p>
              <div className="mt-5 space-y-2 text-xs text-slate-300">
                <div className="flex items-center gap-2"><ShieldCheck size={14} className="text-emerald-300" />课程数据与题库、讲义使用同一知识点集合</div>
                <div className="flex items-center gap-2"><Route size={14} className="text-amber-300" />学习主线按你的掌握度实时重排</div>
                <div className="flex items-center gap-2"><Search size={14} className="text-cyan-300" />搜索结果自动保留一跳关系</div>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
