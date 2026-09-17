"use client";

import { BookOpen, Check, Code2, FileUp, GraduationCap, Languages, PencilLine, UploadCloud, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiUpload, USER_ID } from "@/lib/api";
import type { CourseScope, StudySurvey } from "@/lib/assessment";
import type { LearningNotebook } from "@/lib/types";
import { DEFAULT_SURVEY } from "@/components/onboarding/LearningIntake";
import type { KnowledgeSource } from "./SourcePanel";

type CourseOption = { id: NonNullable<StudySurvey["course_key"]>; title: string; description: string };

export default function CourseCreateDialog({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: (notebook: LearningNotebook) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef<{ notebook: LearningNotebook; uploaded: Map<File, string> } | null>(null);
  const submitting = useRef(false);
  const [catalogue, setCatalogue] = useState<CourseOption[]>([]);
  const [selection, setSelection] = useState<StudySurvey["course_key"] | "upload" | "">("");
  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const loadCatalogue = () => {
    setError("");
    void apiGet<{ items: CourseOption[] }>("/notebooks/learning/catalogue")
      .then(result => setCatalogue(result.items))
      .catch(() => setError("课程列表暂时无法加载，请重试。"));
  };
  useEffect(() => { dialog.current?.showModal(); loadCatalogue(); }, []);
  const choose = (key: NonNullable<typeof selection>, name: string) => {
    setSelection(key); setTitle(key === "custom" || key === "upload" ? "" : name); setError("");
  };
  const addFiles = (incoming: File[]) => {
    if (files.length + incoming.length > 6) { setError("每次最多上传 6 份资料，请分批添加。"); return; }
    setFiles(current => [...current, ...incoming]); setError("");
    if (!selection) setSelection("upload");
    if (!title.trim() && incoming[0]) setTitle(incoming[0].name.replace(/\.[^.]+$/, "").slice(0, 120));
  };
  const create = async () => {
    if (submitting.current || !selection || !title.trim() || (selection === "upload" && !files.length)) return;
    submitting.current = true; setBusy(true); setError("");
    try {
      if (!pending.current) {
        setNote("正在创建课程…");
        const notebook = await apiPost<LearningNotebook>("/notebooks", { user_id: USER_ID, title: title.trim() });
        pending.current = { notebook, uploaded: new Map() }; setCreated(true);
      }
      const { notebook, uploaded } = pending.current;
      for (const file of files) {
        if (uploaded.has(file)) continue;
        setNote(`正在解析 ${file.name}…`);
        const form = new FormData();
        form.append("file", file); form.append("title", file.name); form.append("user_id", USER_ID); form.append("notebook_id", notebook.id);
        const result = await apiUpload<{ source: KnowledgeSource }>("/knowledge/upload", form);
        if (!result.source.selectable) throw new Error(result.source.status_detail || "资料还未解析完成，请稍后重试。");
        uploaded.set(file, result.source.id);
      }
      const key = selection === "upload" ? "custom" : selection;
      const sourceIds = files.map(file => uploaded.get(file)).filter((id): id is string => Boolean(id));
      setNote(sourceIds.length ? "正在根据课本整理知识点和起点题，通常需要几十秒…" : key === "custom" ? "正在围绕主题准备课程范围与起点题，通常需要几十秒…" : "正在准备入门讲义与起点题…");
      await apiPost<CourseScope>(`/notebooks/${notebook.id}/learning/prepare`, {
        title: title.trim(), course_key: key, source_ids: sourceIds,
        survey: { ...DEFAULT_SURVEY, notebook_id: notebook.id, course_key: key, course_title: title.trim(), source_ids: sourceIds,
          materials_status: sourceIds.length ? "已有资料" : "暂时没有" },
      });
      await onCreated(notebook);
    } catch (e) {
      setError(e instanceof Error ? e.message.replace(/^(?:POST|GET) \S+ → \d+:?\s*/, "") : "课程暂未创建完成，请重试。");
      setNote(pending.current ? "课程与已上传资料已保存，重试会继续处理这门课程。" : "");
    } finally { submitting.current = false; setBusy(false); }
  };
  const icons = { ds_algo: BookOpen, python: Code2, calculus: GraduationCap, cet6: Languages, custom: PencilLine, upload: FileUp };
  const options = [...catalogue.filter(c => c.id !== "custom"),
    { id: "custom" as const, title: "自定义学习主题", description: "英语、线性代数、专业课…输入你想学的内容" },
    { id: "upload" as const, title: "上传课本生成课程", description: "围绕你的教材、讲义或笔记整理知识点与题目" }];
  return <dialog ref={dialog} className="course-create-dialog" aria-labelledby="course-create-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={e => { e.preventDefault(); void create(); }}>
      <header className="course-create-header"><div><p>从你想学的内容开始</p><h2 id="course-create-title">新建课程</h2></div><button type="button" aria-label="关闭新建课程" onClick={onClose} disabled={busy}><X size={20} /></button></header>
      <p className="course-create-intro">选一门经典课程，或带上自己的主题与课本。每门课都有独立的资料、测评和学习计划。</p>
      <fieldset disabled={busy || created} className="course-create-options"><legend>选择课程起点</legend>
        {options.map(option => { const Icon = icons[option.id] || BookOpen; return <label key={option.id} className={selection === option.id ? "is-selected" : ""}>
          <input type="radio" name="new-course" aria-label={option.title} checked={selection === option.id} onChange={() => choose(option.id, option.title)} />
          <Icon size={22} aria-hidden="true" /><span><strong>{option.title}</strong><small>{option.description}</small></span><Check size={17} className="course-choice-check" aria-hidden="true" />
        </label>; })}
      </fieldset>
      {catalogue.length === 0 && error && <button type="button" className="secondary-action" onClick={loadCatalogue}>重新加载课程</button>}
      <label className="course-create-title-field" htmlFor="new-book-title">课程名称或学习主题</label>
      <input id="new-book-title" className="course-create-input" maxLength={120} disabled={busy || created} value={title} onChange={e => setTitle(e.target.value)} placeholder="例如：大学英语阅读 / 线性代数 / 我的生物课本" />
      <div className="course-create-upload"><label><UploadCloud size={22} /><span><strong>{selection === "upload" ? "选择要学习的课本" : "已有课本？一起上传"}</strong><small>PDF、Word、文字或图片 · 最多 6 份{selection !== "upload" && " · 可选"}</small></span>
        <input type="file" aria-label="上传课程课本" multiple accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" disabled={busy} onChange={e => { addFiles(Array.from(e.target.files || [])); e.target.value = ""; }} /></label>
        {files.map((file, i) => <div className="course-create-file" key={`${file.name}-${i}`}><span>{file.name}</span><button type="button" aria-label={`移除 ${file.name}`} disabled={busy} onClick={() => setFiles(current => current.filter((_, index) => index !== i))}><X size={16} /></button></div>)}
      </div>
      <p className="course-create-hint">{files.length ? "创建时会读取所选资料，并显示实际使用的范围。生成题目的答案与难度仍需核对。" : selection === "custom" ? "没有课本也可以开始：围绕主题生成初步课程，之后可以补充资料。" : "创建后可以直接学习，也可以先做题，让计划更贴合你的起点。"}</p>
      {note && <p role="status" className="course-create-status">{note}</p>}
      {error && <p role="alert" className="course-create-error">{error}</p>}
      <footer><button type="button" className="secondary-action" onClick={onClose} disabled={busy}>取消</button><button type="submit" className="primary-action" disabled={busy || !selection || !title.trim() || (selection === "upload" && !files.length)}>{busy ? "正在准备课程…" : created ? "继续准备课程" : "创建并进入"}</button></footer>
    </form>
  </dialog>;
}
