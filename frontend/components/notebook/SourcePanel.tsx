"use client";

import { BookOpen, Check, CircleAlert, FileText, Plus, ShieldAlert, TriangleAlert, UploadCloud } from "lucide-react";

export type KnowledgeSourceStatus = "processing" | "indexed" | "degraded" | "failed" | "quarantined" | "inactive";

export interface KnowledgeSource {
  id: string;
  title: string;
  filename?: string;
  source_type: string;
  chunk_count: number;
  status: KnowledgeSourceStatus;
  status_detail?: string;
  selectable?: boolean;
  degraded?: boolean;
  created_at?: string;
  updated_at?: string;
  indexed_at?: string;
}

export const COURSE_SOURCE_ID = "__course__";

export function isSourceSelectable(source: KnowledgeSource): boolean {
  return source.selectable ?? ["indexed", "degraded"].includes(source.status);
}

function sourceStatusText(source: KnowledgeSource): string {
  if (source.status_detail) return source.status_detail;
  if (source.status === "indexed") return `${source.chunk_count} 个可引用片段`;
  if (source.status === "degraded") return `${source.chunk_count} 个片段 · 降级解析`;
  if (source.status === "processing") return "正在解析并建立索引";
  if (source.status === "failed") return "解析失败，请重新上传";
  if (source.status === "quarantined") return "资料已隔离";
  return "资料已停用";
}

function SourceStatusIcon({ source }: { source: KnowledgeSource }) {
  if (source.status === "processing") return <UploadCloud size={17} className="animate-pulse" />;
  if (source.status === "degraded") return <TriangleAlert size={17} />;
  if (source.status === "failed") return <CircleAlert size={17} />;
  if (source.status === "quarantined" || source.status === "inactive") return <ShieldAlert size={17} />;
  return <FileText size={17} />;
}

export default function SourcePanel({
  sources,
  selectedIds,
  uploading,
  uploadNote,
  uploadError,
  onAdd,
  onToggleCourse,
  onToggle,
}: {
  sources: KnowledgeSource[];
  selectedIds: string[];
  uploading: boolean;
  uploadNote: string;
  uploadError: boolean;
  onAdd: () => void;
  onToggleCourse: () => void;
  onToggle: (sourceId: string) => void;
}) {
  const usingCourse = selectedIds.includes(COURSE_SOURCE_ID);
  const selectedCount = selectedIds.length;

  return (
    <div className="notebook-column flex h-full min-h-0 flex-col" aria-label="学习来源">
      <div className="notebook-column-header">
        <div>
          <div className="notebook-column-kicker">LEARNING SOURCES</div>
          <h2>学习来源</h2>
        </div>
        <span className="source-count">{selectedCount}</span>
      </div>

      <div className="border-b border-[#E1E4EC] p-3">
        <button onClick={onAdd} disabled={uploading} className="source-add-button">
          {uploading ? <UploadCloud size={17} className="animate-pulse" /> : <Plus size={18} />}
          {uploading ? "正在建立索引" : "添加学习资料"}
        </button>
        <p className="mt-2 px-1 text-[11px] leading-5 text-[#777D8B]">
          支持 Word、PDF、图片、Markdown 和文本，可同时选择课程知识库与多份资料。
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        <button onClick={onToggleCourse} className={`source-row ${usingCourse ? "is-selected" : ""}`}>
          <span className="source-icon is-course"><BookOpen size={17} /></span>
          <span className="min-w-0 flex-1 text-left">
            <strong>课程知识库</strong>
            <small>可与个人资料一起参与回答</small>
          </span>
          <span className={`source-check ${usingCourse ? "is-checked" : ""}`}>
            {usingCourse && <Check size={13} />}
          </span>
        </button>

        {sources.map((source) => {
          const selected = selectedIds.includes(source.id);
          const active = isSourceSelectable(source);
          const statusText = sourceStatusText(source);
          return (
            <button
              key={source.id}
              onClick={() => active && onToggle(source.id)}
              disabled={!active}
              className={`source-row is-${source.status} ${selected ? "is-selected" : ""} ${!active ? "is-disabled" : ""}`}
              title={statusText}
            >
              <span className="source-icon"><SourceStatusIcon source={source} /></span>
              <span className="min-w-0 flex-1 text-left">
                <strong className="truncate">{source.title || source.filename || "未命名资料"}</strong>
                <small>{active && source.status === "indexed" ? `${source.chunk_count} 个可引用片段` : statusText}</small>
              </span>
              <span className={`source-check ${selected ? "is-checked" : ""}`}>
                {selected && <Check size={13} />}
              </span>
            </button>
          );
        })}

        {sources.length === 0 && (
          <div className="source-empty">
            <UploadCloud size={20} />
            <strong>还没有个人资料</strong>
            <span>上传讲义或笔记后，它会出现在这里。</span>
          </div>
        )}
      </div>

      {uploadNote && (
        <div className={`m-3 mt-0 rounded-[8px] px-3 py-2 text-xs leading-5 ${uploadError ? "bg-[#FFF0ED] text-[#A33A25]" : "bg-[#EAF5EF] text-[#0F6B50]"}`}>
          {uploadNote}
        </div>
      )}
    </div>
  );
}
