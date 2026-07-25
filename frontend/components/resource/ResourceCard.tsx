"use client";

import { useState } from "react";
import Markdown from "@/components/chat/Markdown";
import { Badge, Notice, Panel } from "@/components/ui";
import { kpName } from "@/lib/kp";
import type { PathPlan, ResourceItem } from "@/lib/types";
import Markmap from "./Markmap";
import QuizPlayer from "./QuizPlayer";
import VideoBlock from "./VideoBlock";
import InteractiveAudioPlayer from "./InteractiveAudioPlayer";
import PptBlock from "./PptBlock";
import { DataTableBlock, FlashcardsBlock, InfographicBlock, OnePageVisual } from "./StudyArtifactBlocks";
import { apiAssetUrl, apiPost, USER_ID } from "@/lib/api";
import { withoutCodeBlocks } from "@/lib/learningContent";

const KIND_META: Record<
  string,
  {
    label: string;
    code: string;
    icon: string;
    variant: "neutral" | "info" | "success" | "warn" | "danger";
    hint: string;
  }
> = {
  doc: { label: "图文讲解", code: "讲解", icon: "文", variant: "info", hint: "根据课程资料整理，先看结论与结构，再沿着例子理解。" },
  code: { label: "代码练习", code: "代码", icon: "码", variant: "success", hint: "可运行片段与逐段讲解" },
  reading: { label: "延伸阅读", code: "阅读", icon: "读", variant: "neutral", hint: "围绕当前知识点补充阅读材料" },
  mindmap: { label: "知识导图", code: "导图", icon: "图", variant: "info", hint: "按掌握情况标注：已掌握✅ 待巩固⚠️ 未解锁🔒" },
  quiz: { label: "巩固练习", code: "练习", icon: "练", variant: "warn", hint: "提交后更新掌握情况、错因与后续路线" },
  video: { label: "讲解视频", code: "视频", icon: "影", variant: "neutral", hint: "小云雀云端生成状态、动态预览、分镜与超拟人旁白" },
  ppt: { label: "复习演示", code: "PPT", icon: "演", variant: "info", hint: "仅在你明确要求时生成；完成后可下载并继续编辑" },
  flashcards: { label: "记忆闪卡", code: "闪卡", icon: "卡", variant: "warn", hint: "先独立回忆，再翻面核对；可标记已经掌握的卡片" },
  infographic: { label: "学习信息图", code: "信息图", icon: "视", variant: "info", hint: "把来源内的结论、结构、过程与边界放进一张图" },
  data_table: { label: "知识数据表", code: "数据表", icon: "表", variant: "neutral", hint: "对照、筛选并复制为 CSV，方便继续整理" },
  manim: { label: "Manim 数学动画", code: "MANIM", icon: "动", variant: "success", hint: "浏览器先看动态分镜；有预渲染视频时直接播放，并保留可下载代码" },
  python_animation: { label: "Python 数学动画", code: "PY 动画", icon: "Py", variant: "success", hint: "浏览器动态预览 + Matplotlib 动画脚本，不在服务器执行模型代码" },
};

const TEXT_KINDS = new Set(["doc", "code", "reading"]);

function hasText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}
function resourceIssue(r: ResourceItem): string {
  const payload = r.payload || {};
  if (TEXT_KINDS.has(r.kind) && !hasText(payload.markdown)) return "文本内容为空";
  if (r.kind === "mindmap" && !hasText(payload.markmap)) return "脑图内容为空";
  if (r.kind === "quiz" && (!Array.isArray(payload.questions) || payload.questions.length === 0)) return "题组为空";
  if (r.kind === "flashcards" && !payload.flashcards) return "闪卡内容为空";
  if (r.kind === "infographic" && !payload.infographic) return "信息图内容为空";
  if (r.kind === "data_table" && !payload.data_table) return "数据表内容为空";
  if (
    ["video", "manim", "python_animation"].includes(r.kind) &&
    !payload.script &&
    !payload.video &&
    !payload.manim_code &&
    !payload.python_code &&
    !payload.animation_preview &&
    !payload.audio_url &&
    !payload.cover_url
  ) {
    return "讲解资源为空";
  }
  if (r.kind === "ppt" && !payload.ppt) return "PPT 任务为空";
  return "";
}

function resourcePreview(r: ResourceItem): string {
  const payload = (r.payload || {}) as Record<string, unknown>;
  const markdown = payload.markdown;
  const markmap = payload.markmap;
  const questions = payload.questions;
  const script = payload.script;
  const ppt = payload.ppt as ResourceItem["payload"]["ppt"];
  const flashcards = payload.flashcards as ResourceItem["payload"]["flashcards"];
  const infographic = payload.infographic as ResourceItem["payload"]["infographic"];
  const dataTable = payload.data_table as ResourceItem["payload"]["data_table"];
  const animationPreview = payload.animation_preview as ResourceItem["payload"]["animation_preview"];
  if (typeof markdown === "string") {
    return withoutCodeBlocks(markdown)
      .replace(/[#>*_`\[\]\(\)]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 86);
  }
  if (typeof markmap === "string") {
    return markmap
      .split("\n")
      .map((line) => line.replace(/^#+\s*/, "").trim())
      .filter(Boolean)
      .slice(0, 4)
      .join(" / ")
      .slice(0, 86);
  }
  if (Array.isArray(questions)) return `${questions.length} 道题，提交后会更新掌握情况与错因。`;
  if (flashcards?.cards?.length) return `${flashcards.cards.length} 张主动回忆卡，可翻面与标记掌握。`;
  if (infographic?.sections?.length) return `${infographic.sections.length} 个视觉区块，一图串起结论、过程与边界。`;
  if (dataTable?.rows?.length) return `${dataTable.rows.length} 行知识对照，可复制为 CSV。`;
  if (animationPreview?.stages?.length) return `${animationPreview.stages.length} 个动态步骤，可直接预览并下载 Python 代码。`;
  if (typeof script === "string") return script.replace(/\s+/g, " ").trim().slice(0, 86);
  if (ppt?.status === "ready") return `${ppt.total_pages || ""} 页复习演示已生成，可以下载。`;
  if (ppt?.status === "building") return "正在生成大纲、排版与配图。";
  if (ppt?.error) return ppt.error.slice(0, 86);
  return "";
}

export default function ResourceCard({
  r,
  defaultOpen = false,
  versionCount = 1,
  onQuizEvaluated,
  onAudioQuestion,
  onOpenMistakes,
  interactionBusy = false,
}: {
  r: ResourceItem;
  defaultOpen?: boolean;
  versionCount?: number;
  onQuizEvaluated?: (report: { path?: PathPlan; profile_version?: number }) => void;
  onAudioQuestion?: (
    prompt: string,
    display: string,
    action: "rephrase" | "example" | "quiz" | "question",
  ) => Promise<boolean>;
  onOpenMistakes?: () => void;
  interactionBusy?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const payload = r.payload || {};
  const interactiveAudio = payload.template === "interactive_audio";
  const baseMeta = KIND_META[r.kind] || { label: r.kind, code: r.kind.toUpperCase(), icon: "资", variant: "neutral" as const, hint: "" };
  const meta = interactiveAudio
    ? { label: "互动音频", code: "听讲", icon: "听", variant: "success" as const, hint: "来源约束的短讲解；可边听边暂停提问" }
    : baseMeta;
  const grounded = r.payload?.grounded;
  const issue = resourceIssue(r);
  const [audioPath, setAudioPath] = useState(payload.audio_url || "");
  const [audioState, setAudioState] = useState(payload.audio);
  const audioUrl = apiAssetUrl(audioPath);
  const audioProvider = String(audioState?.provider || "");
  const isSuperVoice = audioProvider === "spark_super_tts";
  const isStandardVoiceFallback = audioProvider === "spark_tts" && Boolean(audioState?.degraded);
  const coverUrl = apiAssetUrl(payload.cover_url);
  const narration = payload.audio_narration || "";
  const isText = TEXT_KINDS.has(r.kind);
  const preview = resourcePreview(r);

  async function retryAudio(): Promise<boolean> {
    const response = await apiPost<{ resource: ResourceItem; audio?: ResourceItem["payload"]["audio"] }>(
      `/resources/${r.id}/audio`,
      { user_id: USER_ID },
    );
    const nextPayload = response.resource.payload || {};
    setAudioPath(nextPayload.audio_url || "");
    setAudioState(response.audio || nextPayload.audio);
    return Boolean(nextPayload.audio_url);
  }

  return (
    <Panel className="animate-rise overflow-hidden transition duration-200 hover:border-[#C8D1C9]">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-4 text-left transition hover:bg-[#F7F9F6] sm:px-5"
      >
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] border border-[#E5E9E3] bg-[#FBFCFA] text-sm font-bold text-[#57635A] shadow-sm">
          {meta.icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="mb-1 flex flex-wrap items-center gap-2">
            <Badge variant={meta.variant}>{meta.code}</Badge>
            <span className="text-[11px] font-semibold text-[#8B958D]">{meta.label}</span>
            {versionCount > 1 && <Badge variant="neutral">{versionCount} 个版本</Badge>}
          </span>
          <span className="block truncate text-base font-bold text-[#182119]">{r.title}</span>
          {preview && <span className="mt-1 block truncate text-xs leading-5 text-[#57635A]">{preview}</span>}
          <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[#8B958D]">
            <span>{kpName(r.kp)}</span>
          </span>
        </span>
        {grounded === false && <Badge variant="warn" title="来源核对未通过或未完成，建议复核">待复核</Badge>}
        {issue && <Badge variant="danger">内容待补全</Badge>}
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border border-[#D8DED7] bg-[#F7F8F5] text-sm font-black text-[#57635A] transition ${open ? "rotate-90" : ""}`} aria-hidden>
          ›
        </span>
        <span className="sr-only">{open ? "收起" : "查看"}</span>
      </button>

      {open && (
        <div className="border-t border-[#E5E9E3] bg-white px-4 py-4">
          {meta.hint && (
            <p className="mb-3 rounded-[10px] border border-[#E5E9E3] bg-[#FBFCFA] px-3 py-2 text-xs leading-5 text-[#57635A]">{meta.hint}</p>
          )}

          {isText && (audioPath || narration || audioState || payload.cover_url) && (
            <div className="mb-4 grid gap-3 rounded-[12px] border border-[#D2DAD2] bg-[#F0F6F2] p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div className="min-w-0">
                <div className="text-[11px] font-bold tracking-[0.14em] text-[#0F6B50]">
                  {narration
                    ? audioUrl
                      ? isSuperVoice ? "星火超拟人互动讲解" : "普通星火语音讲解"
                      : "互动讲解 · 浏览器朗读"
                    : audioUrl
                      ? isSuperVoice ? "星火超拟人语音讲解" : "普通星火语音讲解"
                      : "星火知识封面"}
                </div>
                <p className="mt-1 text-xs leading-5 text-[#57635A]">
                    {audioPath || narration
                      ? onAudioQuestion
                        ? "边听边问；提问时音频会暂停，回答后从原进度继续。"
                      : "先听一遍重点，再结合正文中的例子深入学习。"
                      : "用一张图先建立知识点的整体印象。"}
                </p>
                {(audioUrl || narration || audioState) && (
                  <InteractiveAudioPlayer
                    src={audioUrl}
                    narration={narration}
                    audioState={audioState}
                    resourceTitle={r.title}
                    disabled={interactionBusy}
                    onAsk={onAudioQuestion}
                    onRetry={interactiveAudio ? retryAudio : undefined}
                  />
                )}
                {isStandardVoiceFallback && (
                  <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] leading-5 text-amber-800">
                    当前播放的是普通星火语音，不是已配置的超拟人音色。超拟人服务恢复后可点“重新生成云端语音”切回。
                  </p>
                )}
              </div>
              {coverUrl && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={coverUrl}
                  alt={`${r.title}封面`}
                  className="h-20 w-full rounded-[10px] border border-[#D2DAD2] object-cover sm:w-28"
                />
              )}
            </div>
          )}

          {issue ? (
            <Notice
              tone="warn"
              title={issue}
              desc="这份资料已保留，但当前内容不完整。可以重新整理同类内容。"
            />
          ) : r.kind === "mindmap" && payload.markmap ? (
            <Markmap markdown={payload.markmap} />
          ) : r.kind === "quiz" && payload.questions ? (
            <QuizPlayer resourceId={r.id} questions={payload.questions} onEvaluated={onQuizEvaluated} onOpenMistakes={onOpenMistakes} />
          ) : r.kind === "flashcards" && payload.flashcards ? (
            <FlashcardsBlock artifact={payload.flashcards} />
          ) : r.kind === "infographic" && payload.infographic ? (
            <InfographicBlock artifact={payload.infographic} />
          ) : r.kind === "data_table" && payload.data_table ? (
            <DataTableBlock artifact={payload.data_table} />
          ) : ["video", "manim", "python_animation"].includes(r.kind) ? (
            <VideoBlock payload={payload} kind={r.kind} />
          ) : r.kind === "ppt" ? (
            <PptBlock payload={payload} />
          ) : payload.markdown ? (
            <>
              {payload.one_page_visual && <OnePageVisual visual={payload.one_page_visual} />}
              {payload.one_page_visual?.image_url ? (
                <details className="rounded-xl border border-[#E5E9E3] bg-[#FBFCFA] px-4 py-3">
                  <summary className="cursor-pointer text-xs font-bold text-[#0F6B50]">查看文字版与出处</summary>
                  <div className="mt-3 border-t border-[#E5E9E3] pt-3">
                    <Markdown text={payload.markdown} citeBase={r.id} citations={r.citations} allowCodeBlocks={r.kind === "code"} />
                  </div>
                </details>
              ) : (
                <Markdown text={payload.markdown} citeBase={r.id} citations={r.citations} allowCodeBlocks={r.kind === "code"} />
              )}
            </>
          ) : (
            <Notice tone="warn" title="暂时无法展示这类内容" desc="内容已安全保留，系统不会把内部数据直接展示给学习者。" />
          )}

        </div>
      )}
    </Panel>
  );
}
