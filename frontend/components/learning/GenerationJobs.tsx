"use client";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
type Job = { id: string; status: string; detail: string; created_at?: string; kind: string };
export default function GenerationJobs({ notebookId, onView }: { notebookId: string; onView: (kind: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let stopped = false;
    const refresh = async () => {
      try {
        const data = await apiGet<{ items: Job[] }>(`/jobs?notebook_id=${encodeURIComponent(notebookId)}`);
        if (!stopped) { setJobs(data.items); setUnavailable(false); }
      } catch { if (!stopped) setUnavailable(true); }
    };
    setJobs([]); void refresh();
    const timer = setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, 4000);
    return () => { stopped = true; clearInterval(timer); };
  }, [notebookId]);
  const active = jobs.filter(job => ["queued", "running", "needs_review"].includes(job.status));
  const recent = jobs.filter(job => ["completed", "failed"].includes(job.status)).slice(0, 1);
  if (!active.length && !recent.length) return null;
  return <details className="mx-3 my-2 rounded-lg border border-emerald-100 bg-white px-3 py-2 text-sm text-slate-700" open={active.length > 0}>
    <summary className="cursor-pointer">{active.length ? `任务进度（${active.length}）` : "最近任务"}</summary>
    {unavailable && <p role="status">暂时无法读取进度，请检查网络；已提交的任务会保留。</p>}
    {[...active, ...recent].map(job => <div key={job.id} className="mt-2 flex flex-wrap items-center gap-2" data-job-status={job.status}>
      <span>{job.detail}</span>
      {["completed", "failed"].includes(job.status) && <button type="button" className="underline text-emerald-700" onClick={() => onView(job.kind)}>查看结果</button>}
    </div>)}
  </details>;
}
