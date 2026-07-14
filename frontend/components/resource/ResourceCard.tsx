"use client";

import { useState } from "react";
import Markdown from "@/components/chat/Markdown";
import { Badge, Notice, Panel } from "@/components/ui";
import { kpName } from "@/lib/kp";
import type { PathPlan, ResourceItem } from "@/lib/types";
import Markmap from "./Markmap";
import QuizPlayer from "./QuizPlayer";
import VideoBlock from "./VideoBlock";
import { apiAssetUrl } from "@/lib/api";

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
  doc: { label: "图文讲解", code: "讲解", icon: "文", variant: "info", hint: "根据课程资料整理，正文脚注可查看出处" },
  code: { label: "代码练习", code: "代码", icon: "码", variant: "success", hint: "可运行片段与逐段讲解" },
  reading: { label: "延伸阅读", code: "阅读", icon: "读", variant: "neutral", hint: "围绕当前知识点补充阅读材料" },
  mindmap: { label: "知识导图", code: "导图", icon: "图", variant: "info", hint: "按掌握情况标注：已掌握✅ 待巩固⚠️ 未解锁🔒" },
  quiz: { label: "巩固练习", code: "练习", icon: "练", variant: "warn", hint: "提交后更新掌握情况、错因与后续路线" },
  video: { label: "讲解稿", code: "讲稿", icon: "影", variant: "neutral", hint: "适合录制讲解视频的分镜与旁白素材" },
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
  if (
    r.kind === "video" &&
    !payload.script &&
    !payload.video &&
    !payload.manim_code &&
    !payload.audio_url &&
    !payload.cover_url
  ) {
    return "讲解资源为空";
  }
  return "";
}

function resourcePreview(r: ResourceItem): string {
  const payload = (r.payload || {}) as Record<string, unknown>;
  const markdown = payload.markdown;
  const markmap = payload.markmap;
  const questions = payload.questions;
  const script = payload.script;
  if (typeof markdown === "string") {
    return markdown
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
  if (typeof script === "string") return script.replace(/\s+/g, " ").trim().slice(0, 86);
  return "";
}

export default function ResourceCard({
  r,
  defaultOpen = false,
  versionCount = 1,
  onQuizEvaluated,
}: {
  r: ResourceItem;
  defaultOpen?: boolean;
  versionCount?: number;
  onQuizEvaluated?: (report: { path?: PathPlan; profile_version?: number }) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const meta = KIND_META[r.kind] || { label: r.kind, code: r.kind.toUpperCase(), icon: "资", variant: "neutral" as const, hint: "" };
  const grounded = r.payload?.grounded;
  const issue = resourceIssue(r);
  const payload = r.payload || {};
  const audioUrl = apiAssetUrl(payload.audio_url);
  const coverUrl = apiAssetUrl(payload.cover_url);
  const isText = TEXT_KINDS.has(r.kind);
  const created = r.created_at ? r.created_at.replace("T", " ").slice(0, 16) : "";
  const preview = resourcePreview(r);

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
            {r.citations?.length > 0 && (
              <span className="text-emerald-600">{r.citations.length} 条出处</span>
            )}
            {!r.citations?.length && <span>学习资料</span>}
          </span>
        </span>
        {grounded === true && isText && (
          <Badge variant="success" title="内容已和引用来源核对">出处已核对</Badge>
        )}
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

          {isText && (payload.audio_url || payload.cover_url) && (
            <div className="mb-4 grid gap-3 rounded-[12px] border border-[#D2DAD2] bg-[#F0F6F2] p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div className="min-w-0">
                <div className="text-[11px] font-bold tracking-[0.14em] text-[#0F6B50]">
                  {payload.audio_url ? "星火语音讲解" : "星火知识封面"}
                </div>
                <p className="mt-1 text-xs leading-5 text-[#57635A]">
                  {payload.audio_url ? "先听一遍重点，再结合正文和脚注深入学习。" : "用一张图先建立知识点的整体印象。"}
                </p>
                {audioUrl && <audio src={audioUrl} controls className="mt-2 h-9 w-full" />}
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
            <QuizPlayer resourceId={r.id} questions={payload.questions} onEvaluated={onQuizEvaluated} />
          ) : r.kind === "video" ? (
            <VideoBlock payload={payload} />
          ) : payload.markdown ? (
            <Markdown text={payload.markdown} citeBase={r.id} citations={r.citations} />
          ) : (
            <div className="space-y-2">
              <Notice tone="warn" title="暂时无法展示这类内容" desc="内容已保留，可稍后由系统补充展示方式。" />
              <pre className="max-h-72 overflow-auto rounded-[10px] bg-[#0E1411] p-3 text-xs text-slate-100">
                {JSON.stringify(payload, null, 2)}
              </pre>
            </div>
          )}

          {r.citations?.length > 0 && (
            <div className="mt-4 rounded-[14px] border border-[#26312A] bg-[#0E1411] px-3 py-3 text-[#C7D2C9]">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-[11px] font-bold tracking-[0.18em] text-[#7ED9A6]">内容出处</span>
                {isText && <span className="text-[11px] text-[#7E8B82]">正文脚注 [^n] 与这里逐条对应</span>}
              </div>
              <div className="space-y-1">
                {r.citations.map((c, i) => (
                  <div
                    key={i}
                    id={`${r.id}-cite-${i + 1}`}
                    className="cite-anchor grid grid-cols-[42px_minmax(0,1fr)] gap-2 rounded-[8px] px-2 py-1 text-xs leading-5 text-[#C7D2C9]"
                  >
                    <span className="font-mono font-bold text-[#7ED9A6]">[^{i + 1}]</span>
                    <span>{c}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-[#8B958D]">
            <span>资料编号 {r.id}</span>
            {created && <span>整理于 {created}</span>}
            {grounded === true && <span className="text-emerald-600">出处已核对</span>}
          </div>
        </div>
      )}
    </Panel>
  );
}
