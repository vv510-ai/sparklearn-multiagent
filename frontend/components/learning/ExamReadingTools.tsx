"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { readingError, readingRequestId } from "@/lib/reading";
import type { WordCard, WordDetail, WordLookup } from "@/lib/cet6";
import StudyDialog from "../ui/StudyDialog";
import WordPronunciation from "./WordPronunciation";
import "./exam-reading-tools.css";

type Selection = { id: string; word: string; sentence: string; paragraph: string };
type Explanation = { note: string; content: { main_clause: string; clauses: { quote: string; role: string; explanation: string }[]; translation: string; connection: string; check_question: string; check_answer: string } };
type ExcerptDraft = { notes: Record<string, string>; explanations: Record<string, Explanation>; answers: Record<string, string> };
type Props = { notebookId: string; paperId: string; kind: string; question: number; version: string; paragraphs: string[]; duringAttempt: boolean; onHelp: () => void; preferredSenses?: Record<string, string> };
type Operation = "lookup" | "save" | "explain" | "reload";
const sentences = (p: string) => p.match(/[^.!?]+(?:[.!?]+[”"']?|$)/g)?.map(s => s.trim()).filter(Boolean) || [p];
const normalizedForm = (text: string) => text.trim().toLowerCase().replaceAll("’", "'");
const wordParts = (text: string) => text.split(/([A-Za-z]+(?:['’\-][A-Za-z]+)*(?:(?<=s)['’])?)/gi);

export default function ExamReadingTools(props: Props) {
  const [selected, setSelected] = useState<Selection | null>(null), [open, setOpen] = useState(false);
  const drafts = useRef(new Map<string, ExcerptDraft>());
  const pick = (selection: Selection) => {
    if (!drafts.current.has(selection.id)) drafts.current.set(selection.id, { notes: {}, explanations: {}, answers: {} });
    setSelected(selection); setOpen(true);
  };
  return <>
    <p className="exam-muted">点词查义，关闭后接着读；长难句可用段落下的“拆解句子”。{props.duringAttempt && "查词和拆句会记为借助帮助。"}</p>
    <div lang="en" className="exam-source-text">
      {props.paragraphs.map((paragraph, p) => <div key={p}>
        <p>{wordParts(paragraph).map((part, i, parts) => /^[A-Za-z]/.test(part) ? <button className="exam-word" key={i} aria-label={`查词 ${part}`} aria-haspopup="dialog" data-selected={selected?.id === `${p}:${i}`} onClick={() => {
          const offset = parts.slice(0, i).join("").length;
          const sentence = sentences(paragraph).find(s => { const start = paragraph.indexOf(s); return start <= offset && offset < start + s.length; }) || paragraph;
          pick({ id: `${p}:${i}`, word: part, sentence: sentence.slice(0, 1500), paragraph });
        }}>{part}</button> : part)}</p>
        <button className="exam-sentence-pick" lang="zh-CN" aria-haspopup="dialog" onClick={() => {
          const selection = window.getSelection()?.toString().trim() || "";
          const sentence = selection.length >= 10 && selection.length <= 1500 && paragraph.includes(selection) ? selection : sentences(paragraph)[0];
          pick({ id: `${p}:sentence:${sentence}`, word: "", sentence, paragraph });
        }}>拆解第 {p + 1} 段句子</button>
      </div>)}
    </div>
    {selected && <ExcerptPanel key={selected.id} {...props} selected={selected} draft={drafts.current.get(selected.id)!} open={open} onClose={() => setOpen(false)} />}
  </>;
}

function ExcerptPanel({ selected, draft, open, onClose, ...props }: Props & { selected: Selection; draft: ExcerptDraft; open: boolean; onClose: () => void }) {
  const [mode, setMode] = useState<"word" | "sentence">(selected.word ? "word" : "sentence");
  const [query, setQuery] = useState(selected.word), [sentence, setSentence] = useState(selected.sentence);
  const [words, setWords] = useState<WordLookup | null>(null), [word, setWord] = useState<WordDetail | null>(null), [sense, setSense] = useState("");
  const [operation, setOperation] = useState<Operation | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [notes, setNotes] = useState(draft.notes), [answer, setAnswer] = useState(draft.answers[selected.sentence] || "");
  const [explanation, setExplanation] = useState<Explanation | null>(draft.explanations[selected.sentence] || null), [revealed, setRevealed] = useState(false);
  const alive = useRef(true), flight = useRef(false), pending = useRef<{ key: string; id: string } | null>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const base = `/notebooks/${props.notebookId}/cet6`, busy = operation !== null;
  const reviewUrl = `/?notebook=${encodeURIComponent(props.notebookId)}&cet6=vocabulary&cet6_start=review`;
  const card = word?.cards.find(c => c.sense_id === sense);
  const surfaceForm = words?.query || selected.word;
  const selectedMatch = words?.matches.find(m => m.entry_id === word?.entry.id);
  const surfacePresent = wordParts(sentence).some(t => normalizedForm(t) === normalizedForm(surfaceForm));
  const existing = card?.contexts.filter(c => c.text === sentence.trim() && c.exam_id === props.paperId && c.exam_kind === props.kind && c.exam_question === props.question && c.exam_version === props.version).at(-1);
  const noteKey = `${word?.entry.id}:${sense}:${sentence}`;
  const note = notes[noteKey] ?? existing?.note ?? "";
  const saved = !!card?.contexts.some(c => c.text === sentence.trim() && (c.note || "") === note.trim() && c.exam_id === props.paperId && c.exam_kind === props.kind && c.exam_question === props.question && c.exam_version === props.version && (c.surface_forms || [c.surface_form || ""]).some(f => normalizedForm(f) === normalizedForm(surfaceForm)));
  const changeNote = (value: string) => { const next = { ...notes, [noteKey]: value }; draft.notes = next; setNotes(next); setNotice(""); };
  const help = () => { if (props.duringAttempt) props.onHelp(); };
  const loadWord = async (id: string, match?: WordLookup["matches"][number]) => {
    const detail = await apiGet<WordDetail>(`${base}/words/${id}`);
    const preferred = props.preferredSenses?.[detail.entry.word];
    const formSense = detail.entry.senses.find(s => s.id === match?.suggested_sense_id)?.id;
    if (alive.current) { setWord(detail); setSense(previous => detail.cards.some(c => c.sense_id === previous) ? previous : preferred || formSense || detail.preferred_sense_id); }
  };
  const run = async (kind: Operation, task: () => Promise<void>) => {
    if (flight.current) return;
    flight.current = true; setOperation(kind); setError("");
    try { await task(); } catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setOperation(null); }
  };
  const lookup = () => run("lookup", async () => {
    help(); setWord(null); setWords(null); setNotice("");
    const result = await apiGet<WordLookup>(`${base}/word-lookup?${new URLSearchParams({ q: query.trim(), context: sentence })}`);
    if (!alive.current) return;
    setWords(result);
    if (result.auto_entry_id) await loadWord(result.auto_entry_id, result.matches.find(m => m.entry_id === result.auto_entry_id));
  });
  useEffect(() => {
    alive.current = true;
    if (selected.word) void lookup();
    return () => { alive.current = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const explain = () => run("explain", async () => {
    help(); setRevealed(false);
    const start = Math.max(0, selected.paragraph.indexOf(sentence) - 800);
    const result = await apiPost<Explanation>(`${base}/exams/${props.paperId}/${props.kind}/sentence`, {
      version: props.version, question: props.question, sentence, paragraph: selected.paragraph.slice(start, start + 4000),
    });
    draft.explanations[sentence] = result;
    if (alive.current) {
      setExplanation(result);
      requestAnimationFrame(() => { if (resultHeading.current?.isConnected) resultHeading.current.focus({ preventScroll: true }); });
    }
  });
  const collect = () => run("save", async () => {
    if (!word || !card || saved) return;
    const body = { action: "collect", revision: card.revision, sense_id: sense, version: word.version,
      context: sentence, context_note: note, surface_form: surfaceForm, exam_id: props.paperId, exam_kind: props.kind, exam_question: props.question, exam_version: props.version };
    const key = JSON.stringify(body);
    if (pending.current?.key !== key) pending.current = { key, id: readingRequestId() };
    const result = await apiPost<WordCard>(`${base}/words/${word.entry.id}`, { ...body, request_id: pending.current.id });
    if (alive.current) {
      setWord({ ...word, cards: word.cards.map(c => c.sense_id === sense ? result : c) });
      setNotice(result.queued_at ? "已加入今日待复习，原句和题号已保存。" : "原句和题号已保存，保留已有复习时间。");
      pending.current = null;
    }
  });
  const chooseSentence = (value: string) => { setSentence(value); setWords(previous => previous ? { ...previous, usage_hint: "" } : null); setExplanation(draft.explanations[value] || null); setNotice(""); setRevealed(false); setAnswer(draft.answers[value] || ""); };
  const options = [...new Set([selected.sentence, ...sentences(selected.paragraph)])].filter(s => s.length <= 1500);
  const search = <form onSubmit={e => { e.preventDefault(); void lookup(); }}><label>查找本句单词<input value={query} maxLength={100} disabled={busy} onChange={e => setQuery(e.target.value)} placeholder="可直接输入原文中的变形词" /></label><button disabled={busy || !query.trim()}>查找词义</button></form>;
  const candidates = words && <div className="exam-word-candidates" aria-label="可能对应的词条">{words.matches.map((m, i) => m.entry_id ? <button key={m.entry_id} disabled={busy} aria-pressed={word?.entry.id === m.entry_id} onClick={() => void run("lookup", () => loadWord(m.entry_id!, m))}><strong lang="en">{m.word}</strong><span>{m.in_study_list === false ? "词表外 · " : ""}{m.forms.join(" / ") || (m.match_kind === "spelling" ? "拼写变体" : "独立词条")} · {m.meaning}</span></button> : <div key={`dictionary-${i}`} className="exam-word-dictionary"><strong lang="en">{m.word}</strong><p>{m.meaning}</p><p className="exam-excerpt-hint">这个独立词义未纳入当前学习词表。<a href={words.dictionary_url} target="_blank" rel="noreferrer">核对词典 ↗</a></p></div>)}</div>;
  return <StudyDialog open={open} title={`词句学习 · 第 ${props.question} 题`} onClose={onClose} className="exam-learning-dialog" footer={<>
    <div role="status" className="exam-excerpt-save-status">{notice || (saved ? "这个义项与原句已保存，可继续阅读。" : "")}</div>
    <div className="exam-excerpt-actions">
      {mode === "word" && word && <button className="primary-action" disabled={busy || saved || !sense || !surfacePresent || sentence.length > 1500} onClick={() => void collect()}>{operation === "save" ? "正在保存…" : saved ? "已加入复习" : existing ? "保存笔记与原句" : "加入复习，保留原句"}</button>}
      <button type="button" onClick={onClose} className={saved || mode === "sentence" ? "primary-action" : "secondary-action"}>返回阅读</button>
      {saved && <a href={reviewUrl}>现在复习</a>}
    </div>
  </>}>
    <section className="exam-excerpt-panel" aria-label="词句学习">
      <div className="exam-excerpt-modes" role="group" aria-label="词句学习方式"><button aria-pressed={mode === "word"} onClick={() => setMode("word")}>单词词义</button><button aria-pressed={mode === "sentence"} onClick={() => setMode("sentence")}>读懂原句</button></div>
      <div role="status" className="exam-excerpt-progress">{operation ? { lookup: "正在查找词义…", save: "正在保存原句…", reload: "正在重新读取词卡…", explain: "正在拆解原句，请稍候。你可以先返回阅读。" }[operation] : ""}</div>
      {mode === "word" && <>
        {word ? <div className="exam-excerpt-word"><strong lang="en">{surfaceForm}</strong>
          {normalizedForm(surfaceForm) !== normalizedForm(word.entry.word) && <p className="exam-word-form">{selectedMatch?.match_kind === "spelling" ? "对应拼写" : "原形"} <b lang="en">{word.entry.word}</b> · {selectedMatch?.forms.join(" / ")}</p>}
          {word.entry.level === "reading" && <p className="exam-excerpt-hint">阅读补充词 · 六级学习词表外。可保存原句并复习，不计入六级背词进度。</p>}
          {words?.usage_hint && words.auto_entry_id === word.entry.id && <p className="exam-excerpt-hint">{words.usage_hint}</p>}
          <label>选择本句对应义项<select disabled={busy} value={sense} onChange={e => { setSense(e.target.value); setNotice(""); }}>{word.entry.senses.map(s => <option key={s.id} value={s.id}>{s.definition}</option>)}</select></label>
          {normalizedForm(surfaceForm) !== normalizedForm(word.entry.word) && <p className="exam-excerpt-hint">以下播放词条 <span lang="en">{word.entry.word}</span> 的发音；收藏会归入该词条并保留原文词形。</p>}
          <WordPronunciation word={word.entry.word} entryId={word.entry.id} /></div> : <><strong className="exam-excerpt-query" lang="en">{words?.query || selected.word}</strong>{search}</>}
        {words && !word && <>{words.status === "not_found" ? <p>暂未收录“{words.query}”或其词形。<a href={words.dictionary_url} target="_blank" rel="noreferrer">去词典查询 ↗</a>，也可用“读懂原句”查看语境解释。</p> : <><p>这个词形可能对应不同词义，请结合原句选择：</p>{candidates}</>}</>}
        {word && words && words.matches.length > 1 && <details className="exam-excerpt-details"><summary>其他可能词义与拼写</summary>{candidates}</details>}
        {word && !surfacePresent && <p className="exam-excerpt-hint">当前原句不含“{surfaceForm}”，请选择包含该词的原句后收藏。</p>}
        <p className="exam-excerpt-label">所在原句</p><blockquote lang="en">{sentence}</blockquote>
        {word && <>
          <details className="exam-excerpt-details"><summary>添加语境笔记（选填）</summary><label>我的语境理解（选填）<input value={note} maxLength={500} disabled={busy} onChange={e => changeNote(e.target.value)} placeholder="记下这个词在本句中的意思" /></label><p>点击保存后，笔记会随原句进入复习。</p></details>
          <details className="exam-excerpt-details"><summary>其他词形与词典来源</summary>{search}<p>请结合原句选择义项。<a href={word.entry.senses.find(s => s.id === sense)?.source_url || word.entry.dictionary_url} target="_blank" rel="noreferrer">核对词典来源 ↗</a></p></details>
        </>}
      </>}
      {mode === "sentence" && <>
        <label>选择原句<select value={sentence} disabled={busy} onChange={e => chooseSentence(e.target.value)}>{options.map((s, i) => <option key={i} value={s}>第 {i + 1} 句 · {s.slice(0, 85)}{s.length > 85 ? "…" : ""}</option>)}</select></label>
        <blockquote lang="en">{sentence}</blockquote>
        <button className="primary-action" disabled={busy || sentence.length < 10 || sentence.length > 1500 || !selected.paragraph.includes(sentence)} onClick={() => void explain()}>{operation === "explain" ? "正在拆句…" : explanation ? "重新拆解这句话" : "拆解这句话"}</button>
        {!explanation && <p className="exam-excerpt-hint">先找主干，再看从句和整句意思，最后用自己的话检查理解。</p>}
        {explanation && <div className="exam-sentence-result"><p className="exam-excerpt-hint">{explanation.note}</p><h3 ref={resultHeading} tabIndex={-1}>先看主干</h3><p lang="en">{explanation.content.main_clause}</p><details className="exam-excerpt-details"><summary>逐段看句子结构 · {explanation.content.clauses.length} 处</summary>{explanation.content.clauses.map((c, i) => <div key={i}><blockquote lang="en">{c.quote}</blockquote><p><b>{c.role}：</b>{c.explanation}</p></div>)}</details><p><b>逻辑关系：</b>{explanation.content.connection}</p><details className="exam-excerpt-details"><summary>查看整句意思</summary><p>{explanation.content.translation}</p></details><label>理解自查：{explanation.content.check_question}<textarea maxLength={1000} rows={2} value={answer} onChange={e => { setAnswer(e.target.value); draft.answers[sentence] = e.target.value; }} placeholder="先用自己的话回答，再看参考" /></label><button disabled={!answer.trim()} onClick={() => setRevealed(true)}>对照参考答案</button>{revealed && <p className="exam-check-answer">{explanation.content.check_answer}</p>}</div>}
      </>}
      {error && <div role="alert" className="exam-excerpt-error"><p>{error} 输入仍保留，可重试。</p>{word && <button disabled={busy} onClick={() => void run("reload", async () => { await loadWord(word.entry.id); pending.current = null; })}>重新读取词卡，保留原句与笔记</button>}</div>}
    </section>
  </StudyDialog>;
}
