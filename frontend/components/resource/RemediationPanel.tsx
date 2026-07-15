"use client";

import { useState } from "react";
import Markdown from "@/components/chat/Markdown";
import { Badge, Notice } from "@/components/ui";
import { USER_ID, apiPost } from "@/lib/api";
import type { LearningDiagnosis, ResourceItem } from "@/lib/types";

interface RemediationResponse {
  diagnosis: LearningDiagnosis;
  resource: ResourceItem;
  next_action: "retest" | "select_source";
  reused: boolean;
}

export default function RemediationPanel({
  attemptId,
  diagnosis,
}: {
  attemptId: number;
  diagnosis: LearningDiagnosis;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RemediationResponse | null>(null);
  const canGenerate = ["remediate", "reteach"].includes(diagnosis.action);
  const gapLabel = diagnosis.prerequisite_gap
    ? `前置缺口：${diagnosis.prerequisite_name || diagnosis.prerequisite_gap}`
    : `当前卡点：${diagnosis.blocked_name || diagnosis.blocked_kp || "待巩固概念"}`;

  async function generate() {
    setBusy(true);
    setError("");
    try {
      setResult(await apiPost<RemediationResponse>("/eval/remediation", {
        user_id: USER_ID,
        attempt_id: attemptId,
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "补救微课暂时无法生成");
    } finally {
      setBusy(false);
    }
  }

  if (!canGenerate) {
    return (
      <Notice
        tone="warn"
        title={diagnosis.action === "schedule_review" ? "本轮补救已停止" : "已进入后续复习"}
        desc={diagnosis.reason}
      />
    );
  }

  return (
    <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="warn" mono>REMEDIATE</Badge>
            <Badge variant={diagnosis.severity === "high" ? "danger" : "neutral"}>{gapLabel}</Badge>
          </div>
          <h3 className="mt-3 text-sm font-black text-slate-950">先补一个最小缺口，再回到原题</h3>
          <p className="mt-1 text-xs leading-5 text-slate-600">{diagnosis.reason}</p>
          {diagnosis.misconception && (
            <p className="mt-2 text-[11px] font-medium text-amber-800">诊断误区：{diagnosis.misconception}</p>
          )}
        </div>
        {!result && (
          <button
            type="button"
            onClick={generate}
            disabled={busy}
            className="rounded-lg bg-amber-600 px-3 py-2 text-xs font-black text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "正在按资料整理..." : "生成补救微课"}
          </button>
        )}
      </div>

      {!result && diagnosis.evidence?.length > 0 && (
        <ul className="mt-3 space-y-1 rounded-lg border border-amber-200 bg-white/70 px-3 py-2 text-[11px] leading-5 text-slate-600">
          {diagnosis.evidence.slice(0, 4).map((item) => <li key={item}>· {item}</li>)}
        </ul>
      )}
      {error && <div className="mt-3"><Notice tone="warn" title="补救微课生成失败" desc={`${error}。可以直接重试。`} /></div>}

      {result && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-white p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <strong className="text-sm text-slate-950">{result.resource.title}</strong>
            <Badge variant={result.next_action === "retest" ? "success" : "warn"}>
              {result.next_action === "retest" ? "读完后回到无提示复测" : "需要补充或重选资料"}
            </Badge>
          </div>
          {result.resource.payload.markdown && (
            <Markdown
              text={result.resource.payload.markdown}
              citeBase={result.resource.id}
              citations={result.resource.citations || []}
            />
          )}
          {result.resource.citations?.length > 0 && (
            <div className="mt-3 border-t border-slate-200 pt-2 text-[11px] leading-5 text-slate-500">
              {result.resource.citations.map((citation, index) => (
                <div key={`${citation}-${index}`}><span className="font-mono text-emerald-700">[{index + 1}]</span> {citation}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
