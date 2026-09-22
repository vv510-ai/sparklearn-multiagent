"use client";

import { useState } from "react";
import { ArrowLeft, Search } from "lucide-react";
import { apiPost } from "@/lib/api";
import Markdown from "@/components/chat/Markdown";

type Report = { question: string; markdown: string; status: string; limitations: string[]; plan: {questions: string[]; queries: string[]}; sources: { id:number; title:string; url:string; excerpt:string; kind:string; published_at:string|null; retrieved_at:string }[] };

export default function ResearchPanel({ notebookId, initialTopic, onBack }: { notebookId:string; initialTopic:string; onBack:()=>void }) {
  const [question,setQuestion] = useState(initialTopic);
  const [report,setReport] = useState<Report|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  async function run() {
    setBusy(true);setError("");setReport(null);
    try { setReport(await apiPost<Report>("/learning/research", {question,notebook_id:notebookId})); }
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <div className="notebook-content-scroll"><div className="notebook-content-heading"><div><span>RESEARCH WITH EVIDENCE</span><h1>深度研究</h1><p>拆解问题、检索资料、对照证据，再安排学习顺序。</p></div><button className="secondary-action" onClick={onBack}><ArrowLeft size={15}/>返回</button></div>
    <div className="mx-auto max-w-4xl space-y-5 p-5 pb-16">
      <form onSubmit={e=>{e.preventDefault();void run();}} className="rounded-2xl border border-[#DDE5D9] bg-white p-5"><label htmlFor="research-question" className="text-sm font-semibold">想深入研究什么？</label><textarea id="research-question" value={question} onChange={e=>setQuestion(e.target.value)} minLength={3} maxLength={600} required rows={3} className="mt-3 w-full rounded-xl border border-slate-200 p-3 text-sm" placeholder="例如：间隔重复为什么能帮助记忆？适用边界是什么？"/><p className="my-3 text-xs leading-6 text-slate-500">检索 Wikipedia 与 Crossref，最多 3 个角度、12 条来源。模型整理的是实际获取的导言、摘要与题录。研究结果保存到当前书本的资料归档。</p><button className="primary-action" disabled={busy}><Search size={16}/>{busy?"正在检索与对照，约需1–3分钟…":"开始研究"}</button></form>
      {error&&<p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {report&&<>
        <div role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{report.status==="complete"?"研究笔记已生成并保存":report.status==="offline"?"离线演示 · 仅展示计划":"证据或生成受限 · 请先查看来源"}</div>
        <details className="rounded-xl border bg-white p-4"><summary className="cursor-pointer text-sm font-semibold">查看研究计划与检索词</summary><ul className="mt-3 space-y-2 text-sm">{report.plan.questions.map((q,i)=><li key={i}>{i+1}. {q}</li>)}</ul><p className="mt-3 break-words text-xs text-slate-500">{report.plan.queries.join(" / ")}</p></details>
        <article className="rounded-2xl border border-[#DDE5D9] bg-white p-5"><Markdown text={report.markdown}/></article>
        <section className="space-y-3"><h2 className="font-bold">可核对的来源 · {report.sources.length}</h2>{report.sources.map(s=><article id={`research-source-${s.id}`} key={s.id} className="rounded-xl border border-[#DDE5D9] bg-white p-4"><a href={s.url} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-emerald-800 underline">[{s.id}] {s.title}</a><p className="my-2 text-xs text-slate-500">{s.kind} · 发布：{s.published_at||"未提供"} · 获取：{s.retrieved_at.slice(0,10)}</p><p className="whitespace-pre-wrap text-sm leading-7 text-slate-600">{s.excerpt||"只有题录，未将其作为全文证据。"}</p></article>)}</section>
        <ul className="space-y-2 text-xs leading-6 text-slate-500">{report.limitations.map((l,i)=><li key={i}>* {l}</li>)}</ul>
      </>}
    </div></div>;
}
