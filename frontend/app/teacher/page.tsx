"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, Download, FileUp, Plus, Users } from "lucide-react";
import AuthGate, { AuthUser } from "@/components/auth/AuthGate";
import { apiGet, apiPost, UNAUTHORIZED_EVENT } from "@/lib/api";
import { BRAND } from "@/lib/brand";

type Study = {id: string; title: string; course: string; mode: "demo" | "field"; protocol: string};
type Report = {
  study: Study; participants: number; observations: Record<string, unknown>[]; independent_rate: number | null;
  difference_in_gains: number | null; interpretation: string; verification: string;
  summary: {arm: string; phase: string; n: number; mean_accuracy: number | null}[];
  paired: {arm: string; n: number; mean_gain: number | null}[];
  heatmap: {knowledge_point: string; n: number; accuracy: number | null; errors: Record<string, number>}[];
};
const percent = (n: number | null) => n == null ? "待采集" : `${(100*n).toFixed(1)}%`;
const armName: Record<string,string> = {intervention: "平台组", control: "对照组"};
const phaseName: Record<string,string> = {pre: "前测", post: "后测", delayed: "延迟测"};

function download(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:"application/json"}));
  const a = document.createElement("a"); a.href=url; a.download=name; a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function sampleData() {
  return {observations: ["intervention","control"].flatMap((arm, index) => ["pre","post","delayed"].map((phase,p) => ({
    participant:`DEMO_${index+1}`, arm, phase, knowledge_point:"二叉树遍历",
    correct: [[4,7,6],[4,5,4]][index][p], total:10, independent:8, minutes:12,
    observed_on:["2026-08-01","2026-08-29","2026-09-05"][p], consent:true,
    provenance:"合成演示样例，不代表真实学生或效果", data_kind:"demo", errors:["遍历顺序混淆"],
  })))};
}

export default function TeacherPage() {
  const [user,setUser]=useState<AuthUser|null>(null);
  const [checking,setChecking]=useState(true);
  const [studies,setStudies]=useState<Study[]>([]);
  const [report,setReport]=useState<Report|null>(null);
  const [selected,setSelected]=useState("");
  const [title,setTitle]=useState("");
  const [course,setCourse]=useState("数据结构与算法");
  const [mode,setMode]=useState<"demo"|"field">("demo");
  const [protocol,setProtocol]=useState("");
  const [importData,setImportData]=useState<{observations: Record<string,unknown>[]} | null>(null);
  const [fileName,setFileName]=useState("");
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [showCreate,setShowCreate]=useState(false);
  const refresh = useCallback(()=>apiGet<{studies: Study[]}>("/pilot/studies").then(r=>setStudies(r.studies)),[]);
  useEffect(()=>{
    apiGet<AuthUser>("/auth/me").then(setUser).catch(()=>setUser(null)).finally(()=>setChecking(false));
    const expired=()=>{setUser(null);setReport(null);setStudies([]);};
    window.addEventListener(UNAUTHORIZED_EVENT,expired);
    return ()=>window.removeEventListener(UNAUTHORIZED_EVENT,expired);
  },[]);
  useEffect(()=>{if(user){refresh().catch(()=>setError("试点列表加载失败"));}},[user,refresh]);
  useEffect(()=>{
    setReport(null);setImportData(null);setFileName("");
    if(!selected)return;
    let active=true;
    apiGet<Report>(`/pilot/studies/${selected}`).then(r=>{if(active)setReport(r);}).catch(()=>{if(active)setError("试点数据加载失败");});
    return ()=>{active=false;};
  },[selected]);

  async function create(e:FormEvent) {
    e.preventDefault();setBusy(true);setError("");setMessage("");
    try {const study=await apiPost<Study>("/pilot/studies",{title,course,mode,protocol});await refresh();setSelected(study.id);setShowCreate(false);setTitle("");setMessage("试点已建立，可以导入获同意的匿名观测记录。");}
    catch(e){setError(e instanceof Error?e.message:"创建失败");}finally{setBusy(false);}
  }
  async function removeStudy() {
    if (!report || !window.confirm(`删除“${report.study.title}”及本账户下的全部观测？请先导出需要留存的记录。`)) return;
    setBusy(true); setError("");
    try {
      const result = await fetch(`/api/pilot/studies/${selected}`, { method: "DELETE" });
      if (!result.ok) throw new Error("删除失败，请刷新登录状态后重试");
      setSelected(""); setReport(null); setImportData(null); await refresh(); setMessage("试点及其观测记录已删除。");
    } catch (e) { setError(e instanceof Error ? e.message : "删除失败"); } finally { setBusy(false); }
  }
  async function chooseFile(e:ChangeEvent<HTMLInputElement>) {
    setError("");setImportData(null);const file=e.target.files?.[0];if(!file)return;
    try {if(file.size>2*1024*1024)throw new Error("文件不得超过 2 MB");const parsed=JSON.parse(await file.text());if(!Array.isArray(parsed.observations)||!parsed.observations.length||parsed.observations.length>1000)throw new Error("需要 1 到 1000 条 observations 记录");setImportData(parsed);setFileName(file.name);}
    catch(e){setError(e instanceof Error?e.message:"文件格式错误");}
  }
  async function importRows() {
    if(!selected||!importData)return;setBusy(true);setError("");setMessage("");
    try {const result=await apiPost<{inserted:number;duplicates:number}>(`/pilot/studies/${selected}/observations`,importData);setReport(await apiGet<Report>(`/pilot/studies/${selected}`));setImportData(null);setFileName("");setMessage(`已导入 ${result.inserted} 条，跳过 ${result.duplicates} 条完全相同的记录。`);}
    catch(e){setError(e instanceof Error?e.message:"导入失败");}finally{setBusy(false);}
  }
  if(checking)return <main className="grid min-h-screen place-items-center bg-[#F5F7F3] text-emerald-950" role="status">正在打开教学研究…</main>;
  if(!user)return <AuthGate onAuthenticated={setUser}/>;
  const inputClass="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100";
  return <main className="min-h-screen bg-[#F5F7F3] text-[#19372E]"><div className="mx-auto max-w-7xl px-5 py-7 sm:px-9">
    <nav className="flex flex-wrap items-center justify-between gap-4 border-b border-emerald-950/10 pb-6"><Link href="/" className="flex items-center gap-3 font-bold"><BookOpen size={24}/>{BRAND.name}<span className="text-xs font-normal text-slate-500">教学研究</span></Link><Link href="/" className="flex items-center gap-1 text-sm"><ArrowLeft size={15}/>回到学习</Link></nav>
    <header className="flex flex-wrap items-end justify-between gap-6 py-10"><div><p className="text-xs font-semibold tracking-[.2em] text-emerald-700">CLASSROOM EVIDENCE</p><h1 className="mt-3 text-3xl font-bold sm:text-4xl">看见共性薄弱点，验证教学改变。</h1><p className="mt-4 max-w-3xl text-sm leading-7 text-slate-600">建立课程试点，导入获同意的匿名观测，按同一受试者比较前后表现。数据仅对当前账户可见。</p></div><button onClick={()=>setShowCreate(!showCreate)} className="inline-flex items-center gap-2 rounded-full bg-[#173F34] px-5 py-3 text-sm font-semibold text-white"><Plus size={16}/>建立试点</button></header>
    <div className="mb-5 text-xs text-slate-500">{user.name}的私有研究空间</div>
    {showCreate&&<form onSubmit={create} className="mb-7 grid gap-5 rounded-2xl border border-[#DDE5D9] bg-white p-6 md:grid-cols-2"><label className="text-sm font-semibold">试点名称<input className={inputClass} required minLength={2} maxLength={120} value={title} onChange={e=>setTitle(e.target.value)} placeholder="例如：秋季数据结构课程试点"/></label><label className="text-sm font-semibold">课程<input className={inputClass} required minLength={2} maxLength={120} value={course} onChange={e=>setCourse(e.target.value)}/></label><label className="text-sm font-semibold">数据类型<select className={inputClass} value={mode} onChange={e=>setMode(e.target.value as "demo"|"field")}><option value="demo">演示试点（合成数据）</option><option value="field" disabled={user.demo}>现场试点（真实采集，待核验）</option></select></label><label className="text-sm font-semibold">研究方案<textarea className={inputClass} required minLength={10} maxLength={4000} rows={3} value={protocol} onChange={e=>setProtocol(e.target.value)} placeholder="记录分组方法、前后测题组、周期、知情同意及原始资料存放位置。"/></label><div className="md:col-span-2"><button disabled={busy} className="rounded-full bg-[#173F34] px-6 py-2.5 text-sm text-white disabled:opacity-50">{busy?"正在保存…":"保存试点"}</button></div></form>}
    {error&&<div role="alert" className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
    {message&&<div role="status" className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{message}</div>}
    <div className="grid gap-6 lg:grid-cols-[250px_1fr]"><aside className="self-start rounded-2xl border border-[#DDE5D9] bg-white p-4"><h2 className="px-2 py-2 text-sm font-bold">我的课程试点</h2>{studies.length===0?<p className="px-2 py-6 text-sm leading-7 text-slate-500">还没有试点。先记录方案，再开始采集。</p>:studies.map(s=><button key={s.id} disabled={busy} onClick={()=>{setSelected(s.id);setError("");setMessage("");}} className={`mt-2 w-full rounded-xl p-3 text-left ${selected===s.id?"bg-[#EAF0E7]":"hover:bg-slate-50"}`}><span className="block text-sm font-semibold">{s.title}</span><span className="mt-1 block text-xs text-slate-500">{s.course} · {s.mode==="demo"?"演示":"现场观测"}</span></button>)}</aside>
      <section className="min-w-0">{!report?<div className="grid min-h-80 place-items-center rounded-2xl border border-dashed border-[#CDDACC] p-8 text-center"><div><Users size={34} className="mx-auto text-emerald-600"/><h2 className="mt-4 text-xl font-semibold">从一个真实教学问题开始</h2><p className="mt-3 text-sm leading-7 text-slate-500">选择或建立试点后，查看前后测、独立作答和共性错因。</p></div></div>:<>
        <div className={`mb-5 rounded-xl border p-4 text-sm ${report.study.mode==="demo"?"border-amber-200 bg-amber-50 text-amber-900":"border-blue-200 bg-blue-50 text-blue-900"}`}>{report.verification}</div>
        <div className="grid gap-3 sm:grid-cols-3">{[{label:"匿名受试者",value:String(report.participants)},{label:"独立作答比例",value:percent(report.independent_rate)},{label:"两组增量之差",value:report.difference_in_gains==null?"待配对":`${(100*report.difference_in_gains).toFixed(1)} 个百分点`}].map(s=><div key={s.label} className="rounded-2xl border border-[#DDE5D9] bg-white p-5"><p className="text-xs text-slate-500">{s.label}</p><p className="mt-3 text-2xl font-bold">{s.value}</p></div>)}</div>
        <section className="mt-5 rounded-2xl border border-[#DDE5D9] bg-white p-6"><h2 className="text-lg font-bold">前测 · 后测 · 延迟测</h2><p className="mt-2 text-xs leading-6 text-slate-500">每名受试者每阶段贡献一个正确率；缺测显示“待采集”。以下均为描述统计。</p><div className="mt-5 overflow-x-auto"><table className="w-full min-w-[400px] text-left text-sm"><thead><tr className="border-b border-slate-200"><th className="py-3 font-semibold">组别</th>{Object.entries(phaseName).map(([id,name])=><th key={id} className="py-3 font-semibold">{name}</th>)}</tr></thead><tbody>{Object.entries(armName).map(([arm,name])=><tr key={arm} className="border-b border-slate-100"><th className="py-5 font-medium">{name}</th>{["pre","post","delayed"].map(phase=>{const cell=report.summary.find(s=>s.arm===arm&&s.phase===phase);return <td key={phase} className="py-5"><strong>{percent(cell?.mean_accuracy??null)}</strong><span className="mt-1 block text-xs text-slate-400">n = {cell?.n??0}</span></td>;})}</tr>)}</tbody></table></div><div className="mt-4 space-y-2 text-xs text-slate-500">{report.paired.map(p=><p key={p.arm}>{armName[p.arm]}：{p.n} 人在同一知识点完成前后配对，平均变化 {p.mean_gain==null?"待采集":`${(100*p.mean_gain).toFixed(1)} 个百分点`}。</p>)}</div></section>
        <section className="mt-5 rounded-2xl border border-[#DDE5D9] bg-white p-6"><h2 className="text-lg font-bold">共性薄弱点</h2>{report.heatmap.length===0?<p className="mt-4 text-sm text-slate-500">还没有观测记录。</p>:report.heatmap.map(k=><div key={k.knowledge_point} className="mt-5"><div className="flex justify-between text-sm"><span>{k.knowledge_point}</span><span>{percent(k.accuracy)} · 后测 n={k.n}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-emerald-600" style={{width:`${(k.accuracy??0)*100}%`}}/></div><p className="mt-2 text-xs leading-6 text-slate-500">{Object.entries(k.errors).map(([e,n])=>`${e}：${n} 人`).join("；")||"暂无共性错因标签"}{k.accuracy!=null&&k.accuracy<.6?"。建议教师复核该知识点的题目与教学讲解。":""}</p></div>)}</section>
        <section className="mt-5 rounded-2xl border border-[#DDE5D9] bg-white p-6"><h2 className="text-lg font-bold">导入与留存</h2><p className="mt-2 text-xs leading-6 text-slate-500">导入 JSON，受试者仅用匿名编号。每条记录需含采集日期、分组、阶段、知情同意和原始凭证位置；演示记录不能导入现场试点。</p><div className="mt-5 flex flex-wrap gap-3"><button onClick={()=>download("演示导入样例_非真实效果.json",sampleData())} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm"><Download size={16}/>下载格式样例</button><label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm"><FileUp size={16}/>选择观测文件<input type="file" accept="application/json,.json" className="sr-only" onChange={chooseFile} disabled={busy}/></label><button onClick={()=>download("试点观测与汇总.json",report)} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm"><Download size={16}/>导出当前记录</button></div>{importData&&<div className="mt-4 rounded-xl bg-emerald-50 p-4 text-sm"><p className="break-all">{fileName} · {importData.observations.length} 条记录待校验</p><button disabled={busy} onClick={importRows} className="mt-3 rounded-full bg-[#173F34] px-5 py-2 text-white disabled:opacity-50">{busy?"正在校验并导入…":"校验并导入"}</button></div>}<details className="mt-5 text-sm"><summary className="cursor-pointer text-slate-600">查看本次研究方案</summary><p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-slate-600">{report.study.protocol}</p></details></section>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 text-xs text-slate-500"><p>按研究方案留存数据；撤回或到期后可先导出，再删除试点。</p><button onClick={removeStudy} disabled={busy} className="rounded-full border border-red-200 px-4 py-2 text-red-700 disabled:opacity-50">删除当前试点</button></div>
        <p className="py-6 text-xs leading-7 text-slate-500">{report.interpretation}</p>
      </>}</section>
    </div>
  </div></main>;
}
