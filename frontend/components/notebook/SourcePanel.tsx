"use client";

import { BookOpen, Check, FileText, Plus, UploadCloud } from "lucide-react";

export interface KnowledgeSource {
  id: string;
  title: string;
  filename?: string;
  source_type: string;
  chunk_count: number;
  status: string;
  created_at?: string;
}

export default function SourcePanel({
  sources,
  selectedIds,
  uploading,
  uploadNote,
  uploadError,
  onAdd,
  onUseCourse,
  onToggle,
}: {
  sources: KnowledgeSource[];
  selectedIds: string[];
  uploading: boolean;
  uploadNote: string;
  uploadError: boolean;
  onAdd: () => void;
  onUseCourse: () => void;
  onToggle: (sourceId: string) => void;
}) {
  const usingCourse = selectedIds.length === 0;

  return (
    <div className="notebook-column flex h-full min-h-0 flex-col" aria-label="学习来源">
      <div className="notebook-column-header">
        <div>
          <div className="notebook-column-kicker">LEARNING SOURCES</div>
          <h2>学习来源</h2>
        </div>
        <span className="source-count">{selectedIds.length || 1}</span>
      </div>

      <div className="border-b border-[#E1E4EC] p-3">
        <button onClick={onAdd} disabled={uploading} className="source-add-button">
          {uploading ? <UploadCloud size={17} className="animate-pulse" /> : <Plus size={18} />}
          {uploading ? "正在建立索引" : "添加学习资料"}
        </button>
        <p className="mt-2 px-1 text-[11px] leading-5 text-[#777D8B]">
          支持 PDF、图片、Markdown 和文本。选中后，回答与学习产物只依据这些资料。
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        <button onClick={onUseCourse} className={`source-row ${usingCourse ? "is-selected" : ""}`}>
          <span className="source-icon is-course"><BookOpen size={17} /></span>
          <span className="min-w-0 flex-1 text-left">
            <strong>课程知识库</strong>
            <small>未选择附件时使用内置教材</small>
          </span>
          <span className={`source-check ${usingCourse ? "is-checked" : ""}`}>
            {usingCourse && <Check size={13} />}
          </span>
        </button>

        {sources.map((source) => {
          const selected = selectedIds.includes(source.id);
          const active = source.status === "indexed";
          return (
            <button
              key={source.id}
              onClick={() => active && onToggle(source.id)}
              disabled={!active}
              className={`source-row ${selected ? "is-selected" : ""} ${!active ? "is-disabled" : ""}`}
            >
              <span className="source-icon"><FileText size={17} /></span>
              <span className="min-w-0 flex-1 text-left">
                <strong className="truncate">{source.title || source.filename || "未命名资料"}</strong>
                <small>{active ? `${source.chunk_count} 个可引用片段` : "暂不可使用"}</small>
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
