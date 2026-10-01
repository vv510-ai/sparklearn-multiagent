"use client";

import { useRef, useState } from "react";
import { apiPost } from "@/lib/api";
import { readingError, readingRequestId, type ReadingSession } from "@/lib/reading";

type QuestionInput = { prompt: string; options: string[]; answer: number; paragraph: number; quote: string; explanation: string };
const newQuestion = (): QuestionInput => ({ prompt: "", options: ["", "", "", ""], answer: 0, paragraph: 0, quote: "", explanation: "" });

export default function ReadingImport({ notebookId, userId, onImported, onCancel }: { notebookId: string; userId: string; onImported: (data: ReadingSession) => void; onCancel: () => void }) {
  const key = `learnloop:reading-import:${userId}:${notebookId}`;
  const [title, setTitle] = useState(""); const [source, setSource] = useState("");
  const [sourceURL, setSourceURL] = useState(""); const [sourceType, setSourceType] = useState("past_paper");
  const [text, setText] = useState(""); const [questions, setQuestions] = useState<QuestionInput[]>([newQuestion()]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const request = useRef<{ content: string; id: string } | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const paragraphs = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  const material = () => ({ title: title.trim(), englishTitle: "", source: source.trim(), source_url: sourceURL.trim(), source_type: sourceType,
    paragraphs, questions: questions.map((q, i) => ({ id: `q${i + 1}`, skill: "阅读理解", prompt: q.prompt.trim(), options: q.options.map(s => s.trim()),
      answer: q.answer, evidence: { paragraph: q.paragraph, quote: q.quote.trim() }, explanation: q.explanation.trim(), optionFeedback: [], takeaway: "", drill: null, recall: null })) });
  const saveDraft = () => {
    try { localStorage.setItem(key, JSON.stringify({ title, source, sourceURL, sourceType, text, questions })); setNotice("导入草稿已保存在当前浏览器，仅此账号和课程可恢复。"); }
    catch { setError("浏览器无法保存草稿，请先复制原文和题目。"); }
  };
  const restore = () => {
    try {
      const d = JSON.parse(localStorage.getItem(key) || "null");
      if (!d || typeof d.text !== "string" || !Array.isArray(d.questions) || !d.questions.every((q: QuestionInput) => typeof q.prompt === "string" && q.options?.length === 4)) { setNotice("当前课程没有可恢复的导入草稿。"); return; }
      setTitle(d.title); setSource(d.source); setSourceURL(d.sourceURL); setSourceType(d.sourceType); setText(d.text); setQuestions(d.questions); setNotice("已恢复导入草稿。");
    } catch { setError("草稿格式无法读取，请使用原始材料重新导入。"); }
  };
  const update = (index: number, value: Partial<QuestionInput>) => setQuestions(items => items.map((q, i) => i === index ? { ...q, ...value } : q));
  const submit = async (pack: unknown) => {
    if (busy) return;
    setBusy(true); setError("");
    const content = JSON.stringify(pack);
    if (request.current?.content !== content) request.current = { content, id: readingRequestId() };
    try {
      const data = await apiPost<ReadingSession>(`/notebooks/${notebookId}/reading/import`, { request_id: request.current.id, material: pack });
      try { localStorage.removeItem(key); } catch { /* Optional local copy. */ }
      onImported(data);
    } catch (e) { setError(readingError(e)); }
    finally { setBusy(false); }
  };
  const submitForm = () => {
    if (!title.trim() || !source.trim() || !paragraphs.length) { setError("请先填写标题、来源和原文。"); return; }
    for (const [i, q] of questions.entries()) {
      if (!q.prompt.trim() || q.options.some(s => !s.trim()) || !q.explanation.trim() || !q.quote.trim()) { setError(`请补全第 ${i + 1} 题的题干、四个选项、原文证据和答案说明。`); return; }
      if (!paragraphs[q.paragraph]?.includes(q.quote.trim())) { setError(`第 ${i + 1} 题的证据没有出现在指定段落，请直接从原文复制连续片段。`); return; }
    }
    void submit(material());
  };
  const download = () => {
    const blob = new Blob([JSON.stringify(material(), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "阅读材料.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="reading-import" aria-label="导入自己的阅读材料">
    <div className="reading-heading"><div><span className="reading-eyebrow">准备一次，之后直接练习</span><h2>导入自己的真题</h2></div><button className="secondary-action" disabled={busy} onClick={onCancel}>返回今日任务</button></div>
    <p className="reading-muted">填写你持有的原文、题目和答案。内容仅存入当前账号与课程，答案和解析由导入者提供，本站未核验为官方答案。仅支持仔细阅读四选一。</p>
    <div className="reading-toolbar"><button className="secondary-action" disabled={busy} onClick={saveDraft}>保存导入草稿</button><button className="secondary-action" disabled={busy} onClick={restore}>恢复导入草稿</button></div>
    <fieldset disabled={busy}>
      <label>材料标题<input maxLength={180} value={title} onChange={e => setTitle(e.target.value)} placeholder="例如：2024年6月第三套 · 仔细阅读第一篇" /></label>
      <label>具体来源<input maxLength={600} value={source} onChange={e => setSource(e.target.value)} placeholder="年份、套卷、书名与页码，或材料提供者" /></label>
      <div className="reading-import-row"><label>材料类型<select value={sourceType} onChange={e => setSourceType(e.target.value)}><option value="past_paper">真题（由我提供，待核验）</option><option value="other">其他阅读材料</option></select></label><label>来源链接（选填）<input type="url" value={sourceURL} maxLength={1200} onChange={e => setSourceURL(e.target.value)} placeholder="https://…" /></label></div>
      <label>文章原文<textarea rows={9} maxLength={60000} value={text} onChange={e => setText(e.target.value)} placeholder="粘贴原文，用空行分开段落。" /></label><p className="reading-muted">已识别 {paragraphs.length} 个段落；原文不会由 AI 改写。</p>
      {questions.map((q, i) => <section className="reading-import-question" key={i} aria-label={`导入第 ${i + 1} 题`}><div className="reading-heading"><h3>第 {i + 1} 题</h3>{questions.length > 1 && <button type="button" className="reading-text-button" onClick={() => setQuestions(items => items.filter((_, n) => n !== i))}>移除此题</button>}</div>
        <label>题干<textarea rows={2} maxLength={2000} value={q.prompt} onChange={e => update(i, { prompt: e.target.value })} /></label>
        {q.options.map((option, j) => <label key={j}>选项 {String.fromCharCode(65 + j)}<input maxLength={2000} value={option} onChange={e => update(i, { options: q.options.map((s, n) => n === j ? e.target.value : s) })} /></label>)}
        <div className="reading-import-row"><label>标准答案<select value={q.answer} onChange={e => update(i, { answer: Number(e.target.value) })}>{[0, 1, 2, 3].map(n => <option key={n} value={n}>{String.fromCharCode(65 + n)}</option>)}</select></label><label>证据所在段落<select value={q.paragraph} onChange={e => update(i, { paragraph: Number(e.target.value) })}>{(paragraphs.length ? paragraphs : [""]).map((_, n) => <option key={n} value={n}>第 {n + 1} 段</option>)}</select></label></div>
        <label>原文证据<textarea rows={2} maxLength={4000} value={q.quote} onChange={e => update(i, { quote: e.target.value })} placeholder="从上方原文复制支持答案的连续片段。" /></label>
        <label>答案说明<textarea rows={3} maxLength={4000} value={q.explanation} onChange={e => update(i, { explanation: e.target.value })} placeholder="为什么支持该答案；其他选项哪里不符合原文。" /></label>
      </section>)}
      <button className="secondary-action" disabled={questions.length >= 10} onClick={() => setQuestions(items => [...items, newQuestion()])}>添加一道题</button>
    </fieldset>
    {error && <p role="alert" className="reading-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="reading-toolbar"><button className="primary-action" disabled={busy} onClick={submitForm}>{busy ? "正在保存…" : "保存材料，开始练习"}</button></div>
    <details className="reading-details"><summary>批量导入与备份</summary><p>也可导入符合上述字段的 JSON 材料包。来源、答案和证据仍会逐项校验；不会自动从外站抓取内容。</p><div className="reading-toolbar"><button className="secondary-action" disabled={busy} onClick={download}>导出当前材料 / 模板</button><button className="secondary-action" disabled={busy} onClick={() => file.current?.click()}>导入 JSON 材料包</button></div><input ref={file} type="file" accept=".json,application/json" hidden onChange={async e => { const f = e.target.files?.[0]; e.target.value = ""; if (!f) return; if (f.size > 500000) { setError("材料包不能超过 500 KB。"); return; } try { await submit(JSON.parse(await f.text())); } catch { setError("这不是有效的 JSON 材料包。"); } }} /></details>
  </section>;
}
