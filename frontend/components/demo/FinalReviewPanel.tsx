"use client";

import { CheckCircle2, Circle, RotateCcw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import ResourceCard from "@/components/resource/ResourceCard";
import { Notice } from "@/components/ui";
import { apiGet, apiPost } from "@/lib/api";
import type { PathPlan, ResourceItem } from "@/lib/types";

type EvalSummary = { path?: PathPlan; profile_version?: number };

interface FinalReviewSet {
  id: string;
  title: string;
  order: number;
  question_count: number;
  pattern_label: string;
  operator_answers: string[];
  completed: boolean;
  resource: ResourceItem | null;
}

interface FinalReviewStatus {
  version: string;
  ready: boolean;
  checks: {
    account: boolean;
    quiz_sets: boolean;
    baseline: boolean;
    answer_order: boolean;
  };
  baseline: { exists: boolean; created_at?: string | null };
  completed_set_ids: string[];
  next_set_id: string;
  sets: FinalReviewSet[];
}

const CHECK_LABELS: { key: keyof FinalReviewStatus["checks"]; label: string }[] = [
  { key: "account", label: "当前登录账号" },
  { key: "quiz_sets", label: "两组固定 5 题" },
  { key: "baseline", label: "答题前基线" },
  { key: "answer_order", label: "固定作答顺序" },
];

export default function FinalReviewPanel({
  onEvaluated,
  onRestored,
  onOpenMistakes,
}: {
  onEvaluated?: (report: EvalSummary) => void;
  onRestored?: () => void;
  onOpenMistakes?: () => void;
}) {
  const [status, setStatus] = useState<FinalReviewStatus | null>(null);
  const [busy, setBusy] = useState<"prepare" | "restore" | "">("");
  const [error, setError] = useState("");
  const [instance, setInstance] = useState(0);

  const load = useCallback(async () => {
    const next = await apiGet<FinalReviewStatus>("/demo/final-review");
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    void load().catch((caught) => {
      setError(caught instanceof Error ? caught.message : "终审演示状态加载失败");
    });
  }, [load]);

  const prepare = async () => {
    setBusy("prepare");
    setError("");
    try {
      const next = await apiPost<FinalReviewStatus>("/demo/final-review/prepare", {});
      setStatus(next);
      setInstance((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "终审题组准备失败");
    } finally {
      setBusy("");
    }
  };

  const restore = async () => {
    if (!window.confirm("恢复后，本轮两组测验产生的画像、错题与知识路径变化会被撤销。继续吗？")) return;
    setBusy("restore");
    setError("");
    try {
      const next = await apiPost<FinalReviewStatus>("/demo/final-review/restore", {});
      setStatus(next);
      setInstance((value) => value + 1);
      onRestored?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "演示基线恢复失败");
    } finally {
      setBusy("");
    }
  };

  const activeSet = useMemo(
    () => status?.sets.find((item) => item.id === status.next_set_id) || null,
    [status],
  );

  const evaluated = async (report: EvalSummary) => {
    onEvaluated?.(report);
    try {
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交成功，但演示状态刷新失败");
    }
  };

  if (!status && !error) {
    return <div className="source-empty min-h-[220px]"><ShieldCheck size={24} /><strong>正在核对终审演示条件</strong><span>账号、题组、基线和作答顺序会一起检查。</span></div>;
  }

  return (
    <div className="space-y-4">
      <section className="insight-panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-[10px] font-bold tracking-[0.18em] text-[#0F6B50]">FINAL REVIEW PREFLIGHT</div>
            <h2 className="mt-2 text-xl font-bold text-[#1D2028]">四项齐全后才开放正式答题</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#6F7684]">准备动作会写入两组固定题并锁定当前画像、错题与知识路径基线。任何题量、顺序或目标正误模式不一致，后端都会在写入学习档案前暂停提交。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {!status?.ready && (
              <button type="button" onClick={() => void prepare()} disabled={Boolean(busy)} className="primary-action disabled:cursor-wait disabled:opacity-50">
                {busy === "prepare" ? "正在准备..." : "准备两组终审题"}
              </button>
            )}
            {status?.baseline.exists && (
              <button type="button" onClick={() => void restore()} disabled={Boolean(busy)} className="secondary-action inline-flex items-center gap-2 disabled:cursor-wait disabled:opacity-50">
                <RotateCcw size={15} />{busy === "restore" ? "正在恢复..." : "恢复答题前状态"}
              </button>
            )}
          </div>
        </div>

        <div className="mt-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {CHECK_LABELS.map((item) => {
            const complete = Boolean(status?.checks[item.key]);
            return (
              <div key={item.key} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-bold ${complete ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-500"}`}>
                {complete ? <CheckCircle2 size={16} /> : <Circle size={16} />}{item.label}
              </div>
            );
          })}
        </div>

        {status?.ready ? (
          <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs leading-5 text-emerald-800">
            已确认：题组一 <strong>final-binary-tree-v1</strong> → 题组二 <strong>final-sorting-adv-v1</strong>。已完成 {status.completed_set_ids.length}/2 组；需要重录时先点击“恢复答题前状态”。
          </div>
        ) : (
          <Notice tone="warn" title="正式答题已暂停" desc="请先完成上方四项准备；题组卡片不会提前开放。" />
        )}
        {error && <div className="mt-3"><Notice tone="warn" title="终审演示暂不可用" desc={error} /></div>}
      </section>

      {status?.ready && (
        <section className="insight-panel p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[10px] font-bold tracking-[0.18em] text-[#77611E]">FIXED ANSWER RUNBOOK</div>
              <h2 className="mt-2 text-lg font-bold">固定作答输入</h2>
            </div>
            <span className="rounded-full bg-[#F0F1F5] px-3 py-1 text-xs font-bold text-[#626978]">按 Q1 → Q5</span>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {status.sets.map((item) => (
              <div key={item.id} className={`rounded-xl border p-4 ${item.completed ? "border-emerald-200 bg-emerald-50" : "border-[#E1E4EC] bg-[#F8F9FC]"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div><div className="font-mono text-[10px] text-[#818795]">{item.id}</div><strong className="mt-1 block text-sm">{item.order}. {item.title.replace(/^终审固定题组[一二]：/, "")}</strong></div>
                  {item.completed && <span className="text-xs font-bold text-emerald-700">已完成</span>}
                </div>
                <div className="mt-3 text-xs font-bold text-[#9A5B12]">目标：{item.pattern_label}</div>
                <div className="mt-3 grid grid-cols-5 gap-1.5">
                  {item.operator_answers.map((answer, index) => (
                    <div key={`${item.id}-${index}`} className="min-w-0 rounded-md border border-white bg-white px-2 py-2 text-center shadow-sm">
                      <div className="font-mono text-[9px] text-[#9AA0AC]">Q{index + 1}</div>
                      <div className="mt-1 break-words text-[11px] font-bold text-[#343944]">{answer}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {status?.ready && activeSet?.resource && (
        <section key={`${activeSet.id}-${instance}`}>
          <div className="mb-3 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-xs leading-5 text-sky-800">
            当前只开放第 {activeSet.order} 组：<strong>{activeSet.title}</strong>。请完成全部 5 题并为每题标记作答把握后再提交。
          </div>
          <ResourceCard
            r={activeSet.resource}
            defaultOpen
            onQuizEvaluated={(report) => void evaluated(report)}
            onOpenMistakes={onOpenMistakes}
          />
        </section>
      )}

      {status?.ready && !activeSet && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-center">
          <CheckCircle2 className="mx-auto text-emerald-600" size={28} />
          <strong className="mt-3 block text-base text-emerald-900">两组 10 题已按终审顺序完成</strong>
          <span className="mt-1 block text-xs leading-5 text-emerald-700">现在可以展示掌握度、错因、错题本和知识路径变化；需要重录时恢复基线即可。</span>
        </div>
      )}
    </div>
  );
}
