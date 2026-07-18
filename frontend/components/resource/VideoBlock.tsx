"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Pause, Play } from "lucide-react";
import { Notice } from "@/components/ui";
import { apiAssetUrl, apiGet } from "@/lib/api";
import type { ResourceItem } from "@/lib/types";

export default function VideoBlock({ payload, kind = "video" }: { payload: ResourceItem["payload"]; kind?: string }) {
  const [video, setVideo] = useState(payload.video);
  const [polling, setPolling] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pollError, setPollError] = useState("");
  const [playbackError, setPlaybackError] = useState("");
  const [previewIndex, setPreviewIndex] = useState(0);
  const [previewPlaying, setPreviewPlaying] = useState(true);
  const attempts = useRef(0);
  const script = payload.script;
  const scenes = script?.scenes || [];
  const providerUrl = String(video?.url || "");
  const isManagedVideo = providerUrl.startsWith("/static/gen/");
  const shouldMaterialize = Boolean(video?.task_id && providerUrl && !isManagedVideo);
  const videoUrl = apiAssetUrl(isManagedVideo || !video?.task_id ? providerUrl : undefined);
  const coverUrl = apiAssetUrl(payload.cover_url);
  const audioUrl = apiAssetUrl(payload.audio_url);
  const preview = payload.animation_preview;
  const stages = preview?.stages || [];
  const code = payload.python_code || payload.manim_code || "";
  const codeLabel = kind === "python_animation" || payload.python_code ? "PYTHON · MATPLOTLIB 动画脚本" : "MANIM · 可渲染场景代码";

  useEffect(() => {
    if (!previewPlaying || stages.length < 2) return;
    const timer = window.setInterval(() => setPreviewIndex((current) => (current + 1) % stages.length), preview?.interval_ms || 1500);
    return () => window.clearInterval(timer);
  }, [preview?.interval_ms, previewPlaying, stages.length]);

  useEffect(() => {
    setVideo(payload.video);
    setPlaybackError("");
    attempts.current = 0;
  }, [payload.video]);

  const poll = useCallback(async () => {
    if (!video?.task_id || polling) return;
    setPolling(true);
    setPollError("");
    try {
      const r = await apiGet<NonNullable<ResourceItem["payload"]["video"]>>(
        `/resources/video/task/${video.task_id}`,
      );
      setVideo((v) => ({ ...v, ...r }));
      if (r.url?.startsWith("/static/gen/")) setPlaybackError("");
      if (r.retryable && r.error) setPollError(r.error);
    } catch {
      setPollError("暂时没有查到视频进度，系统会继续重试。");
    } finally {
      setPolling(false);
    }
  }, [polling, video?.task_id]);

  useEffect(() => {
    const terminal = video?.status === "failed" || video?.status === "timeout";
    if (!video?.task_id || polling || terminal || videoUrl || attempts.current >= 120) return;
    const timer = window.setTimeout(() => {
      attempts.current += 1;
      void poll();
    }, attempts.current === 0 ? 800 : 3500);
    return () => window.clearTimeout(timer);
  }, [poll, polling, shouldMaterialize, video?.status, video?.task_id, videoUrl]);

  function copyCode() {
    if (!code) return;
    navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    });
  }

  function downloadCode() {
    if (!code) return;
    const url = URL.createObjectURL(new Blob([code], { type: "text/x-python;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = payload.python_code ? "sparklearn_python_animation.py" : "sparklearn_manim_scene.py";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (!video && !script && !code && !preview && !payload.audio_url && !payload.cover_url) {
    return (
      <Notice
        tone="warn"
        title="讲解资源为空"
        desc="没有视频任务、分镜脚本、旁白或降级动画代码。可重新生成该类型资源。"
      />
    );
  }

  return (
    <div className="space-y-3">
      {stages.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-emerald-200 bg-gradient-to-br from-[#071E19] via-[#10392E] to-[#19513F] text-white shadow-sm">
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
            <div><div className="text-[10px] font-bold tracking-[0.18em] text-emerald-300">LIVE ANIMATION PREVIEW</div><strong className="text-sm">{preview?.title || script?.title || "动态讲解"}</strong></div>
            <button type="button" onClick={() => setPreviewPlaying((value) => !value)} className="grid h-9 w-9 place-items-center rounded-full border border-white/15 bg-white/10 text-white hover:bg-white/15" aria-label={previewPlaying ? "暂停动画" : "播放动画"}>
              {previewPlaying ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" />}
            </button>
          </div>
          <div className="relative min-h-52 px-5 py-7">
            <div className="absolute left-8 right-8 top-[54px] h-1 rounded-full bg-white/10" />
            <div className="relative flex items-start justify-between gap-1">
              {stages.map((stage, index) => (
                <button key={`${stage.label}-${index}`} type="button" onClick={() => { setPreviewIndex(index); setPreviewPlaying(false); }} className="flex min-w-0 flex-1 flex-col items-center text-center">
                  <span className={`grid h-9 w-9 place-items-center rounded-full border-2 font-mono text-xs font-black transition-all duration-500 ${index <= previewIndex ? "scale-110 border-emerald-300 bg-emerald-400 text-[#06241B] shadow-[0_0_24px_rgba(52,211,153,0.45)]" : "border-white/20 bg-[#143C31] text-white/45"}`}>{index + 1}</span>
                  <span className={`mt-3 line-clamp-2 text-[10px] font-bold transition ${index === previewIndex ? "text-white" : "text-white/45"}`}>{stage.label}</span>
                </button>
              ))}
            </div>
            <div className="mx-auto mt-5 max-w-xl rounded-xl border border-white/10 bg-black/15 px-4 py-3 text-center">
              <div className="font-mono text-[10px] text-emerald-300">{stages[previewIndex]?.time || `STEP ${previewIndex + 1}`}</div>
              <div className="mt-1 text-sm font-bold">{stages[previewIndex]?.label}</div>
              <p className="mt-1 text-xs leading-5 text-white/65">{stages[previewIndex]?.detail}</p>
            </div>
          </div>
          <div className="border-t border-white/10 px-4 py-2 text-[10px] text-white/45">这是安全的浏览器预览；服务器不会执行模型返回的 Python 代码。</div>
        </div>
      )}

      {video?.status === "failed" || video?.status === "timeout" ? (
        <Notice
          tone="error"
          title={`视频生成${video.status === "timeout" ? "超时" : "失败"}`}
          desc={`${video.error || video.reason || "请查看后端任务日志"}。下方动态预览、分镜与代码不受影响。`}
        />
      ) : videoUrl ? (
        <video
          key={videoUrl}
          src={videoUrl}
          controls
          preload="metadata"
          poster={coverUrl}
          onError={() => {
            setPlaybackError("视频文件暂时读取失败，系统正在重新获取。");
            if (video?.task_id) {
              setVideo((current) => ({ ...current, status: "running", url: undefined }));
            }
          }}
          className="w-full rounded-xl border border-slate-200 bg-black"
        />
      ) : video?.task_id ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs">
          <span className="min-w-0 text-slate-700">
            {shouldMaterialize || video.status === "succeeded"
              ? "视频已生成，正在安全保存到 SparkLearn"
              : "视频云端生成中，可先阅读下方分镜脚本"}
            <span className="ml-2 font-mono text-[10px] text-slate-500">任务 {video.task_id.slice(0, 10)}...</span>
          </span>
          <button
            onClick={() => void poll()}
            disabled={polling}
            className="shrink-0 rounded-md border border-emerald-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-emerald-700 transition hover:bg-emerald-50 disabled:opacity-50"
          >
            {polling ? "查询中..." : "刷新状态"}
          </button>
        </div>
      ) : video?.status === "degraded" ? (
        <Notice
          tone="info"
          title="已按预案切换为脚本讲解"
          desc="真实视频服务当前未接入，系统已切换为动态分镜预览 + Manim 动画代码。"
        />
      ) : coverUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={coverUrl} alt="视频封面" className="w-full rounded-xl border border-slate-200" />
      ) : null}

      {pollError && <Notice tone="warn" title="视频保存稍有延迟" desc={pollError} />}
      {playbackError && <Notice tone="warn" title="视频暂时无法播放" desc={playbackError} />}

      {script && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-mono text-[11px] tracking-[0.18em] text-emerald-600">STORYBOARD · 分镜脚本</span>
            {script.title && <span className="text-xs font-semibold text-slate-700">{script.title}</span>}
          </div>
          {scenes.length > 0 ? (
            scenes.map((s, i) => (
              <div key={i} className="flex gap-3 border-b border-slate-200 py-2 text-xs last:border-0">
                <span className="w-14 shrink-0 font-mono text-[10px] text-slate-500">{s.t}</span>
                <span className="flex-1 text-slate-700">{s.visual}</span>
                {s.caption && <span className="shrink-0 text-slate-500">「{s.caption}」</span>}
              </div>
            ))
          ) : (
            <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
              本条没有分镜列表,以下为完整旁白。
            </div>
          )}
          {script.narration && <p className="mt-2 text-xs leading-6 text-slate-600">旁白:{script.narration}</p>}
        </div>
      )}

      {audioUrl && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 font-mono text-[11px] tracking-[0.18em] text-emerald-600">TTS · 讲解旁白音频</div>
          <audio src={audioUrl} controls className="w-full" />
        </div>
      )}

      {code && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-950">
          <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
            <span className="font-mono text-[10px] tracking-[0.18em] text-slate-300">{codeLabel}</span>
            <div className="flex gap-2">
              <button onClick={downloadCode} className="flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-[11px] font-semibold text-slate-300 transition hover:border-emerald-400 hover:text-emerald-300"><Download size={12} /> 下载 .py</button>
              <button onClick={copyCode} className="rounded-md border border-slate-700 px-2 py-1 text-[11px] font-semibold text-slate-300 transition hover:border-emerald-400 hover:text-emerald-300">{copied ? "已复制" : "复制代码"}</button>
            </div>
          </div>
          <pre className="max-h-64 overflow-auto p-3 text-[11px] leading-5 text-slate-100">{code}</pre>
        </div>
      )}
    </div>
  );
}
