"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { Notice } from "@/components/ui";
import { apiAssetUrl, apiGet } from "@/lib/api";
import type { ResourceItem } from "@/lib/types";

type PptState = NonNullable<ResourceItem["payload"]["ppt"]>;

export default function PptBlock({ payload }: { payload: ResourceItem["payload"] }) {
  const [ppt, setPpt] = useState<PptState>(payload.ppt || {});
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState("");
  const attempts = useRef(0);
  const pptUrl = apiAssetUrl(ppt.url);
  const coverUrl = apiAssetUrl(ppt.cover_url || payload.cover_url);

  useEffect(() => {
    setPpt(payload.ppt || {});
    attempts.current = 0;
  }, [payload.ppt]);

  const poll = useCallback(async () => {
    if (!ppt.task_id || polling || ppt.status !== "building") return;
    setPolling(true);
    try {
      const next = await apiGet<PptState>(`/resources/ppt/task/${ppt.task_id}`);
      setPpt((current) => ({ ...current, ...next }));
      setPollError(next.retryable && next.error ? next.error : "");
    } catch {
      setPollError("暂时没有查到生成进度，系统会继续重试。");
    } finally {
      setPolling(false);
    }
  }, [polling, ppt.status, ppt.task_id]);

  useEffect(() => {
    if (ppt.status !== "building" || !ppt.task_id || attempts.current >= 100) return;
    const timer = window.setTimeout(() => {
      attempts.current += 1;
      void poll();
    }, attempts.current === 0 ? 800 : 3500);
    return () => window.clearTimeout(timer);
  }, [poll, polling, ppt.status, ppt.task_id]);

  if (ppt.status === "blocked") {
    return <Notice tone="warn" title="还不能生成这份 PPT" desc={ppt.error || "请先选择可用的学习资料。"} />;
  }
  if (ppt.status === "failed") {
    return <Notice tone="error" title="PPT 生成没有完成" desc={ppt.error || "可以稍后重新生成。"} />;
  }

  return (
    <div className="space-y-3">
      {coverUrl && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={coverUrl} alt="复习PPT封面" className="max-h-72 w-full rounded-xl border border-slate-200 object-cover" />
      )}

      {pptUrl ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <div className="text-sm font-bold text-emerald-900">复习 PPT 已生成</div>
          <p className="mt-1 text-xs leading-5 text-emerald-800">
            {ppt.total_pages ? `共 ${ppt.total_pages} 页，` : ""}文件已保存到 知行循证，可以下载后继续编辑。
          </p>
          <a
            href={pptUrl}
            download
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white transition hover:bg-emerald-800"
          >
            <Download size={15} /> 下载 PPT
          </a>
        </div>
      ) : ppt.task_id ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50 px-3 py-3 text-xs">
          <div className="min-w-0 text-slate-700">
            <div className="font-bold text-blue-900">正在整理可编辑复习 PPT</div>
            <div className="mt-1">
              {ppt.total_pages ? `已完成 ${ppt.done_pages || 0}/${ppt.total_pages} 页` : "先生成大纲，再完成轻量排版"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => void poll()}
            disabled={polling}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-blue-300 bg-white px-2.5 py-1.5 font-bold text-blue-700 disabled:opacity-50"
          >
            <RefreshCw size={13} className={polling ? "animate-spin" : ""} />
            {polling ? "查询中" : "刷新"}
          </button>
        </div>
      ) : (
        <Notice tone="warn" title="没有取得 PPT 任务" desc={ppt.error || "请重新点击学习工坊里的复习 PPT。"} />
      )}

      {pollError && <Notice tone="warn" title="进度查询稍有延迟" desc={pollError} />}
      <p className="text-[11px] leading-5 text-slate-500">
        复习 PPT 只会在你明确点击或提出生成要求时创建，普通问答不会自动消耗服务额度。
      </p>
    </div>
  );
}
