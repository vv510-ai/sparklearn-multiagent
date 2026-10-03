"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import type { TextItem } from "pdfjs-dist/types/src/display/api";
import type { ExamKind } from "@/lib/cet6-exams";

function sectionBounds(items: TextItem[], kind: ExamKind) {
  const headings = { writing: /^Part\s+I\b/i, listening: /^Part\s+II\b/i, reading: /^Part\s+III\b/i, translation: /^Part\s+IV\b/i };
  const following = { writing: /^Part\s+II\b/i, listening: /^Part\s+III\b/i, reading: /^Part\s+IV\b/i, translation: /答案\s*速查/ };
  const heading = (i: number) => items.slice(i, i + 5).filter(item => Math.abs(item.transform[5] - items[i].transform[5]) < 3).map(item => item.str).join(" ").trim();
  const answerIndex = items.findIndex((_, i) => /答案\s*速查/.test(heading(i)));
  const limit = answerIndex < 0 ? items.length : answerIndex;
  const found = items.findIndex((_, i) => i < limit && headings[kind].test(heading(i)));
  const start = Math.max(0, found);
  const end = items.findIndex((_, i) => i >= start && i < limit && following[kind].test(heading(i)));
  return { start, end: end < 0 ? limit : end, cropTop: found >= 0 };
}

function readableText(items: TextItem[]) {
  const lines: string[] = []; let lastY: number | null = null;
  for (const item of items) {
    if (lastY !== null && Math.abs(lastY - item.transform[5]) > 3) lines.push("\n");
    lines.push(item.str); lastY = item.transform[5];
  }
  return lines.join(" ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** The browser reads the original URL directly. No server proxy, upload or persisted paper copy. */
export default function SourcePaperReader({ url, sourceUrl, pages, page, onPage, expectedHash, feedback, onSourceText, kind }: {
  url: string; sourceUrl: string; pages: number[]; page: number; onPage: (page: number) => void; expectedHash: string; feedback: boolean; onSourceText: (text: string) => void; kind: ExamKind;
}) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null), [error, setError] = useState("");
  const [mode, setMode] = useState<"text" | "page">("text"), [text, setText] = useState("");
  const [zoom, setZoom] = useState(1), [width, setWidth] = useState(600), [loading, setLoading] = useState(true), [retry, setRetry] = useState(0);
  const container = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let alive = true, pdf: PDFDocumentProxy | undefined;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    setError(""); setLoading(true);
    void (async () => {
      const lib = await import("pdfjs-dist");
      lib.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.mjs";
      const response = await fetch(url, { signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer" });
      if (!response.ok) throw new Error("来源站点暂时无法读取，请用原站链接打开试卷。");
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > 12_000_000) throw new Error("原卷大小与已核验版本不一致。");
      // crypto.subtle is absent on the project's HTTP production origin. PDF bytes
      // are pinned by immutable source commit; HTTPS adds a browser hash check.
      if (globalThis.crypto?.subtle) {
        const digest = await crypto.subtle.digest("SHA-256", bytes.slice(0));
        const hash = [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, "0")).join("");
        if (hash !== expectedHash) throw new Error("来源文件与答案绑定的版本不一致，请暂勿使用该文件作答。");
      }
      pdf = await lib.getDocument({ data: new Uint8Array(bytes), enableXfa: false }).promise;
      if (alive) setDocument(pdf); else await pdf.loadingTask.destroy();
    })().catch(e => { if (alive) { setError(e.name === "AbortError" ? "原站读取较慢，请重试或打开原站。已作答内容仍会保存。" : e.message); setLoading(false); } }).finally(() => clearTimeout(timeout));
    return () => { alive = false; clearTimeout(timeout); controller.abort(); if (pdf) void pdf.loadingTask.destroy(); };
  }, [url, expectedHash, retry]);
  useEffect(() => {
    if (!document) return;
    let alive = true;
    void Promise.all(pages.map(async number => {
      const leaf = await document.getPage(number), content = await leaf.getTextContent();
      const items = content.items.filter((item): item is TextItem => "str" in item);
      const bounds = sectionBounds(items, kind);
      return readableText(items.slice(bounds.start, bounds.end));
    })).then(values => { if (alive) onSourceText(values.join("\n")); }).catch(() => { /* The original-page view remains available. */ });
    return () => { alive=false; };
  }, [document, pages, onSourceText, kind]);
  useEffect(() => {
    const node = container.current; if (!node) return;
    const observer = new ResizeObserver(entries => { const next = entries[0].contentRect.width; if (next > 0) setWidth(next); });
    observer.observe(node); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!document) return;
    let active = true; let task: { cancel: () => void; promise: Promise<void> } | undefined;
    setLoading(true);
    void (async () => {
      const leaf = await document.getPage(page);
      const content = await leaf.getTextContent();
      const items = content.items.filter((item): item is TextItem => "str" in item);
      const bounds = sectionBounds(items, kind);
      if (!active) return;
      setText(readableText(items.slice(bounds.start, bounds.end)));
      if (mode === "page" && canvas.current) {
        const original = leaf.getViewport({ scale: 1 });
        const viewport = leaf.getViewport({ scale: (Math.max(200, width) / original.width) * zoom });
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        const cropTop = bounds.cropTop ? Math.max(0, viewport.convertToViewportPoint(0, items[bounds.start].transform[5])[1] - 24) : 0;
        const cropBottom = bounds.end < items.length ? viewport.convertToViewportPoint(0, items[bounds.end].transform[5])[1] - 20 : viewport.height;
        const cropHeight = Math.max(1, cropBottom - cropTop);
        const element = canvas.current;
        element.width = Math.ceil(viewport.width * ratio); element.height = Math.ceil(cropHeight * ratio);
        element.style.width = `${viewport.width}px`; element.style.height = `${cropHeight}px`;
        const context = element.getContext("2d");
        if (context) { task = leaf.render({ canvas: element, canvasContext: context, viewport, transform: [ratio,0,0,ratio,0,-cropTop*ratio] }); await task.promise; }
      }
      if (active) setLoading(false);
    })().catch(e => { if (active && e.name !== "RenderingCancelledException") { setError("本页暂时无法显示，可打开原站核对。答题记录不受影响。"); setLoading(false); } });
    return () => { active = false; task?.cancel(); };
  }, [document, page, mode, width, zoom, feedback, kind]);
  const index = pages.indexOf(page);
  return <section className="exam-source-reader" aria-label="原站试卷阅读区">
    <div className="exam-reader-toolbar"><label>原卷页码<select aria-label="原卷页码" value={page} onChange={e => onPage(Number(e.target.value))}>{pages.map(p => <option value={p} key={p}>第 {p} 页</option>)}</select></label><div className="exam-segment"><button aria-pressed={mode === "text"} onClick={() => setMode("text")}>清晰文字</button><button aria-pressed={mode === "page"} onClick={() => setMode("page")}>原版排版</button></div></div>
    <p className="exam-muted">题面从原站读取；文字模式方便阅读，换行或符号有疑问时请核对原版。</p>
    {mode === "page" && <div className="exam-reader-toolbar"><label>原版大小<select value={zoom} onChange={e => setZoom(Number(e.target.value))}><option value={1}>适合宽度</option><option value={1.4}>放大 140%</option><option value={1.8}>放大 180%</option></select></label></div>}
    {error && <div className="exam-error" role="alert"><p>{error}</p><button onClick={() => { setDocument(null); setRetry(n => n + 1); }}>重试读取原卷</button><a href={sourceUrl} target="_blank" rel="noreferrer">在原站打开试卷 ↗</a></div>}
    <div ref={container} className="exam-reader-body" aria-busy={loading}>
      {loading && <p role="status">正在读取原卷第 {page} 页…</p>}
      {mode === "text" ? <div lang="en" className="exam-source-text">{text}</div> : <div className="exam-canvas-scroll"><canvas ref={canvas} aria-label={`原卷第 ${page} 页；可切换清晰文字阅读`} /></div>}
    </div>
    <div className="exam-reader-toolbar"><button disabled={index <= 0} onClick={() => onPage(pages[index-1])}>上一页</button><span>{index+1} / {pages.length}</span><button disabled={index >= pages.length-1} onClick={() => onPage(pages[index+1])}>下一页</button><a href={sourceUrl} target="_blank" rel="noreferrer">原站来源 ↗</a></div>
  </section>;
}
