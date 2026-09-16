"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpenCheck, RefreshCw, Star } from "lucide-react";
import { Badge, Notice, Stat } from "@/components/ui";
import ConfidencePicker, { type ConfidenceLevel } from "@/components/resource/ConfidencePicker";
import { USER_ID, apiGet, apiPost } from "@/lib/api";
import type { PathPlan } from "@/lib/types";

interface MistakeItem {
  id: number;
  quiz_resource_id: string;
  question_id: string;
  kp: string;
  kp_name: string;
  status: "pending" | "resolved";
  favorite: boolean;
  reason: string;
  error_tags: string[];
  last_answer: string;
  expected: string;
  explain: string;
  stage: number;
  lapse_count: number;
  due_at: string;
  question: {
    id: string;
    type: "single" | "fill" | "judge" | "design" | "complexity";
    stem: string;
    options: string[];
    difficulty: number;
  };
}

interface MistakeResponse {
  items: MistakeItem[];
  summary: { total: number; pending: number; resolved: number; favorite: number };
}

interface PracticeResult {
  correct: boolean;
  expected: string;
  explain: string;
  error_tags: string[];
  schedule?: { interval_days?: number | null; status?: string };
  report?: { path?: PathPlan; profile_version?: number };
}

type Filter = "all" | "pending" | "favorite" | "resolved";

function choiceLabel(options: string[], answer: string) {
  const letter = answer.trim().toUpperCase();
  if (!/^[A-D]$/.test(letter)) return answer || "未作答";
  const option = options[letter.charCodeAt(0) - 65];
  return option ? `${letter}. ${option.replace(/^[A-D][.、：:\s]*/, "")}` : letter;
}

export default function MistakeBook({ onEvaluated, notebookId = "" }: { notebookId?: string; onEvaluated?: (report?: { path?: PathPlan; profile_version?: number }) => void }) {
  const [data, setData] = useState<MistakeResponse | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState<number | null>(null);
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState<ConfidenceLevel>();
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Record<number, PracticeResult>>({});
  const startedAt = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await apiGet<MistakeResponse>(`/eval/mistake-book?user_id=${USER_ID}&limit=150&notebook_id=${encodeURIComponent(notebookId)}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "错题本加载失败");
    } finally {
      setLoading(false);
    }
  }, [notebookId]);

  useEffect(() => { void load(); }, [load]);

  const items = useMemo(() => (data?.items || []).filter((item) => (
    filter === "all" || (filter === "favorite" ? item.favorite : item.status === filter)
  )), [data?.items, filter]);

  async function toggleFavorite(item: MistakeItem) {
    const favorite = !item.favorite;
    setData((current) => current ? {
      ...current,
      items: current.items.map((saved) => saved.id === item.id ? { ...saved, favorite } : saved),
      summary: { ...current.summary, favorite: Math.max(0, current.summary.favorite + (favorite ? 1 : -1)) },
    } : current);
    try {
      await apiPost(`/eval/mistake-book/${item.id}/favorite`, { user_id: USER_ID, favorite });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "收藏状态保存失败");
      void load();
    }
  }

  function begin(itemId: number) {
    setActiveId(itemId);
    setAnswer("");
    setConfidence(undefined);
    startedAt.current = Date.now();
  }

  async function submit(item: MistakeItem) {
    if (!answer.trim() || !confidence) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiPost<PracticeResult>(`/eval/mistake-book/${item.id}/practice`, {
        user_id: USER_ID,
        answer,
        confidence,
        seconds: startedAt.current ? Math.max(1, Math.round((Date.now() - startedAt.current) / 1000)) : 0,
      });
      setResults((current) => ({ ...current, [item.id]: result }));
      setActiveId(null);
      onEvaluated?.(result.report);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "错题重做提交失败");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="insight-panel p-5 text-sm text-slate-500">正在整理错题本…</div>;
  if (!data) return <Notice tone="warn" title="错题本暂时不可用" desc={error || "请稍后刷新。"} />;

  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-4">
        <Stat label="累计错题" value={data.summary.total} tone={data.summary.total ? "warn" : "success"} />
        <Stat label="待巩固" value={data.summary.pending} tone={data.summary.pending ? "warn" : "success"} />
        <Stat label="已恢复" value={data.summary.resolved} tone="success" />
        <Stat label="已收藏" value={data.summary.favorite} tone="action" />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-2">
        <div className="flex flex-wrap gap-1">
          {([['all', '全部'], ['pending', '待巩固'], ['favorite', '收藏'], ['resolved', '已恢复']] as const).map(([key, label]) => (
            <button key={key} type="button" onClick={() => setFilter(key)} className={`rounded-lg px-3 py-2 text-xs font-bold ${filter === key ? "bg-[#163E32] text-white" : "text-slate-500 hover:bg-slate-50"}`}>{label}</button>
          ))}
        </div>
        <button type="button" onClick={() => void load()} className="secondary-action"><RefreshCw size={14} /> 刷新</button>
      </div>

      {error && <Notice tone="warn" title="操作没有完成" desc={error} />}
      {items.length === 0 ? (
        <div className="source-empty min-h-56"><BookOpenCheck size={26} /><strong>{data.summary.total ? "这个筛选下没有题目" : "还没有错题"}</strong><span>{data.summary.total ? "切换到其他标签继续查看。" : "完成一次巩固测验后，答错或揭晓的题会自动进入这里。"}</span></div>
      ) : (
        <div className="space-y-3">
          {items.map((item, index) => {
            const practicing = activeId === item.id;
            const result = results[item.id];
            const isChoice = item.question.type === "single" || (item.question.type === "complexity" && item.question.options.length > 0);
            return (
              <article key={item.id} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div className="flex items-start gap-3 p-4">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-orange-50 font-mono text-xs font-black text-orange-700">{index + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-black leading-6 text-slate-950">{item.question.stem}</div>
                    <div className="mt-2 flex flex-wrap gap-1.5"><Badge variant="info">{item.kp_name}</Badge><Badge variant={item.status === "resolved" ? "success" : "warn"}>{item.status === "resolved" ? "已恢复" : "待巩固"}</Badge><Badge variant="neutral">错因：{item.reason}</Badge>{item.lapse_count > 0 && <Badge variant="warn">反复错 {item.lapse_count + 1} 次</Badge>}</div>
                  </div>
                  <button type="button" onClick={() => void toggleFavorite(item)} className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border transition ${item.favorite ? "border-amber-300 bg-amber-50 text-amber-500" : "border-slate-200 text-slate-400 hover:text-amber-500"}`} aria-label={item.favorite ? "取消收藏" : "收藏错题"}><Star size={17} fill={item.favorite ? "currentColor" : "none"} /></button>
                </div>

                <details className="border-t border-slate-100 bg-slate-50 px-4 py-3 text-xs">
                  <summary className="cursor-pointer font-bold text-slate-600">查看上次错误与解析</summary>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2"><div className="rounded-lg border border-rose-100 bg-rose-50 p-3"><div className="font-bold text-rose-700">上次答案</div><div className="mt-1 leading-5 text-slate-600">{choiceLabel(item.question.options, item.last_answer)}</div></div><div className="rounded-lg border border-emerald-100 bg-emerald-50 p-3"><div className="font-bold text-emerald-700">参考答案</div><div className="mt-1 leading-5 text-slate-600">{choiceLabel(item.question.options, item.expected)}</div></div></div>
                  {item.explain && <p className="mt-2 rounded-lg border border-slate-200 bg-white p-3 leading-6 text-slate-600">{item.explain}</p>}
                </details>

                <div className="border-t border-slate-100 p-4">
                  {!practicing ? (
                    <div className="flex flex-wrap items-center justify-between gap-3"><span className="text-xs text-slate-500">随时重做；结果会更新掌握度和下一次复习时间。</span><button type="button" onClick={() => begin(item.id)} className="primary-action">重做这题</button></div>
                  ) : (
                    <div className="space-y-3">
                      {isChoice ? <div className="grid gap-2 sm:grid-cols-2">{item.question.options.map((option, optionIndex) => { const letter = String.fromCharCode(65 + optionIndex); return <button type="button" key={letter} onClick={() => setAnswer(letter)} className={`rounded-lg border px-3 py-2 text-left text-xs ${answer === letter ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}><span className="mr-2 font-mono font-bold">{letter}</span>{option.replace(/^[A-D][.、：:\s]*/, "")}</button>; })}</div> : item.question.type === "judge" ? <div className="flex gap-2">{["对", "错"].map((value) => <button type="button" key={value} onClick={() => setAnswer(value)} className={`rounded-lg border px-5 py-2 text-xs font-bold ${answer === value ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-200"}`}>{value}</button>)}</div> : <textarea value={answer} onChange={(event) => setAnswer(event.target.value)} rows={3} placeholder="独立写下答案" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-emerald-400" />}
                      {answer.trim() && <ConfidencePicker value={confidence} onChange={setConfidence} disabled={busy} />}
                      <div className="flex justify-end gap-2"><button type="button" onClick={() => setActiveId(null)} className="secondary-action">取消</button><button type="button" onClick={() => void submit(item)} disabled={!answer.trim() || !confidence || busy} className="primary-action disabled:opacity-40">{busy ? "正在判分…" : "提交重做"}</button></div>
                    </div>
                  )}
                  {result && <Notice tone={result.correct ? "success" : "warn"} title={result.correct ? "这次独立答对了" : "这次仍需巩固"} desc={`${result.correct ? "已形成新的恢复证据。" : `参考答案：${choiceLabel(item.question.options, result.expected)}`} ${result.schedule?.interval_days ? `下次计划在 ${result.schedule.interval_days} 天后复习。` : ""}`} />}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
