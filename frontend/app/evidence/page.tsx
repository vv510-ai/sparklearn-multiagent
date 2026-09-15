"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, BookOpen, CheckCircle2, FileCheck2, Users } from "lucide-react";
import { apiGet } from "@/lib/api";
import { BRAND } from "@/lib/brand";

type Register = {
  track: string; as_of: string; eligibility: string; interpretation: string; source: string;
  groups: {id: string; name: string; weight: number; page: number}[];
  criteria: {id: string; group: string; title: string; status: string; baseline: string; required_evidence: string; implementation: string}[];
  necessary_condition: {text: string}; changes: string[];
  validation: {backend_tests?: number; frontend_build?: string; tested_on?: string; note?: string};
};

export default function EvidencePage() {
  const [data, setData] = useState<Register | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("growth");
  const load = () => { setError(""); apiGet<Register>("/competition").then(setData).catch(() => setError("评审资料暂时无法加载，请重试。")); };
  useEffect(load, []);
  return <main className="min-h-screen bg-[#F5F7F3] text-[#19372E]">
    <div className="mx-auto max-w-6xl px-5 py-7 sm:px-10">
      <nav className="flex flex-wrap items-center justify-between gap-4 border-b border-emerald-950/10 pb-6">
        <Link href="/" className="flex items-center gap-3 font-bold"><span className="rounded-xl bg-[#163F34] p-2.5 text-white"><BookOpen size={22}/></span><span>{BRAND.name}<span className="ml-2 text-xs font-normal text-slate-500">LEARNLOOP</span></span></Link>
        <div className="flex gap-5 text-sm"><Link href="/teacher" className="hover:underline">教师工作台</Link><Link href="/" className="flex items-center gap-1 hover:underline"><ArrowLeft size={15}/>学习工作台</Link></div>
      </nav>
      <section className="grid gap-8 py-14 lg:grid-cols-[1.35fr_1fr]">
        <div><p className="text-xs font-bold tracking-[.2em] text-emerald-700">EVIDENCE & APPLICATION</p><h1 className="mt-5 text-4xl font-bold leading-tight sm:text-5xl">学习是否发生，<br/><span className="text-[#61977D]">让证据来回答。</span></h1><p className="mt-6 max-w-xl text-base leading-8 text-slate-600">从每一道独立作答，到一次真实课堂试点。这里公开项目的验证范围、评分条款与待补充材料。</p>
          <div className="mt-7 flex flex-wrap gap-3"><Link href="/review" className="inline-flex items-center gap-2 rounded-full bg-[#173F34] px-6 py-3 text-sm font-semibold text-white">体验学习闭环 <ArrowRight size={16}/></Link><Link href="/teacher" className="inline-flex items-center gap-2 rounded-full border border-emerald-950/20 px-6 py-3 text-sm"><Users size={16}/>开展课堂试点</Link></div>
        </div>
        <div className="self-center rounded-3xl border border-[#DDE5D9] bg-white p-7 shadow-sm"><span className="text-xs font-semibold text-emerald-700">当前验证阶段</span><h2 className="mt-3 text-2xl font-semibold">产品原型与工程验证</h2><p className="mt-3 text-sm leading-7 text-slate-600">真实课堂学习效果仍待完成研究。演示中的掌握度变化用于说明系统行为。</p><div className="mt-5 border-t border-slate-100 pt-4 text-sm"><p className="flex gap-2"><CheckCircle2 size={17} className="text-emerald-600"/>学习证据、补救与复测已有实现</p><p className="mt-3 flex gap-2"><FileCheck2 size={17} className="text-amber-600"/>调研、课堂效果与商业证明待补证</p></div></div>
      </section>
      {error && <div role="alert" className="rounded-2xl bg-amber-50 p-5 text-amber-900">{error}<button onClick={load} className="ml-4 underline">重试</button></div>}
      {!data && !error && <p role="status">正在加载评分与证据台账…</p>}
      {data && <>
        <section className="rounded-3xl bg-[#EAF0E7] p-6 sm:p-8"><div className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs text-slate-500">2026 中国国际大学生创新大赛</p><h2 className="mt-2 text-2xl font-bold">{data.track}</h2></div><span className="text-xs text-slate-500">核验日期 {data.as_of}</span></div><p className="mt-4 text-sm leading-7 text-slate-600">{data.eligibility}</p>
          <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">{data.groups.map(group => <button key={group.id} onClick={()=>setTab(group.id)} aria-pressed={tab===group.id} className={`rounded-2xl border p-5 text-left transition ${tab===group.id ? "border-[#173F34] bg-[#173F34] text-white" : "border-transparent bg-white hover:border-emerald-400"}`}><p className="text-sm">{group.name}</p><p className="mt-2 text-3xl font-semibold">{group.weight}<span className="ml-1 text-xs font-normal opacity-60">分</span></p></button>)}</div>
        </section>
        <section className="py-10"><h2 className="text-2xl font-bold">逐条对照，逐项留证</h2><p className="mt-3 text-sm leading-7 text-slate-500">{data.interpretation}</p><div className="mt-6 space-y-3">{data.criteria.filter(c=>c.group===tab).map(c=><article key={c.id} className="rounded-2xl border border-[#DDE5D9] bg-white p-6"><div className="flex items-center justify-between gap-3"><h3 className="font-bold"><span className="mr-3 font-mono text-xs text-emerald-600">{c.id}</span>{c.title}</h3><span className={`shrink-0 rounded-full px-3 py-1 text-xs ${c.status==="partial"?"bg-emerald-50 text-emerald-800":"bg-amber-50 text-amber-800"}`}>{c.status==="partial"?"已有部分依据":"待补证"}</span></div><div className="mt-4 grid gap-5 md:grid-cols-2"><div><p className="text-xs font-semibold text-slate-400">目前依据</p><p className="mt-2 text-sm leading-7 text-slate-700">{c.baseline}</p></div><div><p className="text-xs font-semibold text-slate-400">满足条款仍需</p><p className="mt-2 text-sm leading-7 text-slate-700">{c.required_evidence}</p></div></div></article>)}</div></section>
        <section className="grid gap-5 pb-8 md:grid-cols-2"><div className="rounded-2xl bg-white p-6"><h2 className="font-bold">2026 规则变化的落实方向</h2><ul className="mt-4 space-y-3 text-sm text-slate-600">{data.changes.map((change,i)=><li key={change}><span className="mr-3 text-emerald-600">0{i+1}</span>{change}</li>)}</ul></div><div className="rounded-2xl bg-white p-6"><h2 className="font-bold">工程验证记录</h2><p className="mt-4 text-sm leading-7 text-slate-600">{data.validation.backend_tests != null ? `${data.validation.backend_tests} 项后端测试通过。` : "改造版本验证记录待归档。"} {data.validation.frontend_build === "passed" ? "前端生产构建通过。" : ""}</p><p className="mt-3 text-sm leading-7 text-slate-500">{data.validation.note || "代码与接口检查证明已测范围内的工程行为；真实学习效果另行验证。"}</p></div></section>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6"><h2 className="font-bold text-amber-900">报名与材料的必要条件</h2><p className="mt-3 text-sm leading-7 text-amber-900">{data.necessary_condition.text}</p></div>
        <footer className="py-8 text-xs leading-6 text-slate-500">{data.source}</footer>
      </>}
    </div>
  </main>;
}
