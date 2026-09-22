"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Check, KeyRound, Sparkles } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";

type Data = {
  revision: number;
  modules: Record<string, string>;
  models: Record<string, { provider: string; label: string; tier: string; cost: string; use: string }>;
  providers: Record<string, { name: string; base_url: string; docs: string; has_personal_key: boolean; has_server_key: boolean }>;
  routes: Record<string, string>; note: string; verified_at: string;
  server_routes: Record<string, string>;
  presets: { id: string; name: string; description: string; routes: Record<string, string>; available: boolean; unavailable_reason: string }[];
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
  async function save(nextRoutes = routes, success = "已保存，下次生成即使用所选模型。") {
    setBusy(true); setError(""); setMessage("");
    try {
      const d = await apiPost<Data>("/settings/models", { routes: nextRoutes, keys, revision: data?.revision ?? 0 });
      setData(d); setRoutes(d.routes); setKeys({}); setMessage(success);
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
  const savedRoutes = data && Object.keys(data.routes).length ? data.routes : data?.server_routes || {};
  const sameRoutes = (a: Record<string, string>, b: Record<string, string>) =>
    Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([k, v]) => b[k] === v);
  const pending = Object.keys(keys).length > 0 || !!data && !sameRoutes(routes, data.routes);
  return <div className="notebook-content-scroll">
    <div className="notebook-content-heading"><div><span>YOUR MODELS</span><h1>模型设置</h1><p>选择学习方案，模型会按任务自动切换。</p></div><button className="secondary-action" onClick={onBack}><ArrowLeft size={15}/>返回</button></div>
    <div className="mx-auto max-w-4xl space-y-6 p-5 pb-16">
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{message}</p>}
      {!data ? <p>正在读取模型设置…</p> : <>
        <section aria-labelledby="model-presets-title" className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-5">
          <h2 id="model-presets-title" className="flex items-center gap-2 font-bold text-emerald-950"><Sparkles size={18}/>选一次，之后自动搭配</h2>
          <p className="mt-2 text-sm leading-7 text-slate-600">{data.note}</p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {(data.presets || []).map(p => {
              const active = sameRoutes(savedRoutes, p.routes);
              return <article key={p.id} className={`flex flex-col rounded-xl border bg-white p-4 ${active ? "border-emerald-500" : "border-slate-200"}`}>
                <h3 className="flex flex-wrap items-center gap-2 font-semibold text-slate-900">{p.name}{p.id === "smart" && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">推荐</span>}</h3>
                <p className="mb-4 mt-2 flex-1 text-sm leading-6 text-slate-600">{p.description}</p>
                {!p.available && <p className="mb-3 text-xs leading-5 text-amber-800">{p.unavailable_reason}</p>}
                <button type="button" className={active ? "secondary-action" : "primary-action"} disabled={busy || pending || !p.available || active}
                  onClick={() => void save(p.routes, `已启用${p.name}，下次生成自动使用。`)}>
                  {active && <Check size={15}/>} {active ? `已启用${p.name}` : `启用${p.name}`}
                </button>
              </article>;
            })}
          </div>
          {pending && <p className="mt-3 text-sm text-amber-800">下方还有未保存的自定义设置，请先保存再切换方案。</p>}
          <p className="mt-3 text-xs leading-6 text-slate-500">点击即保存；切换方案本身不产生模型费用。新生成的内容使用新方案，已有内容保留。</p>
        </section>
        <details className="rounded-2xl border border-[#DDE5D9] bg-white/80 p-5">
          <summary className="cursor-pointer font-semibold text-slate-800">自定义模型与个人密钥</summary>
          <p className="mt-3 text-xs leading-6 text-slate-500">需要单独指定某项功能时再调整。个人密钥加密保存，仅对当前账户生效。ChatGPT 会员与 OpenAI API 分别计费。模型和价格核对日期：{data.verified_at}。</p>
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
        <div className="mt-5 flex flex-wrap items-center gap-3"><button type="button" className="primary-action" disabled={busy} onClick={()=>void save()}>{busy ? "正在处理…" : "保存模型设置"}</button><span className="text-xs text-slate-500">保存不调用模型；“测试连接”发送一次短请求，可能产生少量费用。</span></div>
        </details>
      </>}
    </div>
  </div>;
}
