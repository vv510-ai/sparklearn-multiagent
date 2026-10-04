"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import type { TextItem } from "pdfjs-dist/types/src/display/api";
import { isReading, type ExamKind } from "@/lib/cet6-exams";
import { cutSection, normalizeHeadings, passageView, pdfPageText } from "@/lib/exam-source";

function sectionBounds(items: TextItem[], kind: ExamKind, analysisOnly = false) {
  if (analysisOnly) return {start:0,end:items.length,cropTop:false};
  const headings = { writing: /^Part\s+I\b/i, listening: /^Part\s+II\b/i, reading: /^Part\s+III\b/i, reading_cloze: /^Part\s+III\b|^Section\s+A\b/i, reading_matching: /^Section\s+B\b/i, reading_careful: /^Section\s+C\b/i, translation: /^Part\s+IV\b/i };
  const following = { writing: /^Part\s+II\b/i, listening: /^Part\s+III\b/i, reading: /^Part\s+IV\b/i, reading_cloze: /^Section\s+B\b/i, reading_matching: /^Section\s+C\b/i, reading_careful: /^Part\s+IV\b/i, translation: /答案\s*速查/ };
  const heading = (i: number) => normalizeHeadings(items.slice(i, i + 5).filter(item => Math.abs(item.transform[5] - items[i].transform[5]) < 3).map(item => item.str).join(" ").trim());
  const answerIndex = items.findIndex((_, i) => /答案\s*速查/.test(heading(i)));
  const limit = answerIndex < 0 ? items.length : answerIndex;
  const found = items.findIndex((_, i) => i < limit && headings[kind].test(heading(i)));
  const start = Math.max(0, found);
  const end = items.findIndex((_, i) => i >= start && i < limit && following[kind].test(heading(i)));
  return { start, end: end < 0 ? limit : end, cropTop: found >= 0 };
}

const readableText = pdfPageText;
const ignoreText = () => {};

/** The browser reads the original URL directly. No server proxy, upload or persisted paper copy. */
export default function SourcePaperReader({ url, sourceUrl, pages, page, onPage, expectedHash, feedback, onSourceText, kind, question=26, answerUrl, answerHash, answerPages=1, referenceRequest, pageRequest, analysisOnly=false, scanned=false, renderPassage }: {
  url: string; sourceUrl: string; pages: number[]; page: number; onPage: (page: number) => void; expectedHash: string; feedback: boolean; onSourceText: (text: string) => void; kind: ExamKind;
  question?: number; answerUrl?: string; answerHash?: string; answerPages?: number; referenceRequest?: {page:number;sequence:number}; pageRequest?: number; analysisOnly?: boolean; scanned?: boolean;
  renderPassage?: (paragraphs: string[]) => ReactNode;
}) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null), [error, setError] = useState("");
  const [mode, setMode] = useState<"text" | "page">(analysisOnly || scanned ? "page" : "text"), [text, setText] = useState("");
  const [fullText,setFullText] = useState(""), [showAnalysis,setShowAnalysis] = useState(false), [answerPage,setAnswerPage] = useState(1);
  const [zoom, setZoom] = useState(1), [width, setWidth] = useState(600), [loading, setLoading] = useState(true), [retry, setRetry] = useState(0);
  const container = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const pageKey=pages.join(",");
  useEffect(()=>{if(referenceRequest && feedback){setShowAnalysis(true);setAnswerPage(referenceRequest.page);}},[referenceRequest,feedback]);
  useEffect(()=>{if(pageRequest){setShowAnalysis(false);setMode(/\.docx(?:$|\?)/i.test(url)?"text":"page");}},[pageRequest,url]);
  useEffect(() => {
    let alive = true, pdf: PDFDocumentProxy | undefined;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000);
    setError(""); setLoading(true);
    void (async () => {
      const lib = await import("pdfjs-dist");
      lib.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.mjs";
      const response = await fetch(url, { signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer" });
      if (!response.ok) throw new Error("来源站点暂时无法读取，请用原站链接打开试卷。");
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > 60_000_000) throw new Error("来源文件超过阅读器的大小限制。");
      // crypto.subtle is absent on the project's HTTP production origin. PDF bytes
      // are pinned by immutable source commit; HTTPS adds a browser hash check.
      if (globalThis.crypto?.subtle && expectedHash) {
        const digest = await crypto.subtle.digest("SHA-256", bytes.slice(0));
        const hash = [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, "0")).join("");
        if (hash !== expectedHash) throw new Error("来源文件与答案绑定的版本不一致，请暂勿使用该文件作答。");
      }
      if (/\.docx(?:$|\?)/i.test(url)) {
        const {unzipSync,strFromU8}=await import("fflate");
        const content=unzipSync(new Uint8Array(bytes),{filter:file=>file.name==="word/document.xml" && file.originalSize<3_000_000})["word/document.xml"];
        if(!content)throw new Error("来源 Word 缺少可读正文。");
        const xml=new DOMParser().parseFromString(strFromU8(content),"application/xml"),ns="http://schemas.openxmlformats.org/wordprocessingml/2006/main";
        const raw=[...xml.getElementsByTagNameNS(ns,"p")].map(p=>[...p.getElementsByTagNameNS(ns,"t")].map(t=>t.textContent||"").join("")).join("\n\n");
        const source=cutSection(raw,kind);
        if(alive){setFullText(source);onSourceText(source);setLoading(false);}return;
      }
      pdf = await lib.getDocument({ data: new Uint8Array(bytes), enableXfa: false }).promise;
      if (alive) setDocument(pdf); else await pdf.loadingTask.destroy();
    })().catch(e => { if (alive) { setError(e.name === "AbortError" ? "原站读取较慢，请重试或打开原站。已作答内容仍会保存。" : e.message); setLoading(false); } }).finally(() => clearTimeout(timeout));
    return () => { alive = false; clearTimeout(timeout); controller.abort(); if (pdf) void pdf.loadingTask.destroy(); };
  }, [url, expectedHash, retry, kind, onSourceText]);
  useEffect(() => {
    if (!document) return;
    let alive = true;
    void Promise.all(pageKey.split(",").map(async value => {
      const number=Number(value);
      const leaf = await document.getPage(number), content = await leaf.getTextContent();
      const items = content.items.filter((item): item is TextItem => "str" in item);
      // Cut sections only after joining all pages: a continuation page can contain
      // a later heading and must keep its leading paragraph text.
      return readableText(items);
    })).then(values => { if (alive) { const source=analysisOnly?values.join("\n\n"):cutSection(values.join("\n\n"),kind);setFullText(source);onSourceText(source);if(!source.trim())setMode("page"); } }).catch(() => { /* The original-page view remains available. */ });
    return () => { alive=false; };
  }, [document, pageKey, onSourceText, kind, analysisOnly]);
  useEffect(() => {
    const node = container.current; if (!node) return;
    const observer = new ResizeObserver(entries => { const next = entries[0].contentRect.width; if (next > 0) setWidth(next); });
    observer.observe(node); return () => observer.disconnect();
  }, [showAnalysis]);
  useEffect(() => {
    if (!document) return;
    let active = true; let task: { cancel: () => void; promise: Promise<void> } | undefined;
    setLoading(true);
    void (async () => {
      const leaf = await document.getPage(page);
      const content = await leaf.getTextContent();
      const items = content.items.filter((item): item is TextItem => "str" in item);
      const bounds = sectionBounds(items, kind, analysisOnly);
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
  }, [document, page, mode, width, zoom, feedback, kind, analysisOnly, showAnalysis]);
  const index = pages.indexOf(page);
  const view=passageView(fullText || text,kind,question);
  if(showAnalysis && feedback && answerUrl) return <section className="exam-source-reader"><button onClick={()=>setShowAnalysis(false)}>返回题目材料</button><p className="exam-muted">第三方参考解析，非官方答案。请对照原文判断，答案仍可能有误。</p><SourcePaperReader url={answerUrl} sourceUrl={answerUrl} pages={Array.from({length:answerPages},(_,i)=>i+1)} page={answerPage} onPage={setAnswerPage} expectedHash={answerHash||""} feedback onSourceText={ignoreText} kind={kind} analysisOnly /></section>;
  return <section className="exam-source-reader" aria-label="原站试卷阅读区">
    <div className="exam-reader-toolbar"><strong>{analysisOnly ? "来源解析" : isReading(kind) ? kind === "reading_careful" ? `阅读材料 · 第 ${question>=51?2:1} 篇` : "阅读材料" : "原卷题目要求"}</strong><div className="exam-segment">{!scanned&&<button aria-pressed={mode === "text"} onClick={() => setMode("text")}>清晰文字</button>}{document&&<button aria-pressed={mode === "page"} onClick={() => setMode("page")}>原版排版</button>}{feedback&&answerUrl&&<button onClick={()=>setShowAnalysis(true)}>来源解析</button>}</div></div>
    <p className="exam-muted">{scanned ? "本卷为扫描件，请直接对照原版作答；可放大和切换页码。" : "题面从第三方来源直接读取；按自然段阅读，有疑问时可核对原版。"}</p>
    {mode === "page" && <label>原卷页码<select aria-label="原卷页码" value={page} onChange={e => onPage(Number(e.target.value))}>{pages.map(p => <option value={p} key={p}>第 {p} 页</option>)}</select></label>}
    {mode === "page" && <div className="exam-reader-toolbar"><label>原版大小<select value={zoom} onChange={e => setZoom(Number(e.target.value))}><option value={1}>适合宽度</option><option value={1.4}>放大 140%</option><option value={1.8}>放大 180%</option></select></label></div>}
    {error && <div className="exam-error" role="alert"><p>{error}</p><button onClick={() => { setDocument(null); setRetry(n => n + 1); }}>重试读取原卷</button><a href={sourceUrl} target="_blank" rel="noreferrer">在原站打开试卷 ↗</a></div>}
    <div ref={container} className="exam-reader-body" aria-busy={loading}>
      {loading && <p role="status">正在读取原卷第 {page} 页…</p>}
      {mode === "text" ? <>{view.directions&&<details className="exam-directions"><summary>查看本题型说明</summary><p lang="en">{view.directions}</p></details>}{renderPassage && !analysisOnly ? renderPassage(view.paragraphs) : <div lang="en" className="exam-source-text">{(analysisOnly ? (fullText||text).split(/\n\n/) : view.paragraphs).map((p,i)=><p key={i}>{p}</p>)}</div>}</> : <div className="exam-canvas-scroll"><canvas ref={canvas} aria-label={`原卷第 ${page} 页；可切换清晰文字阅读`} /></div>}
    </div>
    <div className="exam-reader-toolbar">{mode === "page"&&<><button disabled={index <= 0} onClick={() => onPage(pages[index-1])}>上一页</button><span>{index+1} / {pages.length}</span><button disabled={index >= pages.length-1} onClick={() => onPage(pages[index+1])}>下一页</button></>}<a href={sourceUrl} target="_blank" rel="noreferrer">第三方来源文件 ↗</a></div>
  </section>;
}
