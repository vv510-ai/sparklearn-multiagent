"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Clapperboard, KeyRound, Loader2, PlugZap } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { ClaudeVideoSettings as Settings } from "@/lib/types";

type Config = Settings["config"];
const control = "mt-2 block w-full rounded-xl border border-[#D8E1D8] bg-white px-3 py-3 text-sm text-slate-800 focus:outline-emerald-600";

function authText(worker: Settings["worker"]) {
  if (!worker.auth.logged_in) return "Claude Code 未登录";
  const method = worker.auth.method === "claude.ai" ? "Claude 订阅" : worker.auth.method === "api_key" ? "API Key" : worker.auth.method || "已登录";
  return `已登录 · ${method}${worker.auth.plan ? ` · ${worker.auth.plan}` : ""}`;
}

function Segmented<T extends string | number>({ label, value, options, onChange, disabled }: {
  label: string; value: T; options: { id: T; label: string; note?: string }[]; onChange: (value: T) => void; disabled?: boolean;
}) {
  const current = options.find(option => option.id === value);
  return (
    <div className="border-t border-slate-100 pt-3">
      <p className="text-sm font-semibold">{label}</p>
      <div className="ll-seg mt-2" role="group" aria-label={label}>
        {options.map(option => (
          <button key={String(option.id)} type="button" aria-pressed={option.id === value} disabled={disabled}
            onClick={() => onChange(option.id)}>{option.label}</button>
        ))}
      </div>
      {current?.note && <p className="mt-2 text-xs text-slate-500">{current.note}</p>}
    </div>
  );
}

/** Owner-only settings for explanation videos made by the local official Claude Code. */
export default function ClaudeVideoSettings() {
  const [data, setData] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Partial<Config>>({});
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [secure, setSecure] = useState(false);

  const load = useCallback(() => apiGet<Settings>("/settings/claude-video").then(next => { setData(next); return next; }), []);
  useEffect(() => {
    setSecure(window.isSecureContext);
    void load().catch(() => setError("讲解视频设置读取失败，请刷新页面重试"));
    const timer = window.setInterval(() => void load().catch(() => undefined), 30000);
    return () => window.clearInterval(timer);
  }, [load]);
  useEffect(() => {
    if (!data?.test || !["queued", "claimed"].includes(data.test.status)) return;
    const timer = window.setTimeout(() => void load().catch(() => undefined), 3000);
    return () => window.clearTimeout(timer);
  }, [data, load]);

  if (!data) return error ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p> : null;
  if (!data.available) {
    return (
      <section className="rounded-2xl border border-[#DDE5D9] bg-white/70 p-5">
        <h2 className="flex items-center gap-2 font-bold text-slate-800"><Clapperboard size={18} />讲解视频 · Claude</h2>
        <p className="mt-2 text-sm leading-7 text-slate-600">{data.reason}</p>
      </section>
    );
  }

  const saved = data.config;
  const config = { ...saved, ...draft } as Config;
  const dirty = Object.keys(draft).length > 0 || apiKey !== "";
  const set = <K extends keyof Config>(key: K, value: Config[K]) =>
    setDraft(current => {
      const next = { ...current, [key]: value };
      if (saved[key] === value) delete next[key];
      return next;
    });
  const worker = data.worker;
  const testing = !!data.test && ["queued", "claimed"].includes(data.test.status);

  async function save(extra: Record<string, unknown> = {}, success = "已保存，下次生成讲解视频即使用新设置。") {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const body: Record<string, unknown> = { revision: saved.revision, config: draft, ...extra };
      if (apiKey && !("api_key" in extra)) body.api_key = apiKey;
      setData(await apiPost<Settings>("/settings/claude-video", body));
      setDraft({});
      setApiKey("");
      setMessage(success);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await apiPost("/settings/claude-video/test", {});
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="claude-video-title" className="space-y-4 rounded-2xl border border-emerald-200 bg-white/80 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="claude-video-title" className="flex items-center gap-2 font-bold text-emerald-950"><Clapperboard size={18} />讲解视频 · Claude</h2>
          <p className="mt-1 text-sm leading-7 text-slate-600">由你本机已登录的官方 Claude Code 制作：先出分镜，再配中文旁白、做动画、截图自查，最后渲染 1080P MP4。</p>
        </div>
        <span className={`ll-status ${worker.online ? "is-passed" : "is-unverified"}`}>
          <span aria-hidden>●</span>{worker.online ? (worker.busy ? "本机接入在线 · 正在制作" : "本机接入在线") : "本机接入未运行"}
        </span>
      </div>

      <div className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3 text-xs leading-6 text-slate-600">
        {worker.online || worker.cli_version ? (
          <>
            <p><strong className="text-slate-800">{worker.cli_version || "Claude Code"}</strong> · {authText(worker)}</p>
            <p>制作工具：HyperFrames {worker.tools.hyperframes || "未安装"} · ffmpeg {worker.tools.ffmpeg || "未安装"} · 配音 {worker.tools.tts || "未安装"}</p>
            {!worker.online && <p className="text-amber-800">接入程序现在没有运行：在 Mac 的 LearnLoop 启动菜单选择“启动讲解视频接入”。</p>}
          </>
        ) : (
          <p>还没有连接过本机接入程序。在 Mac 的 LearnLoop 启动菜单依次选择“登录 Claude”和“启动讲解视频接入”，保持窗口运行即可。</p>
        )}
      </div>

      <div className="border-t border-slate-100 pt-3">
        <label className="text-sm font-semibold" htmlFor="claude-video-model">制作模型</label>
        <select id="claude-video-model" className={control} disabled={busy} value={config.model}
          onChange={e => set("model", e.target.value)}>
          {data.options.models.map(model => <option key={model.id} value={model.id}>{model.label} · {model.note}</option>)}
        </select>
      </div>
      <Segmented label="思考强度" value={config.effort} options={data.options.efforts} disabled={busy} onChange={value => set("effort", value)} />
      <Segmented label="视频时长上限" value={config.max_seconds} disabled={busy}
        options={data.options.durations.map(seconds => ({ id: seconds, label: `${seconds} 秒`,
          note: "Claude 会按内容决定实际时长，宁短勿拖；时间越长，制作越久、越耗额度。" }))}
        onChange={value => set("max_seconds", value)} />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="border-t border-slate-100 pt-3">
          <label className="text-sm font-semibold" htmlFor="claude-video-voice">中文配音</label>
          <select id="claude-video-voice" className={control} disabled={busy} value={config.voice} onChange={e => set("voice", e.target.value)}>
            {data.options.voices.map(voice => <option key={voice.id} value={voice.id}>{voice.label} · {voice.note}</option>)}
          </select>
        </div>
        <Segmented label="画质" value={config.quality} options={data.options.qualities} disabled={busy} onChange={value => set("quality", value)} />
      </div>
      <label className="flex items-start gap-3 border-t border-slate-100 pt-3 text-sm">
        <input type="checkbox" className="mt-1 h-4 w-4 accent-emerald-700" checked={config.approve_storyboard} disabled={busy}
          onChange={e => set("approve_storyboard", e.target.checked)} />
        <span><strong className="font-semibold">制作前先给我看分镜</strong><br />
          <span className="text-xs leading-6 text-slate-500">打开后，Claude 写完分镜、录好旁白就暂停，在视频卡片上确认（可附画面意见）后再开始制作。</span></span>
      </label>

      <div className="border-t border-slate-100 pt-3">
        <p className="flex items-center gap-2 text-sm font-semibold"><KeyRound size={15} />接入方式</p>
        <div className="ll-seg mt-2" role="group" aria-label="接入方式">
          <button type="button" aria-pressed={config.access === "subscription"} disabled={busy} onClick={() => set("access", "subscription")}>Claude 订阅（推荐）</button>
          <button type="button" aria-pressed={config.access === "api_key"} disabled={busy} onClick={() => set("access", "api_key")}>Anthropic API Key</button>
        </div>
        {config.access === "subscription" ? (
          <p className="mt-2 text-xs leading-6 text-slate-500">使用你在本机官方 Claude Code 里登录的 Pro / Max 订阅额度；本页不需要也不会保存任何 Claude 登录信息。</p>
        ) : (
          <div className="mt-2 space-y-2">
            <p className="text-xs leading-6 text-slate-500">按 Anthropic 控制台用量计费。密钥加密保存，只在制作时交给本机接入程序。{saved.has_api_key ? "已保存一个密钥，留空即保留。" : ""}</p>
            {!secure && <p className="text-xs text-amber-800">当前连接不是 HTTPS 或 localhost，暂不能填写密钥。</p>}
            <input className={control} type="password" autoComplete="off" maxLength={300} disabled={!secure || busy} value={apiKey}
              onChange={e => setApiKey(e.target.value.trim())} placeholder={saved.has_api_key ? "填写新密钥以替换" : "sk-ant-…"} />
            <label className="block text-xs text-slate-600" htmlFor="claude-video-budget">单条视频费用上限（美元）</label>
            <input id="claude-video-budget" className={control} type="number" min={1} max={50} step={1} disabled={busy} value={config.budget_usd}
              onChange={e => set("budget_usd", Number(e.target.value) || 1)} />
            {saved.has_api_key && (
              <button type="button" className="text-xs text-red-700" disabled={busy}
                onClick={() => void save({ api_key: "", config: { ...draft, access: "subscription" } }, "已移除 API Key，改用 Claude 订阅。")}>
                移除已保存的 API Key
              </button>
            )}
          </div>
        )}
      </div>

      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{message}</p>}
      {data.test && (
        <p role="status" className={`rounded-xl p-3 text-sm ${data.test.status === "succeeded" ? "bg-emerald-50 text-emerald-800" : testing ? "bg-slate-50 text-slate-600" : "bg-amber-50 text-amber-900"}`}>
          {testing ? <><Loader2 size={14} className="mr-1 inline animate-spin" />正在请本机 Claude 回复一句话…</>
            : data.test.status === "succeeded" ? <><CheckCircle2 size={14} className="mr-1 inline" />{data.test.model} 连接成功：{data.test.reply}</>
            : `连接测试没有成功：${data.test.detail || "本机接入程序没有响应"}`}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="primary-action" disabled={busy || !dirty} onClick={() => void save()}>
          {busy ? "正在处理…" : "保存视频设置"}
        </button>
        <button type="button" className="secondary-action" disabled={busy || dirty || testing} onClick={() => void test()}>
          <PlugZap size={15} />测试连接
        </button>
        <span className="text-xs text-slate-500">{data.active_jobs ? `有 ${data.active_jobs} 条视频正在排队或制作；新设置从下一条开始生效。` : "测试连接会请 Claude 回复一句话，使用极少的订阅额度。"}</span>
      </div>
      <p className="text-xs leading-6 text-slate-500">{data.note}</p>
    </section>
  );
}
