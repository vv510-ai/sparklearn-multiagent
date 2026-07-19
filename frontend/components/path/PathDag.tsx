"use client";

import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";
import {
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Lightbulb,
  Layers3,
  LockKeyhole,
  Maximize2,
  Minimize2,
  Network,
  RotateCcw,
  Route,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import type { PathNode, PathPlan, PathSubtopic } from "@/lib/types";

const VIEW_W = 800;
const VIEW_H = 640;
const NODE_W = 144;
const NODE_H = 68;
const DETAIL_NODE_W = 112;
const DETAIL_NODE_H = 44;
const EXPANDED_CHAPTER_H = 350;
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
type DragState = {
  id: string;
  pointerId: number;
  offsetX: number;
  offsetY: number;
  startX: number;
  startY: number;
  moved: boolean;
};
type DisplayNode = PathNode & {
  detail?: boolean;
  parentId?: string;
  relation?: string;
};
type DisplayEdge = { from: string; to: string; label?: string; detail?: boolean };

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

function compactGraphLayout(plan: PathPlan): Record<string, Point> {
  const chapters = Array.from(new Set(plan.nodes.map(chapterOf)));
  const groups = new Map<string, PathNode[]>();
  plan.nodes.forEach((node) => {
    const chapter = chapterOf(node);
    groups.set(chapter, [...(groups.get(chapter) || []), node]);
  });

  const pos: Record<string, Point> = {};
  const center = { x: VIEW_W / 2, y: VIEW_H / 2 + 2 };
  const radiusX = 280;
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

function expandedGraphLayout(plan: PathPlan, expanded: Set<string>) {
  if (!expanded.size) return { positions: compactGraphLayout(plan), height: VIEW_H };

  const chapters = Array.from(new Set(plan.nodes.map(chapterOf)));
  const columns = 2;
  const cellWidth = VIEW_W / columns;
  const positions: Record<string, Point> = {};

  chapters.forEach((chapter, chapterIndex) => {
    const row = Math.floor(chapterIndex / columns);
    const column = chapterIndex % columns;
    const left = column * cellWidth;
    const top = row * EXPANDED_CHAPTER_H + 32;
    const parents = plan.nodes.filter((node) => chapterOf(node) === chapter);
    const parentSpan = Math.min(380, cellWidth - 180);
    parents.forEach((node, index) => {
      positions[node.id] = {
        x: left + cellWidth / 2 + (index - (parents.length - 1) / 2) * (parentSpan / Math.max(1, parents.length - 1)),
        y: top + 72,
      };
    });

    const details = parents.flatMap((node) => (
      expanded.has(node.id)
        ? (node.subtopics || []).map((detail) => ({ detail, parentId: node.id }))
        : []
    ));
    const detailColumns = 4;
    details.forEach(({ detail }, index) => {
      const detailColumn = index % detailColumns;
      const detailRow = Math.floor(index / detailColumns);
      positions[detail.id] = {
        x: left + 82 + detailColumn * ((cellWidth - 164) / (detailColumns - 1)),
        y: top + 166 + detailRow * 62,
      };
    });
  });

  return {
    positions,
    height: Math.max(VIEW_H, Math.ceil(chapters.length / columns) * EXPANDED_CHAPTER_H + 20),
  };
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

function motionSeed(id: string) {
  let seed = 0;
  for (let index = 0; index < id.length; index += 1) {
    seed = (seed * 31 + id.charCodeAt(index)) % 997;
  }
  return (seed / 997) * Math.PI * 2;
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
  const expandableIds = useMemo(
    () => plan.nodes.filter((node) => node.subtopics?.length).map((node) => node.id),
    [plan.nodes],
  );
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(expandableIds));
  const [activeDetailId, setActiveDetailId] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [manualPositions, setManualPositions] = useState<Record<string, Point>>({});
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [motionTime, setMotionTime] = useState(0);
  const [reduceMotion, setReduceMotion] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const suppressClickRef = useRef<string | null>(null);

  const allDisplayNodes = useMemo<DisplayNode[]>(() => plan.nodes.flatMap((node) => [
    node,
    ...(node.subtopics || []).map((detail: PathSubtopic): DisplayNode => ({
      id: detail.id,
      name: detail.name,
      mastery: node.mastery,
      status: node.status,
      difficulty: node.difficulty,
      score: node.score,
      reason: `属于「${node.name}」的${detail.relation || "细分概念"}`,
      chapter: node.chapter,
      desc: detail.desc,
      detail: true,
      parentId: node.id,
      relation: detail.relation,
    })),
  ]), [plan.nodes]);
  const allNodeById = useMemo(
    () => Object.fromEntries(allDisplayNodes.map((node) => [node.id, node])) as Record<string, DisplayNode>,
    [allDisplayNodes],
  );
  const displayNodes = useMemo(
    () => mode === "route"
      ? allDisplayNodes.filter((node) => !node.detail)
      : allDisplayNodes.filter((node) => !node.detail || expanded.has(node.parentId || "")),
    [allDisplayNodes, expanded, mode],
  );
  const displayEdges = useMemo<DisplayEdge[]>(() => {
    const courseEdges = plan.edges.map((edge) => ({ ...edge, label: "先修" }));
    if (mode === "route") return courseEdges;
    const detailEdges = plan.nodes.flatMap((node) => (
      expanded.has(node.id)
        ? (node.subtopics || []).map((detail) => ({
          from: node.id,
          to: detail.id,
          label: detail.relation || "包含",
          detail: true,
        }))
        : []
    ));
    const visibleIds = new Set(displayNodes.map((node) => node.id));
    const crossEdges = (plan.detail_edges || [])
      .filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to))
      .map((edge) => ({ ...edge, detail: true }));
    return [...courseEdges, ...detailEdges, ...crossEdges];
  }, [displayNodes, expanded, mode, plan.detail_edges, plan.edges, plan.nodes]);
  const byId = useMemo(
    () => Object.fromEntries(displayNodes.map((node) => [node.id, node])) as Record<string, DisplayNode>,
    [displayNodes],
  );
  const chapters = useMemo(() => Array.from(new Set(plan.nodes.map(chapterOf))), [plan.nodes]);
  const chapterCounts = useMemo(
    () => allDisplayNodes.reduce<Record<string, number>>((counts, node) => {
      const name = chapterOf(node);
      counts[name] = (counts[name] || 0) + 1;
      return counts;
    }, {}),
    [allDisplayNodes],
  );
  const chapterColors = useMemo(
    () => Object.fromEntries(chapters.map((name, index) => [name, CHAPTER_COLORS[index % CHAPTER_COLORS.length]])),
    [chapters],
  );
  const layout = useMemo(
    () => mode === "graph"
      ? expandedGraphLayout(plan, expanded)
      : { positions: routeLayout(plan), height: VIEW_H },
    [expanded, mode, plan],
  );
  const positions = useMemo<Record<string, Point>>(() => {
    const animated: Record<string, Point> = {};
    Object.entries(layout.positions).forEach(([id, base]) => {
      const anchor = mode === "graph" && manualPositions[id] ? manualPositions[id] : base;
      const node = allNodeById[id];
      if (mode !== "graph" || reduceMotion || draggingId === id) {
        animated[id] = anchor;
        return;
      }
      const seed = motionSeed(id);
      const amplitude = node?.detail ? 1.55 : 2.35;
      animated[id] = {
        x: anchor.x
          + Math.sin(motionTime * 0.00062 + seed) * amplitude
          + Math.sin(motionTime * 0.00027 + seed * 1.7) * amplitude * 0.32,
        y: anchor.y
          + Math.cos(motionTime * 0.00049 + seed * 0.83) * amplitude * 0.82
          + Math.sin(motionTime * 0.00031 + seed * 1.23) * amplitude * 0.28,
      };
    });
    return animated;
  }, [allNodeById, draggingId, layout.positions, manualPositions, mode, motionTime, reduceMotion]);
  const activeId = activeDetailId && byId[activeDetailId] ? activeDetailId : selected;
  const activeNode = activeId ? byId[activeId] : undefined;
  const routeNodes = useMemo(
    () => plan.nodes.filter((node) => node.order != null).sort((a, b) => (a.order || 99) - (b.order || 99)).slice(0, 6),
    [plan.nodes],
  );
  const routeIds = useMemo(() => new Set(routeNodes.map((node) => node.id)), [routeNodes]);
  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    displayNodes.forEach((node) => map.set(node.id, new Set()));
    displayEdges.forEach((edge) => {
      map.get(edge.from)?.add(edge.to);
      map.get(edge.to)?.add(edge.from);
    });
    return map;
  }, [displayEdges, displayNodes]);

  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const queryHits = useMemo(() => {
    if (!normalizedQuery) return new Set<string>();
    return new Set(allDisplayNodes.filter((node) => (
      `${node.name} ${node.chapter || ""} ${node.desc || ""} ${node.reason || ""}`
        .toLocaleLowerCase("zh-CN")
        .includes(normalizedQuery)
    )).map((node) => node.id));
  }, [allDisplayNodes, normalizedQuery]);

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
      displayNodes.filter((node) => chapterOf(node) === chapter).forEach((node) => ids.add(node.id));
      return { active: true, ids };
    }
    if (mode === "route" && routeIds.size) {
      routeIds.forEach((id) => ids.add(id));
      if (plan.next_kp) neighbours.get(plan.next_kp)?.forEach((id) => ids.add(id));
      return { active: true, ids };
    }
    if (activeId && byId[activeId]) {
      ids.add(activeId);
      neighbours.get(activeId)?.forEach((id) => ids.add(id));
      return { active: true, ids };
    }
    return { active: false, ids };
  }, [activeId, byId, chapter, displayNodes, mode, neighbours, normalizedQuery, plan.next_kp, queryHits, routeIds]);

  const prerequisites = useMemo(
    () => activeNode
      ? displayEdges.filter((edge) => edge.to === activeNode.id).map((edge) => byId[edge.from]).filter(Boolean)
      : [],
    [activeNode, byId, displayEdges],
  );
  const unlocks = useMemo(
    () => activeNode
      ? displayEdges.filter((edge) => edge.from === activeNode.id).map((edge) => byId[edge.to]).filter(Boolean)
      : [],
    [activeNode, byId, displayEdges],
  );

  useEffect(() => {
    setExpanded(new Set(expandableIds));
    setActiveDetailId(null);
    setManualPositions({});
  }, [expandableIds]);
  useEffect(() => {
    if (activeDetailId && byId[activeDetailId]?.parentId !== selected) setActiveDetailId(null);
  }, [activeDetailId, byId, selected]);
  useEffect(() => setShowRecallHint(false), [activeId]);
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const syncPreference = () => setReduceMotion(preference.matches);
    syncPreference();
    preference.addEventListener("change", syncPreference);
    return () => preference.removeEventListener("change", syncPreference);
  }, []);
  useEffect(() => {
    if (reduceMotion || mode !== "graph") {
      setMotionTime(0);
      return;
    }
    let frame = 0;
    let lastFrame = 0;
    const animate = (time: number) => {
      if (time - lastFrame >= 36) {
        lastFrame = time;
        setMotionTime(time);
      }
      frame = window.requestAnimationFrame(animate);
    };
    frame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frame);
  }, [mode, reduceMotion]);
  useEffect(() => {
    if (!fullscreen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [fullscreen]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (fullscreen) {
        setFullscreen(false);
        return;
      }
      setQuery("");
      setChapter(ALL_CHAPTERS);
      setActiveDetailId(null);
      onSelect(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen, onSelect]);

  const reset = () => {
    setQuery("");
    setChapter(ALL_CHAPTERS);
    setMode("graph");
    setExpanded(new Set(expandableIds));
    setActiveDetailId(null);
    setManualPositions({});
    onSelect(null);
  };
  const toggleExpanded = (nodeId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  };
  const toggleAllDetails = () => {
    setMode("graph");
    setActiveDetailId(null);
    const collapse = expanded.size === expandableIds.length;
    if (collapse) setManualPositions({});
    setExpanded(collapse ? new Set() : new Set(expandableIds));
  };
  const pointerToGraph = (event: ReactPointerEvent<SVGGElement>) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const matrix = svg.getScreenCTM();
    if (!matrix) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(matrix.inverse());
  };
  const startDrag = (event: ReactPointerEvent<SVGGElement>, node: DisplayNode) => {
    if (mode !== "graph" || event.button !== 0) return;
    const pointer = pointerToGraph(event);
    const current = positions[node.id];
    if (!pointer || !current) return;
    event.preventDefault();
    event.stopPropagation();
    suppressClickRef.current = null;
    dragRef.current = {
      id: node.id,
      pointerId: event.pointerId,
      offsetX: pointer.x - current.x,
      offsetY: pointer.y - current.y,
      startX: current.x,
      startY: current.y,
      moved: false,
    };
    setManualPositions((value) => ({ ...value, [node.id]: current }));
    setDraggingId(node.id);
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveDrag = (event: ReactPointerEvent<SVGGElement>, node: DisplayNode) => {
    const drag = dragRef.current;
    if (!drag || drag.id !== node.id || drag.pointerId !== event.pointerId) return;
    const pointer = pointerToGraph(event);
    if (!pointer) return;
    event.preventDefault();
    event.stopPropagation();
    const halfWidth = (node.detail ? DETAIL_NODE_W : NODE_W) / 2;
    const halfHeight = (node.detail ? DETAIL_NODE_H : NODE_H) / 2;
    const next = {
      x: Math.max(halfWidth + 6, Math.min(VIEW_W - halfWidth - 6, pointer.x - drag.offsetX)),
      y: Math.max(halfHeight + 6, Math.min(layout.height - halfHeight - 6, pointer.y - drag.offsetY)),
    };
    if (Math.hypot(next.x - drag.startX, next.y - drag.startY) > 1.6) drag.moved = true;
    setManualPositions((value) => ({ ...value, [node.id]: next }));
  };
  const endDrag = (event: ReactPointerEvent<SVGGElement>, node: DisplayNode) => {
    const drag = dragRef.current;
    if (!drag || drag.id !== node.id || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (drag.moved) suppressClickRef.current = node.id;
    dragRef.current = null;
    setDraggingId(null);
  };
  const clickDisplayNode = (event: ReactMouseEvent<SVGGElement>, node: DisplayNode) => {
    event.stopPropagation();
    if (suppressClickRef.current === node.id) {
      suppressClickRef.current = null;
      return;
    }
    selectDisplayNode(node);
  };
  function selectDisplayNode(node: DisplayNode) {
    if (node.detail) {
      setActiveDetailId(node.id);
      onSelect(node.parentId || null);
      return;
    }
    setActiveDetailId(null);
    if (node.subtopics?.length && !expanded.has(node.id)) toggleExpanded(node.id);
    onSelect(node.id);
  }
  const updateQuery = (value: string) => {
    setQuery(value);
    if (!value.trim()) return;
    setChapter(ALL_CHAPTERS);
    const probe = value.trim().toLocaleLowerCase("zh-CN");
    const parents = allDisplayNodes
      .filter((node) => node.detail && `${node.name} ${node.desc || ""}`.toLocaleLowerCase("zh-CN").includes(probe))
      .map((node) => node.parentId)
      .filter(Boolean) as string[];
    if (parents.length) setExpanded((current) => new Set([...Array.from(current), ...parents]));
  };
  const courseLocked = plan.course_id === "data_structures_algorithms";
  const totalNodeCount = allDisplayNodes.length;
  const totalRelationCount = plan.edges.length
    + allDisplayNodes.filter((node) => node.detail).length
    + (plan.detail_edges || []).length;

  const graphContent = (
    <div className={`${fullscreen ? "fixed inset-0 z-[999] overflow-y-auto rounded-none" : "overflow-hidden rounded-[18px]"} border border-slate-800 bg-[#06101E] text-white shadow-[0_24px_80px_rgba(2,8,23,.2)]`}>
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
            <p className="mt-1 max-w-2xl text-xs leading-6 text-slate-400 sm:text-sm">课程主节点与细分概念组成可展开网络；点击主节点查看关系，使用节点右上角或“全部展开”控制复杂度。</p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              [totalNodeCount, "知识节点"],
              [totalRelationCount, "知识关系"],
              [expanded.size, "已展开"],
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
              onChange={(event) => updateQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                const first = byId[Array.from(queryHits)[0] || ""];
                if (first) selectDisplayNode(first);
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
            <button type="button" className={buttonClass(expanded.size === expandableIds.length && mode === "graph")} onClick={toggleAllDetails}>
              <Layers3 size={14} />{expanded.size === expandableIds.length ? "收起细节" : "全部展开"}
            </button>
            <button type="button" className={buttonClass(fullscreen)} onClick={() => setFullscreen((value) => !value)}>
              {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}{fullscreen ? "退出全屏" : "全屏模式"}
            </button>
            <button type="button" className={buttonClass(false)} onClick={reset}><RotateCcw size={14} />重置</button>
          </div>
        </div>
        <div className="mt-3 rounded-2xl border border-white/[0.07] bg-black/15 p-2.5 sm:p-3">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-1.5 px-0.5">
            <span className="text-[10px] font-black tracking-[0.16em] text-slate-400">章节导航</span>
            <span className="text-[10px] font-bold text-slate-500">{chapters.length} 个章节 · {totalNodeCount} 个知识节点 · 可展开</span>
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="按章节筛选知识图谱">
            <button type="button" onClick={() => { setChapter(ALL_CHAPTERS); setQuery(""); }} className={buttonClass(chapter === ALL_CHAPTERS)}>
              {ALL_CHAPTERS}
              <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-300">{totalNodeCount}</span>
            </button>
            {chapters.map((name) => (
              <button type="button" key={name} onClick={() => {
                setChapter(name);
                setQuery("");
                const chapterParents = plan.nodes.filter((node) => chapterOf(node) === name).map((node) => node.id);
                setExpanded((current) => new Set([...Array.from(current), ...chapterParents]));
              }} className={buttonClass(chapter === name)}>
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
                  : activeId
                    ? `关系聚焦 · ${byId[activeId]?.name || "知识点"}`
                    : expanded.size
                      ? `复杂全图 · 已展开 ${expanded.size} 组`
                      : "课程骨架图"}
          </div>
          <svg
            ref={svgRef}
            viewBox={`0 0 ${VIEW_W} ${layout.height}`}
            className="block h-auto min-h-[480px] w-full"
            role="img"
            aria-label={`${plan.course || "课程"}交互式知识图谱`}
            onClick={() => { setActiveDetailId(null); onSelect(null); }}
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
            <rect width={VIEW_W} height={layout.height} fill="url(#graph-background)" />
            <g opacity="0.15">
              {Array.from({ length: Math.min(72, Math.ceil(layout.height / 28)) }).map((_, index) => (
                <circle key={index} cx={(index * 167) % VIEW_W} cy={(index * 97) % layout.height} r={(index % 3) + 1} fill="#BFEFFF" />
              ))}
            </g>

            {displayEdges.map((edge, index) => {
              const from = positions[edge.from];
              const to = positions[edge.to];
              if (!from || !to) return null;
              const fromNode = byId[edge.from];
              const toNode = byId[edge.to];
              const selectedEdge = Boolean(activeId && (edge.from === activeId || edge.to === activeId));
              const routeEdge = mode === "route" && routeIds.has(edge.from) && routeIds.has(edge.to);
              const crossDetail = Boolean(edge.detail && fromNode?.parentId && toNode?.parentId && fromNode.parentId !== toNode.parentId);
              const dim = focus.active && !(focus.ids.has(edge.from) && focus.ids.has(edge.to));
              const stroke = routeEdge
                ? "#FFD166"
                : selectedEdge
                  ? "#E9FAFF"
                  : edge.detail
                    ? chapterColors[chapterOf(toNode || fromNode)] || "#6386A8"
                    : "#8293AA";
              const path = mode === "route"
                ? `M ${from.x + NODE_W / 2 - 8} ${from.y} C ${(from.x + to.x) / 2} ${from.y}, ${(from.x + to.x) / 2} ${to.y}, ${to.x - NODE_W / 2 + 8} ${to.y}`
                : `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
              return (
                <g key={`${edge.from}-${edge.to}-${index}`} opacity={dim ? 0.05 : selectedEdge || routeEdge ? 0.95 : edge.detail ? 0.42 : 0.3}>
                  <path d={path} fill="none" stroke={stroke} strokeWidth={selectedEdge || routeEdge ? 2.6 : edge.detail ? 1.05 : 1.25} strokeDasharray={crossDetail ? "5 4" : undefined} markerEnd="url(#knowledge-arrow)" />
                  {(selectedEdge || crossDetail) && edge.label && (
                    <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 7} textAnchor="middle" fontSize={selectedEdge ? "9" : "7.5"} fontWeight="800" fill="#EAFBFF" stroke="#06101E" strokeWidth="4" paintOrder="stroke">
                      {edge.label}
                    </text>
                  )}
                </g>
              );
            })}

            {displayNodes.map((node) => {
              const point = positions[node.id];
              if (!point) return null;
              const style = STATUS[node.status];
              const chapterColor = chapterColors[chapterOf(node)] || CHAPTER_COLORS[0];
              const dim = focus.active && !focus.ids.has(node.id);
              const isSelected = activeId === node.id;
              const isHit = queryHits.has(node.id);
              const isRoute = mode === "route" && routeIds.has(node.id);
              const isNext = plan.next_kp === node.id;
              const statusSymbol = node.status === "done" ? "✓" : node.status === "locked" ? "·" : "●";
              if (node.detail) {
                return (
                  <g
                    key={node.id}
                    transform={`translate(${point.x - DETAIL_NODE_W / 2}, ${point.y - DETAIL_NODE_H / 2})`}
                    opacity={dim ? 0.1 : 1}
                    className={`${draggingId === node.id ? "cursor-grabbing" : "cursor-grab"} touch-none transition-opacity`}
                    onClick={(event) => clickDisplayNode(event, node)}
                    onPointerDown={(event) => startDrag(event, node)}
                    onPointerMove={(event) => moveDrag(event, node)}
                    onPointerUp={(event) => endDrag(event, node)}
                    onPointerCancel={(event) => endDrag(event, node)}
                    role="button"
                    aria-label={`${node.name}，${node.relation || "细分知识点"}，属于 ${byId[node.parentId || ""]?.name || "课程"}，可拖拽`}
                  >
                    {(isSelected || isHit) && (
                      <rect x="-4" y="-4" width={DETAIL_NODE_W + 8} height={DETAIL_NODE_H + 8} rx="26" fill="none" stroke={isHit ? "#FFF5A6" : "#FFFFFF"} strokeWidth="2" filter="url(#node-glow)" />
                    )}
                    <rect width={DETAIL_NODE_W} height={DETAIL_NODE_H} rx="22" fill="#0A1C2C" stroke={chapterColor} strokeWidth={isSelected ? 2.4 : 1.3} />
                    <circle cx="14" cy="15" r="4" fill={chapterColor} />
                    <text x={DETAIL_NODE_W / 2 + 4} y="19" textAnchor="middle" fontSize="11" fontWeight="900" fill="#F4FAFF">{node.name}</text>
                    <text x={DETAIL_NODE_W / 2} y="33" textAnchor="middle" fontSize="7.5" fontWeight="700" fill="#8FA8BF">{node.relation || "细分概念"}</text>
                  </g>
                );
              }
              return (
                <Fragment key={node.id}>
                  <g
                    transform={`translate(${point.x - NODE_W / 2}, ${point.y - NODE_H / 2})`}
                    opacity={dim ? 0.12 : 1}
                    className={`${mode === "graph" ? (draggingId === node.id ? "cursor-grabbing" : "cursor-grab") : "cursor-pointer"} touch-none transition-opacity`}
                    onClick={(event) => clickDisplayNode(event, node)}
                    onPointerDown={(event) => startDrag(event, node)}
                    onPointerMove={(event) => moveDrag(event, node)}
                    onPointerUp={(event) => endDrag(event, node)}
                    onPointerCancel={(event) => endDrag(event, node)}
                    role="button"
                    aria-label={`${node.name}，${style.label}，掌握度 ${masteryLabel(node.mastery)}，${expanded.has(node.id) ? "细分节点已展开" : "可展开细分节点"}，可拖拽`}
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
                  {node.subtopics?.length ? (
                    <g
                      transform={`translate(${point.x + NODE_W / 2 - 8}, ${point.y - NODE_H / 2 + 8})`}
                      opacity={dim ? 0.12 : 1}
                      className="cursor-pointer touch-none transition-opacity"
                      onPointerDown={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setDraggingId(node.id);
                      }}
                      onPointerUp={(event) => {
                        event.stopPropagation();
                        setDraggingId(null);
                      }}
                      onPointerCancel={(event) => {
                        event.stopPropagation();
                        setDraggingId(null);
                      }}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        toggleExpanded(node.id);
                      }}
                      role="button"
                      aria-label={`${expanded.has(node.id) ? "收起" : "展开"}${node.name}的 ${node.subtopics.length} 个细分节点`}
                    >
                      <circle r="11" fill="#06101E" stroke={chapterColor} strokeWidth="1.4" />
                      <text y="3.5" textAnchor="middle" fontSize="13" fontWeight="900" fill={chapterColor}>{expanded.has(node.id) ? "−" : "+"}</text>
                    </g>
                  ) : null}
                </Fragment>
              );
            })}
          </svg>
          <div className="flex flex-wrap gap-x-4 gap-y-2 border-t border-white/10 px-4 py-3 text-[10px] text-slate-400 sm:px-6">
            {(Object.entries(STATUS) as [PathNode["status"], typeof STATUS[PathNode["status"]]][]).map(([key, item]) => (
              <span key={key} className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: item.border }} />{item.label}</span>
            ))}
            <span className="ml-auto">节点会轻微漂浮 · 拖拽可整理布局 · 主节点右上角 ± 展开/收起 · Esc 重置搜索</span>
          </div>
        </div>

        <aside className="bg-slate-950/25 p-5">
          {activeNode ? (
            <div>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black tracking-[0.16em] text-cyan-300">{activeNode.detail ? "DETAIL CONCEPT" : "NODE DETAIL"}</div>
                  <h3 className="mt-2 text-xl font-black">{activeNode.name}</h3>
                </div>
                <span className="rounded-full border px-2.5 py-1 text-[10px] font-bold" style={{ color: STATUS[activeNode.status].border, borderColor: `${STATUS[activeNode.status].border}55`, backgroundColor: `${STATUS[activeNode.status].border}14` }}>
                  {STATUS[activeNode.status].label}
                </span>
              </div>
              <p className="mt-2 text-xs leading-6 text-slate-400">
                {activeNode.chapter || "学习主题"}{activeNode.detail && activeNode.parentId ? ` · 属于 ${byId[activeNode.parentId]?.name || "课程主节点"}` : ""}
              </p>
              <p className="mt-3 text-sm leading-6 text-slate-300">{activeNode.desc || activeNode.reason}</p>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-white/10 bg-white/[0.045] p-3"><strong className="block text-lg">{masteryLabel(activeNode.mastery)}</strong><span className="text-[10px] text-slate-500">当前掌握度</span></div>
                <div className="rounded-xl border border-white/10 bg-white/[0.045] p-3"><strong className="block text-lg">{activeNode.difficulty}/5</strong><span className="text-[10px] text-slate-500">学习难度</span></div>
              </div>

              <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.045] p-3">
                <div className="flex items-center gap-2 text-xs font-black text-white"><BookOpen size={14} className="text-cyan-300" />{activeNode.detail ? "知识归属" : "为什么现在推荐"}</div>
                <p className="mt-2 text-xs leading-5 text-slate-400">{activeNode.reason}</p>
              </div>

              <div className="mt-4">
                <div className="text-[10px] font-black tracking-[0.14em] text-slate-500">前置知识</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {prerequisites.length ? prerequisites.map((node) => (
                    <button type="button" key={node.id} onClick={() => selectDisplayNode(node)} className="rounded-full border border-cyan-300/15 bg-cyan-300/[0.07] px-2.5 py-1.5 text-xs text-cyan-100 hover:border-cyan-300/50">{node.name}</button>
                  )) : <span className="text-xs text-slate-500">本课程起点，无课程内前置要求</span>}
                </div>
              </div>

              <div className="mt-4">
                <div className="text-[10px] font-black tracking-[0.14em] text-slate-500">学完可解锁</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {unlocks.length ? unlocks.map((node) => (
                    <button type="button" key={node.id} onClick={() => selectDisplayNode(node)} className="rounded-full border border-violet-300/15 bg-violet-300/[0.07] px-2.5 py-1.5 text-xs text-violet-100 hover:border-violet-300/50">{node.name}</button>
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
              <p className="mt-3 text-sm leading-7 text-slate-400">当前图谱只包含「{plan.course || "本课程"}」的知识点。默认展开课程主节点和细分概念，也可一键收起为课程骨架图。</p>
              <div className="mt-5 space-y-2 text-xs text-slate-300">
                <div className="flex items-center gap-2"><ShieldCheck size={14} className="text-emerald-300" />课程数据与题库、讲义使用同一知识点集合</div>
                <div className="flex items-center gap-2"><Route size={14} className="text-amber-300" />学习主线按你的掌握度实时重排</div>
                <div className="flex items-center gap-2"><Search size={14} className="text-cyan-300" />搜索会自动展开命中的细分概念并保留一跳关系</div>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );

  return fullscreen ? createPortal(graphContent, document.body) : graphContent;
}
