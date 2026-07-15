"use client";
/** Markdown 渲染:react-markdown + GFM。
 *  1) ```mermaid 代码块经 CDN 渲染为图,失败降级源码,生产页面不白屏;
 *  2) 传入 citeBase 时,正文中的 [^n] 会渲染成可点击引用芯片,
 *     锚点跳转到资源卡底部「引用来源」对应条目 —— 引用溯源的可视化证据链。 */
import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getMermaid } from "@/lib/cdn";

let seq = 0;

function looksLikeMermaidError(svg: string) {
  return /syntax error in text|error-icon|mermaid version/i.test(svg);
}

function simpleFlowSteps(code: string): string[] | null {
  if (!/^\s*(?:flowchart|graph)\s+(?:LR|RL|TB|TD|BT)\b/m.test(code)) return null;
  const labels = new Map<string, string>();
  const labelPattern = /\b([A-Za-z][\w-]*)\s*\[([^\]]+)\]/g;
  let labelMatch: RegExpExecArray | null;
  while ((labelMatch = labelPattern.exec(code))) labels.set(labelMatch[1], labelMatch[2].replace(/^['"]|['"]$/g, ""));

  const edges: [string, string][] = [];
  const edgePattern = /\b([A-Za-z][\w-]*)(?:\s*\[[^\]]+\])?\s*--+>?\s*\b([A-Za-z][\w-]*)/g;
  let edgeMatch: RegExpExecArray | null;
  while ((edgeMatch = edgePattern.exec(code))) edges.push([edgeMatch[1], edgeMatch[2]]);
  if (!edges.length) return null;

  const incoming = new Map<string, number>();
  const outgoing = new Map<string, string>();
  for (const [from, to] of edges) {
    incoming.set(to, (incoming.get(to) || 0) + 1);
    if (outgoing.has(from) || (incoming.get(to) || 0) > 1) return null;
    outgoing.set(from, to);
  }
  const ids = Array.from(new Set(edges.flat()));
  const root = ids.find((id) => !incoming.has(id));
  if (!root) return null;
  const ordered: string[] = [];
  const seen = new Set<string>();
  for (let current: string | undefined = root; current && !seen.has(current); current = outgoing.get(current)) {
    seen.add(current);
    ordered.push(labels.get(current) || current);
  }
  return ordered.length === ids.length ? ordered : null;
}

function MermaidFallback({ code }: { code: string }) {
  const steps = simpleFlowSteps(code);
  if (steps) {
    return (
      <div className="my-2 rounded-lg border border-emerald-200 bg-emerald-50/60 p-3">
        <div className="mb-2 text-[11px] font-semibold text-emerald-700">简图模式</div>
        <div className="flex flex-wrap items-center gap-2">
          {steps.map((step, index) => (
            <React.Fragment key={`${step}-${index}`}>
              {index > 0 && <span className="text-emerald-500" aria-hidden>→</span>}
              <span className="rounded-md border border-emerald-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700">{step}</span>
            </React.Fragment>
          ))}
        </div>
      </div>
    );
  }
  return (
    <details className="my-2 rounded-lg border border-orange-200 bg-orange-50 p-3 text-xs text-orange-900">
      <summary className="cursor-pointer font-semibold">图表暂以源码保留</summary>
      <pre className="mt-2 max-h-40 overflow-auto rounded-md !bg-[#0f172a] p-3 text-slate-100"><code>{code}</code></pre>
    </details>
  );
}

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    setFailed(false);
    if (ref.current) ref.current.innerHTML = "";
    (async () => {
      try {
        const m = await getMermaid();
        await m.parse?.(code);
        const { svg } = await m.render(`mmd-${++seq}`, code);
        if (looksLikeMermaidError(svg)) throw new Error("mermaid syntax error");
        if (alive && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (alive) setFailed(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [code]);
  if (failed) return <MermaidFallback code={code} />;
  return <div ref={ref} className="my-2 max-h-80 overflow-auto rounded-lg border border-slate-200 bg-white p-2" />;
}

/** 正文引用芯片:[^n] → 可点击上标,跳到底部第 n 条来源。 */
function CiteChip({ n, base, title }: { n: number; base: string; title?: string }) {
  return (
    <a
      href={`#${base}-cite-${n}`}
      title={title ? `引用来源 ${n}:${title}` : `跳到引用来源 ${n}`}
      className="mx-0.5 inline-flex -translate-y-[3px] items-center rounded border border-emerald-200 bg-emerald-50 px-1 font-mono text-[10px] font-bold leading-4 text-emerald-700 no-underline transition hover:border-emerald-300 hover:bg-emerald-100"
    >
      {n}
    </a>
  );
}

const CITE_RE = /\[\^(\d{1,2})\]/g;

/** 把子节点里的纯文本按 [^n] 切开并插入 CiteChip;元素节点原样保留。 */
function withCites(children: React.ReactNode, base?: string, citations?: string[]): React.ReactNode {
  if (!base) return children;
  return React.Children.map(children, (child, ci) => {
    if (typeof child !== "string" || !child.includes("[^")) return child;
    const parts: React.ReactNode[] = [];
    let last = 0;
    let m: RegExpExecArray | null;
    CITE_RE.lastIndex = 0;
    while ((m = CITE_RE.exec(child))) {
      if (m.index > last) parts.push(child.slice(last, m.index));
      const n = Number(m[1]);
      parts.push(<CiteChip key={`c${ci}-${m.index}`} n={n} base={base} title={citations?.[n - 1]} />);
      last = m.index + m[0].length;
    }
    if (last < child.length) parts.push(child.slice(last));
    return parts;
  });
}

export default function Markdown({
  text,
  streaming = false,
  citeBase,
  citations,
}: {
  text: string;
  streaming?: boolean;
  /** 提供后启用 [^n] 引用芯片;锚点前缀通常传资源 id */
  citeBase?: string;
  /** 引用来源列表,用于芯片 hover 提示 */
  citations?: string[];
}) {
  const cite = (children: React.ReactNode) => withCites(children, citeBase, citations);
  return (
    <div className={`prose-spark text-[13.5px] ${streaming ? "caret" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props) {
            const { className, children } = props as { className?: string; children?: React.ReactNode };
            const lang = /language-(\w+)/.exec(className || "")?.[1];
            const raw = String(children ?? "").replace(/\n$/, "");
            if (lang === "mermaid" && !streaming) return <MermaidBlock code={raw} />;
            if (lang)
              return (
                <pre>
                  <code>{raw}</code>
                </pre>
              );
            return <code>{raw}</code>;
          },
          pre: ({ children }) => <>{children}</>,
          p: ({ children }) => <p>{cite(children)}</p>,
          li: ({ children }) => <li>{cite(children)}</li>,
          strong: ({ children }) => <strong>{cite(children)}</strong>,
          em: ({ children }) => <em>{cite(children)}</em>,
          td: ({ children }) => <td>{cite(children)}</td>,
          th: ({ children }) => <th>{cite(children)}</th>,
          h1: ({ children }) => <h1>{cite(children)}</h1>,
          h2: ({ children }) => <h2>{cite(children)}</h2>,
          h3: ({ children }) => <h3>{cite(children)}</h3>,
          h4: ({ children }) => <h4>{cite(children)}</h4>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
