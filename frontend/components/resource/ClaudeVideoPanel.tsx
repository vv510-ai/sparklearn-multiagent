"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Clapperboard, Download, Loader2, Play, RotateCcw, Square } from "lucide-react";
import { Notice } from "@/components/ui";
import { apiAssetUrl, apiGet, apiPost } from "@/lib/api";
import type { ResourceItem, VideoStoryboard } from "@/lib/types";

type Video = NonNullable<ResourceItem["payload"]["video"]>;

const STEPS = [
  { label: "分镜", phases: ["queued", "prepare", "storyboard"] },
  { label: "配音", phases: ["voice", "awaiting_approval"] },
  { label: "画面与动效", phases: ["compose"] },
  { label: "截图自查", phases: ["review"] },
  { label: "渲染校验", phases: ["render", "check", "upload"] },
];
const ACTIVE = new Set(["queued", "running", "awaiting_approval"]);
const EFFORT: Record<string, string> = { low: "低", medium: "中", high: "高", xhigh: "很高", max: "最高" };
const POLL_LIMIT_MS = 4 * 60 * 60 * 1000;

function clock(seconds?: number) {
  const total = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function modelLabel(model?: string) {
  const parts = String(model || "").replace(/^claude-/, "").split("-");
  if (!parts[0]) return "Claude";
  return `${parts[0][0].toUpperCase()}${parts[0].slice(1)} ${parts.slice(1).join(".")}`.trim();
}

function Storyboard({ board }: { board: VideoStoryboard }) {
  return (
    <div className="ll-cv-board">
      {board.summary && <p className="text-xs leading-6 text-slate-600">{board.summary}</p>}
      {board.scenes.map((scene, index) => (
        <div key={`${scene.title}-${index}`} className="ll-cv-scene">
          <time>{scene.start != null ? `${clock(scene.start)}–${clock(scene.end)}` : `第 ${index + 1} 镜`}</time>
          <div>
            <strong>{scene.title}</strong>
            <p>{scene.narration}</p>
            {scene.visual && <small>画面：{scene.visual}</small>}
          </div>
        </div>
      ))}
      {board.quiz && <p className="text-xs leading-6 text-emerald-800">结尾自测：{board.quiz}</p>}
    </div>
  );
}

/** Live Claude Code video: progress while it is made, storyboard approval, then the player with chapters. */
export default function ClaudeVideoPanel({ video: initial, coverUrl }: { video: Video; coverUrl?: string }) {
  const [video, setVideo] = useState<Video>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState("");
  const [tick, setTick] = useState(0);
  const player = useRef<HTMLVideoElement>(null);
  const started = useRef(Date.now());

  useEffect(() => { setVideo(initial); }, [initial]);
  const merge = useCallback((next: Video) => setVideo(current => ({ ...current, ...next })), []);

  useEffect(() => {
    if (!video.task_id || !ACTIVE.has(video.status || "") || Date.now() - started.current > POLL_LIMIT_MS) return;
    const timer = window.setTimeout(async () => {
      try {
        merge(await apiGet<Video>(`/resources/video/task/${video.task_id}`));
      } catch {
        setTick(value => value + 1);
      }
    }, video.status === "awaiting_approval" ? 20000 : 5000);
    return () => window.clearTimeout(timer);
  }, [video, tick, merge]);

  async function act(action: "approve" | "cancel" | "retry") {
    if (!video.task_id) return;
    setBusy(true);
    setError("");
    try {
      merge(await apiPost<Video>(`/claude-video/${video.task_id}/${action}`, action === "approve" ? { notes } : {}));
      started.current = Date.now();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const status = video.status || "queued";
  const phase = video.phase || "queued";
  const stepIndex = Math.max(0, STEPS.findIndex(step => step.phases.includes(phase)));
  const url = apiAssetUrl(video.url || undefined);
  const poster = apiAssetUrl(video.poster_url || undefined) || coverUrl;
  const board = video.storyboard && video.storyboard.scenes?.length ? video.storyboard : null;
  const seek = (seconds: number) => {
    if (!player.current) return;
    player.current.currentTime = seconds;
    void player.current.play().catch(() => undefined);
  };

  return (
    <section className="ll-cv" aria-label="Claude 讲解视频">
      <header className="ll-cv-head">
        <h3><Clapperboard size={17} />{video.title || board?.title || "Claude 讲解视频"}</h3>
        <div className="ll-cv-badges">
          <span>{modelLabel(video.model)}</span>
          {video.effort && <span>思考强度 {EFFORT[video.effort] || video.effort}</span>}
          <span>{status === "succeeded" ? `1080P · ${clock(video.duration)}` : "HyperFrames · 1080P"}</span>
        </div>
      </header>

      <div className="ll-cv-body">
        {status === "succeeded" && url ? (
          <>
            <div className="ll-video">
              <video ref={player} src={url} poster={poster} controls preload="metadata" playsInline />
              <div className="ll-video-bar">
                <span>由你本机的 Claude Code 制作 · 先出分镜，再配音、动画与渲染</span>
                <a href={url} download className="inline-flex items-center gap-1 font-bold text-emerald-200 hover:text-white">
                  <Download size={14} />下载 MP4
                </a>
              </div>
            </div>
            {!!video.chapters?.length && (
              <nav className="ll-cv-chapters" aria-label="视频章节">
                {video.chapters.map(chapter => (
                  <button key={`${chapter.start}-${chapter.title}`} type="button" onClick={() => seek(chapter.start)}>
                    <time>{clock(chapter.start)}</time>{chapter.title}
                  </button>
                ))}
              </nav>
            )}
            {video.notes && <p className="text-xs leading-6 text-slate-500">Claude 自查：{video.notes}</p>}
            {board && (
              <details className="rounded-xl border border-emerald-100 bg-white/70 p-3">
                <summary className="cursor-pointer text-xs font-bold text-emerald-800">完整分镜与旁白（{board.scenes.length} 镜）</summary>
                <div className="mt-3"><Storyboard board={board} /></div>
              </details>
            )}
          </>
        ) : status === "awaiting_approval" && board ? (
          <div className="ll-cv-approve space-y-3">
            <Notice tone="info" title="分镜已完成，确认后开始制作"
              desc={`共 ${board.scenes.length} 镜，配音时长 ${clock(board.duration)}。旁白已按这份分镜录好；补充意见只影响画面与动效。`} />
            <Storyboard board={board} />
            <label className="block text-xs font-bold text-slate-600" htmlFor={`notes-${video.task_id}`}>补充意见（可选）</label>
            <textarea id={`notes-${video.task_id}`} maxLength={400} value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="例如：第 3 镜的反应过程做成分子拆开再重组的动画" />
            <div className="ll-cv-actions">
              <button type="button" className="primary-action" disabled={busy} onClick={() => void act("approve")}>
                <Play size={14} />开始制作
              </button>
              <button type="button" className="secondary-action" disabled={busy} onClick={() => void act("cancel")}>取消</button>
            </div>
          </div>
        ) : ACTIVE.has(status) ? (
          <>
            <div className="ll-cv-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={video.progress || 2}>
              <i style={{ width: `${Math.max(3, Math.min(100, video.progress || 2))}%` }} />
            </div>
            <ol className="ll-cv-steps">
              {STEPS.map((step, index) => (
                <li key={step.label} className={index < stepIndex ? "is-done" : index === stepIndex ? "is-active" : ""}>
                  <b>{index + 1}</b>{step.label}
                </li>
              ))}
            </ol>
            <p className="ll-cv-message" role="status">
              <Loader2 size={15} className="animate-spin text-emerald-600" />
              {video.message || "已交给本机 Claude 制作"}
            </p>
            {status === "queued" && video.worker_online === false && (
              <Notice tone="warn" title="本机视频接入程序未运行"
                desc="在 Mac 的 LearnLoop 启动菜单选择“启动讲解视频接入”，保持窗口运行即可自动开始。" />
            )}
            {board && (
              <details className="rounded-xl border border-emerald-100 bg-white/70 p-3">
                <summary className="cursor-pointer text-xs font-bold text-emerald-800">分镜方案（{board.scenes.length} 镜 · {clock(board.duration)}）</summary>
                <div className="mt-3"><Storyboard board={board} /></div>
              </details>
            )}
            <div className="ll-cv-actions">
              <button type="button" className="secondary-action" disabled={busy} onClick={() => void act("cancel")}>
                <Square size={13} />取消制作
              </button>
              <span className="self-center text-[11px] text-slate-500">通常 10~30 分钟；可以先看下面的讲解步骤，完成后会自动出现在这里。</span>
            </div>
          </>
        ) : (
          <div className="space-y-3">
            <Notice tone={status === "cancelled" ? "info" : "error"} title={status === "cancelled" ? "已取消制作" : "讲解视频没有完成"}
              desc={video.error || "可以重新制作，或先看下面的讲解步骤。"} />
            {video.retryable !== false && (
              <button type="button" className="primary-action" disabled={busy} onClick={() => void act("retry")}>
                <RotateCcw size={14} />重新制作
              </button>
            )}
          </div>
        )}
        {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-xs text-red-800">{error}</p>}
      </div>
    </section>
  );
}
