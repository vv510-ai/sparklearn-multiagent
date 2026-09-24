"use client";
/** Markmap 交互脑图:markmap-lib/view 经 CDN 渲染;失败降级为可读大纲。
 *  浅色企业主题 + 个性化标注图例(✅已掌握 / ⚠️待巩固 / 🔒先修未解锁,来自学习画像)。 */
import { useEffect, useRef, useState } from "react";
import { getMarkmap } from "@/lib/cdn";

const MARKMAP_LIB_ESM_URL = "https://cdn.jsdelivr.net/npm/markmap-lib@0.17.2/+esm";
const MARKMAP_VIEW_ESM_URL = "https://cdn.jsdelivr.net/npm/markmap-view@0.17.2/+esm";

const MARKMAP_JSON_OPTIONS = {
  color: ["#0F6B50", "#7c3aed", "#059669", "#d97706", "#db2777", "#0d9488"],
  colorFreezeLevel: 2,
  duration: 220,
  fitRatio: 0.9,
  initialExpandLevel: 6,
  maxInitialScale: 1.35,
  maxWidth: 220,
  nodeMinHeight: 20,
  paddingX: 12,
  spacingHorizontal: 78,
  spacingVertical: 14,
};

type D3SelectionLike = {
  attr: (...args: unknown[]) => D3SelectionLike;
  call: (...args: unknown[]) => D3SelectionLike;
  on: (...args: unknown[]) => D3SelectionLike;
  remove: () => D3SelectionLike;
  select: (...args: unknown[]) => D3SelectionLike;
  selectAll: (...args: unknown[]) => D3SelectionLike;
  style: (...args: unknown[]) => D3SelectionLike;
};

function instantTransition(selection: D3SelectionLike) {
  const chain = (sel: D3SelectionLike) => ({
    attr: (...args: unknown[]) => {
      sel.attr(...args);
      return chain(sel);
    },
    call: (...args: unknown[]) => {
      sel.call(...args);
      return chain(sel);
    },
    end: () => Promise.resolve(),
    on: (...args: unknown[]) => {
      sel.on(...args);
      return chain(sel);
    },
    remove: () => {
      sel.remove();
      return chain(sel);
    },
    select: (...args: unknown[]) => chain(sel.select(...args)),
    selectAll: (...args: unknown[]) => chain(sel.selectAll(...args)),
    style: (...args: unknown[]) => {
      sel.style(...args);
      return chain(sel);
    },
  });
  return chain(selection);
}

type MarkmapInstance = {
  setData: (data: unknown) => void | Promise<void>;
  destroy?: () => void;
  transition: (selection: D3SelectionLike) => unknown;
  fit?: () => void;
};

type MarkmapRuntime = {
  Markmap: { create: (el: SVGElement, opts: object | undefined, data: unknown) => unknown };
  Transformer: new () => { transform: (md: string) => { root: unknown } };
  deriveOptions?: (opts: object) => object;
};

async function loadMarkmapRuntime(): Promise<MarkmapRuntime> {
  try {
    return (await getMarkmap()) as MarkmapRuntime;
  } catch {
    const [lib, view] = await Promise.all([
      import(/* webpackIgnore: true */ MARKMAP_LIB_ESM_URL),
      import(/* webpackIgnore: true */ MARKMAP_VIEW_ESM_URL),
    ]);
    return { ...lib, ...view } as MarkmapRuntime;
  }
}

const LEGEND: [string, string][] = [
  ["✅", "已掌握"],
  ["⚠️", "可学习 · 待巩固"],
  ["🔒", "先修未解锁"],
];

function outlineItems(markdown: string) {
  return markdown
    .split("\n")
    .map((line) => {
      const heading = /^(#{1,6})\s+(.+)$/.exec(line.trim());
      const bullet = /^[-*+]\s+(.+)$/.exec(line.trim());
      if (heading) return { depth: heading[1].length - 1, text: heading[2] };
      if (bullet) return { depth: 2, text: bullet[1] };
      return null;
    })
    .filter((item): item is { depth: number; text: string } => Boolean(item?.text));
}

export default function Markmap({ markdown }: { markdown: string }) {
  const ref = useRef<SVGSVGElement>(null);
  const mmRef = useRef<MarkmapInstance | null>(null);
  const nodeCount = outlineItems(markdown).length;
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [activeNode, setActiveNode] = useState("");
  const [tall, setTall] = useState(() => nodeCount > 16);
  const [touring, setTouring] = useState(false);
  const hasPersonalMarks = /[✅⚠🔒]/.test(markdown);

  useEffect(() => {
    let alive = true;
    setFailed(false);
    setReady(false);
    (async () => {
      try {
        const mm = await loadMarkmapRuntime();
        const { root } = new mm.Transformer().transform(markdown);
        const options = {
          autoFit: true,
          pan: true,
          zoom: true,
          ...(mm.deriveOptions ? mm.deriveOptions(MARKMAP_JSON_OPTIONS) : MARKMAP_JSON_OPTIONS),
        };
        if (!alive || !ref.current) return;
        ref.current.innerHTML = "";
        const markmap = mm.Markmap.create(ref.current, options, null) as MarkmapInstance;
        markmap.transition = instantTransition;
        mmRef.current = markmap;
        await markmap.setData(root);
        if (alive) { await markmap.fit?.(); setReady(true); }
      } catch {
        if (alive) {
          setFailed(true);
          setTouring(false);
        }
      }
    })();
    return () => {
      alive = false;
      mmRef.current?.destroy?.();
      mmRef.current = null;
    };
  }, [markdown]);

  useEffect(() => {
    // 高度切换后重新适配视图
    const t = window.setTimeout(() => mmRef.current?.fit?.(), 60);
    return () => window.clearTimeout(t);
  }, [tall]);

  useEffect(() => {
    const svg = ref.current;
    if (!svg || !touring) {
      svg?.querySelectorAll(".markmap-node-active").forEach((node) => node.classList.remove("markmap-node-active"));
      return;
    }

    let index = 0;
    const highlightNext = () => {
      const nodes = Array.from(svg.querySelectorAll<SVGGElement>(".markmap-node"));
      if (!nodes.length) return;
      nodes.forEach((node) => node.classList.remove("markmap-node-active"));
      const current = nodes[index % nodes.length];
      current.classList.add("markmap-node-active");
      setActiveNode(`${index % nodes.length + 1} / ${nodes.length}：${current.textContent || ""}`);
      index += 1;
    };
    mmRef.current?.fit?.();
    highlightNext();
    const timer = window.setInterval(highlightNext, 4000);
    return () => {
      window.clearInterval(timer);
      svg.querySelectorAll(".markmap-node-active").forEach((node) => node.classList.remove("markmap-node-active"));
    };
  }, [markdown, touring]);

  if (!markdown.trim()) {
    return (
      <div className="rounded-lg border border-orange-200 bg-orange-50 px-3 py-3 text-sm text-orange-800">
        <div className="font-bold">脑图内容为空</div>
        <div className="mt-1 text-xs leading-5 text-orange-700">当前资源没有可渲染的 Markdown 层级。</div>
      </div>
    );
  }

  if (failed) {
    const items = outlineItems(markdown);
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="mb-2 text-xs text-slate-500">脑图暂时无法加载，已转换为可读大纲。</div>
        <div className="max-h-72 space-y-1 overflow-auto rounded-md border border-slate-200 bg-white p-3 text-xs leading-6 text-slate-700">
          {items.map((item, index) => (
            <div
              key={`${item.text}-${index}`}
              className={item.depth === 0 ? "font-bold text-slate-900" : item.depth === 1 ? "font-semibold text-slate-800" : "text-slate-600"}
              style={{ paddingLeft: `${Math.min(item.depth, 3) * 16}px` }}
            >
              {item.depth > 0 && <span className="mr-2 text-emerald-600">•</span>}
              {item.text}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="markmap-light rounded-lg border border-slate-200 bg-white p-2">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2 px-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 font-semibold text-emerald-700">
            全图 {nodeCount} 个知识节点
          </span>
          {hasPersonalMarks ? (
            <>
              <span className="font-semibold text-slate-600">画像标注</span>
              {LEGEND.map(([mark, label]) => (
                <span key={mark} className="inline-flex items-center gap-1">
                  <span>{mark}</span>
                  {label}
                </span>
              ))}
            </>
          ) : (
            <span className="text-[11px] text-slate-400">拖拽平移 · 滚轮缩放 · 点击节点折叠 · 连线缓慢流动</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            disabled={!ready}
            onClick={() => setTouring((value) => !value)}
            aria-pressed={touring}
            className={`rounded-md border px-2 py-1 text-[11px] font-semibold transition ${touring ? "border-cyan-300 bg-cyan-50 text-cyan-800" : "border-slate-200 bg-white text-slate-600 hover:border-cyan-200 hover:text-cyan-700"}`}
          >
            {touring ? "停止逐个查看" : "逐个查看"}
          </button>
          <button
            disabled={!ready}
            onClick={() => mmRef.current?.fit?.()}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 transition hover:border-emerald-200 hover:text-emerald-700"
          >
            适配视图
          </button>
          <button
            onClick={() => setTall((v) => !v)}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 transition hover:border-emerald-200 hover:text-emerald-700"
          >
            {tall ? "恢复高度" : "放大查看"}
          </button>
        </div>
      </div>
      {!ready && <p role="status" className="p-2 text-xs text-slate-500">正在加载导图…</p>}
      {touring && <p role="status" className="rounded bg-emerald-50 p-2 text-sm text-emerald-900">{activeNode}</p>}
      <svg
        ref={ref}
        className={`markmap-canvas w-full rounded-md bg-slate-50/60 transition-all ${tall ? "h-[32rem]" : "h-80"} [&_circle]:!stroke-[2px]`}
      />
    </div>
  );
}
