"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { readingError, readingRequestId } from "@/lib/reading";
import type { WordCard, WordCatalogue, WordDetail } from "@/lib/cet6";
import WordPronunciation from "./WordPronunciation";
import "./exam-reading-tools.css";

type Selection = { word: string; sentence: string; paragraph: string };
type Explanation = { note: string; content: { main_clause: string; clauses: { quote: string; role: string; explanation: string }[]; translation: string; connection: string; check_question: string; check_answer: string } };
type Props = { notebookId: string; paperId: string; kind: string; question: number; version: string; paragraphs: string[]; duringAttempt: boolean; onHelp: () => void };
const sentences = (p: string) => p.match(/[^.!?]+(?:[.!?]+[”"']?|$)/g)?.map(s => s.trim()).filter(Boolean) || [p];

export default function ExamReadingTools(props: Props) {
  const [selected, setSelected] = useState<Selection | null>(null), [sequence, setSequence] = useState(0);
  const pick = (s: Selection) => { setSelected(s); setSequence(n => n + 1); };
  return <>
    <p className="exam-muted">点单词查义并保存原句；用段落下的“拆解句子”选择长难句。{props.duringAttempt && "使用查词或拆句会记录为借助帮助。"}</p>
    <div lang="en" className="exam-source-text">
      {props.paragraphs.map((paragraph, p) => <div key={p}>
        <p>{paragraph.split(/([A-Za-z]+(?:['’\-][A-Za-z]+)*)/g).map((part, i, parts) => /^[A-Za-z]/.test(part) ? <button className="exam-word" key={i} aria-label={`查词 ${part}`} onClick={() => {
          const offset = parts.slice(0, i).join("").length;
          const sentence = sentences(paragraph).find(s => { const start = paragraph.indexOf(s); return start <= offset && offset < start + s.length; }) || paragraph;
          pick({ word: part, sentence: sentence.slice(0, 1500), paragraph });
        }}>{part}</button> : part)}</p>
        <button className="exam-sentence-pick" lang="zh-CN" onClick={() => {
          const selection = window.getSelection()?.toString().trim() || "";
          pick({ word: "", sentence: selection.length >= 10 && selection.length <= 1500 && paragraph.includes(selection) ? selection : sentences(paragraph)[0], paragraph });
        }}>拆解第 {p + 1} 段句子</button>
      </div>)}
    </div>
    {selected && <ExcerptPanel key={sequence} {...props} selected={selected} onClose={() => setSelected(null)} />}
  </>;
}

function ExcerptPanel({ selected, onClose, ...props }: Props & { selected: Selection; onClose: () => void }) {
  const [query, setQuery] = useState(selected.word), [sentence, setSentence] = useState(selected.sentence);
  const [words, setWords] = useState<WordCatalogue | null>(null), [word, setWord] = useState<WordDetail | null>(null), [sense, setSense] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [note, setNote] = useState("");
  const [explanation, setExplanation] = useState<Explanation | null>(null), [answer, setAnswer] = useState(""), [revealed, setRevealed] = useState(false);
  const alive = useRef(true), flight = useRef(false), heading = useRef<HTMLHeadingElement>(null), pending = useRef<{ key: string; id: string } | null>(null);
  const base = `/notebooks/${props.notebookId}/cet6`;
  const help = () => { if (props.duringAttempt) props.onHelp(); };
  const loadWord = async (id: string) => {
    const detail = await apiGet<WordDetail>(`${base}/words/${id}`);
    if (alive.current) { setWord(detail); setSense(previous => detail.cards.some(c => c.sense_id === previous) ? previous : detail.preferred_sense_id); }
  };
  const run = async (task: () => Promise<void>) => {
    if (flight.current) return;
    flight.current = true; setBusy(true); setError("");
    try { await task(); } catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  const lookup = () => run(async () => {
    help(); setWord(null); setNotice("");
    const result = await apiGet<WordCatalogue>(`${base}/words?q=${encodeURIComponent(query.trim())}&limit=6`);
    if (!alive.current) return;
    setWords(result);
    const exact = result.items.find(w => w.word.toLowerCase() === query.toLowerCase() || w.variants.some(v => v.toLowerCase() === query.toLowerCase()));
    if (exact) await loadWord(exact.id);
  });
  useEffect(() => {
    alive.current = true; heading.current?.focus(); heading.current?.scrollIntoView({ block: "nearest" });
    if (selected.word) void lookup();
    return () => { alive.current = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const explain = () => run(async () => {
    help(); setExplanation(null); setRevealed(false);
    const start = Math.max(0, selected.paragraph.indexOf(sentence) - 800);
    const result = await apiPost<Explanation>(`${base}/exams/${props.paperId}/${props.kind}/sentence`, {
      version: props.version, question: props.question, sentence, paragraph: selected.paragraph.slice(start, start + 4000),
    });
    if (alive.current) setExplanation(result);
  });
  const collect = () => run(async () => {
    const card = word?.cards.find(c => c.sense_id === sense);
    if (!word || !card) return;
    const body = { action: "collect", revision: card.revision, sense_id: sense, version: word.version,
      context: sentence, context_note: note, exam_id: props.paperId, exam_kind: props.kind, exam_question: props.question, exam_version: props.version };
    const key = JSON.stringify(body);
    if (pending.current?.key !== key) pending.current = { key, id: readingRequestId() };
    const saved = await apiPost<WordCard>(`${base}/words/${word.entry.id}`, { ...body, request_id: pending.current.id });
    if (alive.current) {
      setWord({ ...word, cards: word.cards.map(c => c.sense_id === sense ? saved : c) });
      setNotice(saved.queued_at ? "已加入今日待复习，原句和题号已保存。" : "原句和题号已保存，保留这个义项已有的复习时间。");
      pending.current = null;
    }
  });
  const options = [...new Set([selected.sentence, ...sentences(selected.paragraph)])].filter(s => s.length <= 1500);
  return <section className="exam-excerpt-panel" aria-label="词句学习">
    <div className="exam-reader-toolbar"><h3 ref={heading} tabIndex={-1}>词句学习 · 第 {props.question} 题</h3><button onClick={onClose}>收起词句学习</button></div>
    <label>选择原句<select value={sentence} disabled={busy} onChange={e => { setSentence(e.target.value); setExplanation(null); setNotice(""); setRevealed(false); setAnswer(""); }}>{options.map((s, i) => <option key={i} value={s}>{s.slice(0, 100)}{s.length > 100 ? "…" : ""}</option>)}</select></label>
    <blockquote lang="en">{sentence}</blockquote>
    <form onSubmit={e => { e.preventDefault(); void lookup(); }}><label>查找本句单词<input value={query} maxLength={100} disabled={busy} onChange={e => setQuery(e.target.value)} placeholder="未找到时可尝试单词原形" /></label><button disabled={busy || !query.trim()}>查找词义</button></form>
    {words && !word && <div>{!words.items.length && <p>词库暂未收录此形式，可尝试原形；不自动猜测词义。</p>}{words.items.map(w => <button key={w.id} disabled={busy} onClick={() => void run(() => loadWord(w.id))}>{w.word} · {w.meaning}</button>)}</div>}
    {word && <div className="exam-excerpt-word"><strong lang="en">{word.entry.word}</strong><WordPronunciation word={word.entry.word} entryId={word.entry.id} /><label>选择本句对应义项<select disabled={busy} value={sense} onChange={e => { setSense(e.target.value); setNotice(""); }}>{word.entry.senses.map(s => <option key={s.id} value={s.id}>{s.definition}</option>)}</select></label><p className="exam-muted">请按原句选择义项。<a href={word.entry.senses.find(s => s.id === sense)?.source_url || word.entry.dictionary_url} target="_blank" rel="noreferrer">核对词典来源 ↗</a></p><label>我的语境理解（选填）<input value={note} maxLength={500} disabled={busy} onChange={e => setNote(e.target.value)} /></label><button className="primary-action" disabled={busy || !sense || !sentence.trim() || sentence.length > 1500} onClick={() => void collect()}>加入复习，保留原句</button></div>}
    {notice && <p role="status">{notice} <a href={`/?notebook=${encodeURIComponent(props.notebookId)}&cet6=vocabulary`}>去背单词查看待复习</a></p>}
    <button disabled={busy || sentence.length < 10 || sentence.length > 1500 || !selected.paragraph.includes(sentence)} onClick={() => void explain()}>{explanation ? "重新拆解这句话" : "拆解这句话"}</button>
    {busy && <p role="status">正在处理，请稍候…</p>}
    {error && <div role="alert" className="exam-error"><p>{error} 输入仍保留，可重试上面的操作。</p>{word && <button disabled={busy} onClick={() => void run(async () => { await loadWord(word.entry.id); pending.current = null; })}>重新读取词卡，保留原句与笔记</button>}</div>}
    {explanation && <div className="exam-sentence-result"><p className="exam-muted">{explanation.note}</p><h4>先看主干</h4><p lang="en">{explanation.content.main_clause}</p>{explanation.content.clauses.map((c, i) => <div key={i}><blockquote lang="en">{c.quote}</blockquote><p><b>{c.role}：</b>{c.explanation}</p></div>)}<p><b>逻辑关系：</b>{explanation.content.connection}</p><details><summary>查看整句意思</summary><p>{explanation.content.translation}</p></details><label>理解自查：{explanation.content.check_question}<textarea maxLength={1000} rows={2} value={answer} onChange={e => setAnswer(e.target.value)} placeholder="先用自己的话回答，再看参考" /></label><button disabled={!answer.trim()} onClick={() => setRevealed(true)}>对照参考答案</button>{revealed && <p>{explanation.content.check_answer}</p>}</div>}
  </section>;
}
