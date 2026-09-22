"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, KeyRound } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";

type Data = {
  revision: number;
  modules: Record<string, string>;
  models: Record<string, { provider: string; label: string; tier: string; cost: string; use: string }>;
  providers: Record<string, { name: string; base_url: string; docs: string; has_personal_key: boolean; has_server_key: boolean }>;
  routes: Record<string, string>; note: string; verified_at: string;
};
const control = "mt-2 block w-full rounded-xl border border-[#D8E1D8] bg-white px-3 py-3 text-sm text-slate-800 focus:outline-emerald-600";

export default function ModelSettings({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [routes, setRoutes] = useState<Record<string, string>>({});
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [secure, setSecure] = useState(false);
  const load = () => apiGet<Data>("/settings/models").then(d => { setData(d); setRoutes(d.routes); });
  useEffect(() => { setSecure(window.isSecureContext); void load().catch(() => setError("设置读取失败，请刷新页面重试")); }, []);
  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      const d = await apiPost<Data>("/settings/models", { routes, keys, revision: data?.revision ?? 0 });
      setData(d); setKeys({}); setMessage("已保存，下次生成即使用所选模型。");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function test(model: string) {
    if (!model) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const d = await apiPost<{ model: string; reply: string }>("/settings/models/test", { model });
      setMessage(`${d.model} 真实调用成功：${d.reply}`);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="notebook-content-scroll">
    <div className="notebook-content-heading"><div><span>YOUR MODELS</span><h1>模型设置</h1><p>按学习任务选择能力和费用，为当前账户填写 API。</p></div><button className="secondary-action" onClick={onBack}><ArrowLeft size={15}/>返回</button></div>
    <div className="mx-auto max-w-4xl space-y-6 p-5 pb-16">
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{message}</p>}
      {!data ? <p>正在读取模型设置…</p> : <>
        <p className="text-sm leading-7 text-slate-600">{data.note} ChatGPT 会员与 OpenAI API 分别计费。模型和价格核对日期：{data.verified_at}。</p>
        <section className="space-y-4 rounded-2xl border border-[#DDE5D9] bg-white/80 p-5"><h2 className="flex items-center gap-2 font-bold"><KeyRound size={18}/>连接模型服务</h2>
          {!secure && <p className="text-sm text-amber-800">当前连接为 HTTP。请通过 HTTPS 或本机 localhost 打开后填写个人密钥；现在可选择已有的服务端模型。</p>}
          {Object.entries(data.providers).map(([id,p]) => <div key={id} className="border-t border-slate-100 pt-4">
            <label className="block text-sm font-semibold" htmlFor={`key-${id}`}>{p.name} API Key</label>
            <p className="mt-1 break-all text-xs text-slate-500">{p.base_url} · {p.has_personal_key ? "已保存个人密钥" : p.has_server_key ? "可使用服务端密钥" : "待填写"}</p>
            <input id={`key-${id}`} className={control} type="password" autoComplete="off" maxLength={512} disabled={!secure || busy} value={keys[id] || ""} onChange={e => setKeys(k => { const next = {...k}; if (e.target.value) next[id] = e.target.value; else delete next[id]; return next; })} placeholder="填写新密钥；留空保留已保存值"/>
            <div className="mt-2 flex flex-wrap gap-4 text-xs"><a href={p.docs} target="_blank" rel="noopener noreferrer" className="text-emerald-700 underline">查看官方接口与价格</a>{p.has_personal_key && <button type="button" disabled={busy} onClick={() => setKeys(k => ({...k,[id]:""}))} className="text-red-700">{keys[id] === "" ? "保存后移除密钥" : "移除个人密钥"}</button>}</div>
          </div>)}
        </section>
        <section className="space-y-4 rounded-2xl border border-[#DDE5D9] bg-white/80 p-5"><h2 className="font-bold">各功能使用的模型</h2><p className="text-xs leading-6 text-slate-500">经济档适合日常学习，均衡档适合深入解释；复杂研究可选 Kimi K3 或 GPT-6 Astra。高价格不保证每道题更准确。</p>
          {Object.entries({default:"默认模型",...data.modules}).map(([id,label]) => <div key={id} className="border-t border-slate-100 pt-3"><label className="text-sm font-semibold" htmlFor={`model-${id}`}>{label}</label><div className="flex items-end gap-2"><select id={`model-${id}`} className={control} disabled={busy} value={routes[id] || ""} onChange={e=>setRoutes(r=>({...r,[id]:e.target.value}))}><option value="">{id === "default" ? "使用服务端默认模型" : "跟随默认模型"}</option>{Object.entries(data.models).map(([model,m])=><option key={model} value={model}>{m.label} · {m.tier}</option>)}</select><button className="secondary-action mb-1 shrink-0" type="button" disabled={busy || !routes[id] || Object.keys(keys).length > 0} onClick={()=>void test(routes[id])}>测试连接</button></div>{routes[id] && <p className="mt-2 text-xs leading-6 text-slate-500">{data.models[routes[id]]?.use}。{data.models[routes[id]]?.cost}</p>}</div>)}
        </section>
        <div className="flex flex-wrap items-center gap-3"><button type="button" className="primary-action" disabled={busy} onClick={()=>void save()}>{busy ? "正在处理…" : "保存模型设置"}</button><span className="text-xs text-slate-500">保存不调用模型；“测试连接”发送一次短请求，可能产生少量费用。</span></div>
      </>}
    </div>
  </div>;
}
