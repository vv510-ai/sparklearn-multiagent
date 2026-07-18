"use client";

import { BookOpen, Check, CircleAlert, FileText, FolderPlus, LoaderCircle, Plus, ShieldAlert, TriangleAlert, UploadCloud } from "lucide-react";
import type { LearningNotebook } from "@/lib/types";

export type KnowledgeSourceStatus = "processing" | "indexed" | "degraded" | "failed" | "quarantined" | "inactive";

export interface KnowledgeSource {
  id: string;
  notebook_id?: string;
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
  notebooks,
  activeNotebookId,
  notebookLoading,
  notebookError,
  sources,
  selectedIds,
  uploading,
  uploadNote,
  uploadError,
  onAdd,
  onCreateNotebook,
  onSelectNotebook,
  onToggleCourse,
  onToggle,
}: {
  notebooks: LearningNotebook[];
  activeNotebookId?: string;
  notebookLoading: boolean;
  notebookError: string;
  sources: KnowledgeSource[];
  selectedIds: string[];
  uploading: boolean;
  uploadNote: string;
  uploadError: boolean;
  onAdd: () => void;
  onCreateNotebook: () => void;
  onSelectNotebook: (notebookId: string) => void;
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
        <div className="mb-2 flex items-center justify-between gap-2 px-1">
          <div>
            <div className="text-[10px] font-bold tracking-[0.14em] text-[#8A91A0]">SUBJECT FOLDER</div>
            <div className="mt-0.5 text-sm font-bold text-[#2B303B]">当前科目书本</div>
          </div>
          <button type="button" onClick={onCreateNotebook} className="inline-flex items-center gap-1 rounded-full border border-[#CFE0D8] bg-[#EFF7F3] px-2.5 py-1.5 text-[11px] font-bold text-[#0F6B50] transition hover:bg-[#E4F2EB]">
            <FolderPlus size={14} />新建
          </button>
        </div>

        {notebooks.length > 0 ? (
          <div className="relative">
            <select
              value={activeNotebookId || ""}
              disabled={notebookLoading}
              onChange={(event) => onSelectNotebook(event.target.value)}
              className="w-full appearance-none rounded-[10px] border border-[#DDE2EA] bg-white py-2.5 pl-3 pr-9 text-sm font-semibold text-[#343944] outline-none transition focus:border-[#83B7A5] focus:ring-4 focus:ring-[#E6F2ED] disabled:cursor-wait disabled:bg-[#F7F8FA]"
              aria-label="切换科目书本"
            >
              <option value="" disabled>选择一个科目书本</option>
              {notebooks.map((notebook) => (
                <option key={notebook.id} value={notebook.id}>
                  {notebook.emoji || "📘"} {notebook.title} · {notebook.source_count} 份资料
                </option>
              ))}
            </select>
            {notebookLoading && <LoaderCircle size={15} className="pointer-events-none absolute right-3 top-3 animate-spin text-[#7C8492]" />}
          </div>
        ) : (
          <button type="button" onClick={onCreateNotebook} className="flex w-full items-center gap-3 rounded-[10px] border border-dashed border-[#BFC9D6] bg-[#F8F9FC] px-3 py-3 text-left transition hover:border-[#83B7A5] hover:bg-[#F1F7F4]">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[9px] bg-[#E7F3ED] text-[#0F6B50]"><Plus size={17} /></span>
            <span><strong className="block text-sm text-[#343944]">新建第一个科目书本</strong><small className="mt-0.5 block text-[11px] text-[#858C9A]">每个科目的资料相互独立</small></span>
          </button>
        )}
        <p className="mt-2 px-1 text-[11px] leading-5 text-[#858C9A]">切换科目后，下方只显示这本书的资料与学习记录。</p>
        {notebookError && <p className="mt-2 rounded-[8px] bg-[#FFF3ED] px-2.5 py-2 text-[11px] leading-4 text-[#A14D2E]">{notebookError}</p>}
      </div>

      <div className="border-b border-[#E1E4EC] p-3">
        <button onClick={onAdd} disabled={uploading || !activeNotebookId} className="source-add-button" title={activeNotebookId ? "向当前科目上传资料" : "请先新建或选择一个科目书本"}>
          {uploading ? <UploadCloud size={17} className="animate-pulse" /> : <Plus size={18} />}
          {uploading ? "正在建立索引" : "添加学习资料"}
        </button>
        <p className="mt-2 px-1 text-[11px] leading-5 text-[#777D8B]">
          {activeNotebookId ? "支持 Word、PDF、图片、Markdown 和文本，资料只会保存到当前科目。" : "请先新建或选择科目书本，再上传对应的讲义和笔记。"}
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

        {sources.length === 0 && activeNotebookId && (
          <div className="source-empty">
            <UploadCloud size={20} />
            <strong>这本书还没有资料</strong>
            <span>上传这门科目的讲义或笔记后，它会出现在这里。</span>
          </div>
        )}

        {!activeNotebookId && (
          <div className="source-empty">
            <FolderPlus size={20} />
            <strong>先选择科目书本</strong>
            <span>课程知识库仍可使用，个人资料会按科目分别保存。</span>
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
