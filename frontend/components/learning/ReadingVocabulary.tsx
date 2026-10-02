"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { readingError, readingRequestId } from "@/lib/reading";
import type { WordCatalogue, WordDetail, WordCard } from "@/lib/cet6";

export default function ReadingVocabulary({ notebookId, readingId, questionId, questionNumber, paragraphs, duringAttempt, onHelp }: {
  notebookId: string; readingId: string; questionId: string; questionNumber: number; paragraphs: string[]; duringAttempt: boolean; onHelp: () => void;
}) {
  const [query, setQuery] = useState(""), [results, setResults] = useState<WordCatalogue | null>(null), [selected, setSelected] = useState<WordDetail | null>(null);
  const [sense, setSense] = useState(""), [context, setContext] = useState((paragraphs[0] || "").slice(0, 1500)), [note, setNote] = useState(""), [paragraphIndex, setParagraphIndex] = useState(0);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const alive = useRef(true), flight = useRef(false), ticket = useRef(0), receipt = useRef<{ key: string; id: string } | null>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; ticket.current++; }; }, []);
  const lookup = async () => {
    if (!query.trim() || flight.current) return;
    if (duringAttempt) onHelp();
    const id = ++ticket.current; flight.current = true; setBusy(true); setError(""); setSelected(null); setNotice("");
    try { const r = await apiGet<WordCatalogue>(`/notebooks/${notebookId}/cet6/words?q=${encodeURIComponent(query)}&limit=6`); if (alive.current && ticket.current === id) setResults(r); }
    catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  const pick = async (id: string) => {
    if (flight.current) return; flight.current = true; setBusy(true); setError("");
    try { const r = await apiGet<WordDetail>(`/notebooks/${notebookId}/cet6/words/${id}`); if (alive.current) { setSelected(r); setSense(r.entry.senses[0]?.id || ""); receipt.current = null; } }
    catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  const save = async () => {
    const card = selected?.cards.find(c => c.sense_id === sense);
    if (!selected || !card || flight.current) return;
    flight.current = true; setBusy(true); setError("");
    const body = { action: "collect", revision: card.revision, sense_id: sense, version: selected.version, context, context_note: note, reading_id: readingId, question_id: questionId };
    const key = JSON.stringify(body); if (receipt.current?.key !== key) receipt.current = { key, id: readingRequestId() };
    try { const result = await apiPost<WordCard>(`/notebooks/${notebookId}/cet6/words/${selected.entry.id}`, { ...body, request_id: receipt.current.id }); if (alive.current) { setSelected({ ...selected, cards: selected.cards.map(c => c.sense_id === sense ? result : c) }); setNotice("已保存到我的生词，词义、原句和这篇阅读一起保留。"); receipt.current = null; } }
    catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  return <details className="reading-vocabulary"><summary>保存题中生词</summary><p>关联当前第 {questionNumber} 题。{duringAttempt ? "作答中查词会记录为借助提示；先尝试独立作答也可以。" : "把不熟悉的义项连同原句保留下来，之后在“单词 → 我的生词”复习。"}</p>
    <form onSubmit={e => { e.preventDefault(); void lookup(); }}><label>查找词库<input maxLength={100} value={query} onChange={e => setQuery(e.target.value)} placeholder="输入单词，如 evidence" /></label><button className="secondary-action" disabled={busy || !query.trim()} type="submit">查找单词</button></form>
    {results && !selected && <div>{!results.items.length && <p>本词表没有找到。可尝试原形，或先在本题笔记里记录原词，不猜测对应词义。</p>}{results.items.map(w => <button key={w.id} className="reading-list-item" disabled={busy} onClick={() => void pick(w.id)}><span><strong>{w.word}</strong><small>{w.meaning}</small></span></button>)}</div>}
    {selected && <div><strong lang="en">{selected.entry.word}</strong><label>选择本句对应义项<select disabled={busy} value={sense} onChange={e => setSense(e.target.value)}>{selected.entry.senses.map(s => <option key={s.id} value={s.id}>{s.definition}</option>)}</select></label><label>原文段落<select disabled={busy} value={paragraphIndex} onChange={e => { const at = Number(e.target.value); setParagraphIndex(at); setContext(paragraphs[at].slice(0, 1500)); }}>{paragraphs.map((p, i) => <option key={i} value={i}>第 {i + 1} 段 · {p.slice(0, 55)}…</option>)}</select></label><label>保留原句（可从本段截取，保持原文不变）<textarea rows={3} maxLength={1500} value={context} onChange={e => setContext(e.target.value)} /></label><label>我理解的语境义（选填）<input maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></label><p>释义：ECDICT 社区词典；请按原句选择，词典释义可能需要进一步核验。</p><button className="primary-action" disabled={busy || !sense || !context.trim()} onClick={() => void save()}>连同原句保存生词</button>{notice && <a href={`/?notebook=${encodeURIComponent(notebookId)}&cet6=vocabulary&cet6_word=${selected.entry.id}`}>去词卡复习 ↗</a>}</div>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="reading-error">{error} 你的输入仍保留；可重新查找后再保存。</p>}
  </details>;
}
