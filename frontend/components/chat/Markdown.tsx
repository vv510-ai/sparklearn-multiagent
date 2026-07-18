"use client";
/** Markdown 渲染:react-markdown + GFM。
 *  1) ```mermaid 代码块经 CDN 渲染为图,失败时给学习者友好提示;
 *  2) 传入 citeBase 时,正文中的 [^n] 会渲染成可点击引用芯片,
 *     锚点跳转到资源卡底部「引用来源」对应条目 —— 引用溯源的可视化证据链。 */
import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getMermaid } from "@/lib/cdn";
import { withoutCodeBlocks } from "@/lib/learningContent";

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
    <div className="my-2 rounded-lg border border-orange-200 bg-orange-50 p-3 text-xs text-orange-900">
      图表暂时无法显示，请先阅读上下文中的文字步骤；系统不会向学习者展示图表源码。
    </div>
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

const CITE_RE = /\[\^(\d{1,2})\]/g;

/** 出处保留在后台核验数据中，学习正文只渲染知识内容。 */
function withoutCites(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child !== "string") return child;
    CITE_RE.lastIndex = 0;
    return child.replace(CITE_RE, "");
  });
}

export default function Markdown({
  text,
  streaming = false,
  allowCodeBlocks = false,
}: {
  text: string;
  streaming?: boolean;
  /** 只有明确的代码学习场景才开启。 */
  allowCodeBlocks?: boolean;
  /** 兼容资源数据；普通学习界面不展示出处。 */
  citeBase?: string;
  citations?: string[];
}) {
  const cite = (children: React.ReactNode) => withoutCites(children);
  const learnerText = allowCodeBlocks ? text : withoutCodeBlocks(text, true);
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
            if (!allowCodeBlocks) return null;
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
        {learnerText}
      </ReactMarkdown>
    </div>
  );
}
