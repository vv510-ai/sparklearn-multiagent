"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { Notice } from "@/components/ui";
import { apiAssetUrl, apiGet } from "@/lib/api";
import type { ResourceItem } from "@/lib/types";
import { voiceLabel } from "@/lib/media";
import ClaudeVideoPanel from "./ClaudeVideoPanel";

export default function VideoBlock({ payload }: { payload: ResourceItem["payload"]; kind?: string }) {
  const [video, setVideo] = useState(payload.video);
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState("");
  const [playbackError, setPlaybackError] = useState("");
  const [previewIndex, setPreviewIndex] = useState(0);
  const [previewPlaying, setPreviewPlaying] = useState(true);
  const [narrationSpeaking, setNarrationSpeaking] = useState(false);
  const attempts = useRef(0);
  // Claude Code videos poll and render in their own panel; the legacy cloud-video flow stays below.
  const claude = payload.video?.provider === "claude_code";
  const claudeDone = claude && payload.video?.status === "succeeded";
  const script = payload.script;
  const scenes = script?.scenes || [];
  const providerUrl = String(video?.url || "");
  const isManagedVideo = providerUrl.startsWith("/static/gen/");
  const shouldMaterialize = Boolean(video?.task_id && providerUrl && !isManagedVideo);
  const videoUrl = apiAssetUrl(isManagedVideo || !video?.task_id ? providerUrl : undefined);
  const coverUrl = apiAssetUrl(payload.cover_url);
  const audioUrl = apiAssetUrl(payload.audio_url);
  const strictSuperUnavailable = Boolean(
    payload.audio?.strict_voice
      || (payload.audio?.provider === "spark_super_tts" && !audioUrl),
  );
  const preview = payload.animation_preview;
  const stages = preview?.stages || [];

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

  useEffect(() => () => window.speechSynthesis?.cancel(), []);

  const toggleBrowserNarration = useCallback(() => {
    if (!script?.narration || !("speechSynthesis" in window)) return;
    if (narrationSpeaking) {
      window.speechSynthesis.cancel();
      setNarrationSpeaking(false);
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(script.narration);
    utterance.lang = "zh-CN";
    utterance.rate = 0.86;
    utterance.onend = () => setNarrationSpeaking(false);
    utterance.onerror = () => setNarrationSpeaking(false);
    setNarrationSpeaking(true);
    window.speechSynthesis.speak(utterance);
  }, [narrationSpeaking, script?.narration]);

  const poll = useCallback(async () => {
    if (claude || !video?.task_id || polling) return;
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
  }, [claude, polling, video?.task_id]);

  useEffect(() => {
    const terminal = video?.status === "failed" || video?.status === "timeout";
    if (claude || !video?.task_id || polling || terminal || videoUrl || attempts.current >= 120) return;
    const timer = window.setTimeout(() => {
      attempts.current += 1;
      void poll();
    }, attempts.current === 0 ? 800 : 3500);
    return () => window.clearTimeout(timer);
  }, [claude, poll, polling, shouldMaterialize, video?.status, video?.task_id, videoUrl]);

  if (!video && !script && !preview && !payload.audio_url && !payload.cover_url) {
    return (
      <Notice
        tone="warn"
        title="讲解资源为空"
        desc="没有视频任务、分镜脚本、旁白或可视化降级内容。可重新生成该类型资源。"
      />
    );
  }

  return (
    <div className="space-y-3">
      {claude && payload.video && <ClaudeVideoPanel video={payload.video} coverUrl={coverUrl} />}
      {!claude && video?.task_id && !videoUrl && video.status !== "failed" && video.status !== "timeout" && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs">
          <span className="min-w-0 text-slate-700">
            {shouldMaterialize || video.status === "succeeded"
              ? "云端视频已生成，正在安全保存到 知行循证"
              : "云端正在生成视频；下面的动态演示是等待期间的学习预览"}
          </span>
          <button
            onClick={() => void poll()}
            disabled={polling}
            className="shrink-0 rounded-md border border-emerald-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-emerald-700 transition hover:bg-emerald-50 disabled:opacity-50"
          >
            {polling ? "查询中..." : "刷新状态"}
          </button>
        </div>
      )}

      {stages.length > 0 && !claudeDone && (
        <div className="overflow-hidden rounded-xl border border-emerald-200 bg-gradient-to-br from-[#071E19] via-[#10392E] to-[#19513F] text-white shadow-sm">
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
            <div><div className="text-[10px] font-bold tracking-[0.18em] text-emerald-300">动态演示</div><strong className="text-sm">{preview?.title || script?.title || "动态讲解"}</strong></div>
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
        </div>
      )}

      {claude ? null : video?.status === "failed" || video?.status === "timeout" ? (
        <Notice
          tone="error"
          title={`视频生成${video.status === "timeout" ? "超时" : "失败"}`}
          desc={`${video.error || video.reason || "请稍后重试"}。下方动态预览和讲解步骤仍可使用。`}
        />
      ) : videoUrl ? (
        <div className="space-y-2">
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
          <p className="text-[11px] leading-5 text-slate-500">
            上方是约 {script?.video_clip_seconds || 10} 秒的关键概念动画；完整 {script?.target_seconds || 60} 秒讲解请结合下方分镜与稍慢语速旁白收听。
          </p>
        </div>
      ) : video?.task_id ? null : video?.status === "degraded" ? (
        <Notice
          tone="info"
          title="已切换为动态讲解"
          desc="视频暂时不可用，先展示动态步骤和重点讲解。"
        />
      ) : coverUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={coverUrl} alt="视频封面" className="w-full rounded-xl border border-slate-200" />
      ) : null}

      {pollError && <Notice tone="warn" title="视频保存稍有延迟" desc={pollError} />}
      {playbackError && <Notice tone="warn" title="视频暂时无法播放" desc={playbackError} />}

      {script && !claudeDone && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[11px] font-bold tracking-[0.18em] text-emerald-600">讲解步骤</span>
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

      {audioUrl && !claudeDone && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 text-[11px] font-bold tracking-[0.18em] text-emerald-600">
            {voiceLabel(payload.audio)}
          </div>
          <audio src={audioUrl} controls className="w-full" />
          {payload.audio?.provider === "spark_tts" && payload.audio?.degraded && (
            <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] leading-5 text-amber-800">
              当前音频不是已配置的超拟人音色；超拟人服务恢复后，新生成的讲解会自动优先使用它。
            </p>
          )}
        </div>
      )}

      {strictSuperUnavailable && script?.narration && !claudeDone && (
        <Notice
          tone="warn"
          title="超拟人语音暂未生成"
          desc="已锁定星火超拟人音色，系统不会改用普通星火或浏览器声音。可稍后重新生成云端语音。"
        />
      )}

      {!audioUrl && script?.narration && !strictSuperUnavailable && !claudeDone && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3">
          <div>
            <div className="text-[11px] font-bold tracking-[0.18em] text-emerald-700">即时语音讲解</div>
            <p className="mt-1 text-xs leading-5 text-slate-600">云端音频未就绪时，可先用浏览器稍慢语速朗读完整两分钟讲稿。</p>
          </div>
          <button
            type="button"
            onClick={toggleBrowserNarration}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-emerald-300 bg-white px-3 py-2 text-xs font-bold text-emerald-700 hover:bg-emerald-100"
          >
            {narrationSpeaking ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
            {narrationSpeaking ? "暂停朗读" : "立即听讲"}
          </button>
        </div>
      )}

    </div>
  );
}
