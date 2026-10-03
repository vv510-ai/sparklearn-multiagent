"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { readingDate, readingError, readingRequestId } from "@/lib/reading";
import type { WordCard, WordDetail } from "@/lib/cet6";
import WordLesson from "./WordLesson";
import WordPronunciation from "./WordPronunciation";
import "./word-round.css";

export type RoundItem = { entry_id: string; sense_id: string; mode: "meaning" | "spelling"; attempts: number; done: boolean };
export type RecallRound = { id: string; kind: "new" | "review"; items: RoundItem[]; completed: number; total: number; finished: boolean };

export default function WordRound({ notebookId, roundId, initial, onExit, onAnother, onChanged }: {
  notebookId: string; roundId: string; initial: RecallRound | null; onExit: () => void; onAnother: (kind: "new" | "review") => void; onChanged: () => void;
}) {
  const [round, setRound] = useState(initial), [error, setError] = useState("");
  const alive = useRef(true);
  const refresh = async () => {
    const next = await apiGet<RecallRound>(`/notebooks/${notebookId}/cet6/word-rounds/${encodeURIComponent(roundId)}`);
    if (alive.current) { setRound(next); setError(""); onChanged(); }
  };
  useEffect(() => { alive.current = true; void refresh().catch(e => { if (alive.current) setError(readingError(e)); }); return () => { alive.current = false; }; }, [notebookId, roundId]); // eslint-disable-line react-hooks/exhaustive-deps
  const item = round?.items.find(i => !i.done);
  return <section className="word-round" aria-label="有限词卡练习">
    <button className="cet6-back" onClick={onExit}><ArrowLeft size={17} />暂停，返回背词</button>
    {!round ? <p role="status">正在恢复本轮词卡…</p> : <>
      <div className="word-round-heading"><div><p className="cet6-eyebrow">{round.kind === "new" ? "本轮新词" : "本轮到期复习"}</p><h2>{round.finished ? "这一轮完成了" : round.kind === "new" ? "一次学好几个词" : "看看还记得多少"}</h2></div><strong aria-live="polite">{round.completed} / {round.total}</strong></div>
      <progress aria-label="本轮词卡进度" value={round.completed} max={Math.max(1, round.total)} />
      {round.finished ? <div className="word-round-complete" role="status"><CheckCircle2 size={42} /><h3>已完成 {round.total} {round.kind === "new" ? "个新词" : "张复习卡"}</h3><p>记录已保存。这一轮到这里结束。</p><p>需要再练的词按回忆结果另行安排，可从“到期复习”进入。</p><div className="cet6-actions"><button className="primary-action" onClick={onExit}>完成，回到背词</button><button className="secondary-action" onClick={() => onAnother(round.kind)}>{round.kind === "new" ? "再学一轮新词" : "再看一轮到期复习"}</button></div></div> : item && <RecallCard key={`${round.id}:${item.entry_id}:${item.sense_id}:${item.mode}`} notebookId={notebookId} item={item} onAdvance={refresh} />}
    </>}
    {error && <div className="cet6-error" role="alert">{error}<button onClick={() => void refresh().catch(e => setError(readingError(e)))}>重新读取本轮</button></div>}
  </section>;
}

function RecallCard({ notebookId, item, onAdvance }: { notebookId: string; item: RoundItem; onAdvance: () => Promise<void> }) {
  const [data, setData] = useState<WordDetail | null>(null), [busy, setBusy] = useState(true), [error, setError] = useState("");
  const [answer, setAnswer] = useState(""), [help, setHelp] = useState(false), [lesson, setLesson] = useState(false), [retry, setRetry] = useState(0), [swipe, setSwipe] = useState(0);
  const alive = useRef(true), flight = useRef(false), startId = useRef(readingRequestId());
  const pending = useRef<{ key: string; id: string } | null>(null), pointer = useRef<{ x: number; y: number } | null>(null);
  const url = `/notebooks/${notebookId}/cet6/words/${item.entry_id}`;
  useEffect(() => {
    let current = true; alive.current = true; setBusy(true); setError("");
    void (async () => {
      let next = await apiGet<WordDetail>(url);
      if (!current) return;
      const card = next.cards.find(c => c.sense_id === item.sense_id)!;
      if ((card.tracks[item.mode]?.attempts || 0) > item.attempts) { await onAdvance(); return; }
      if (!card.active) {
        const started = await apiPost<WordCard>(url, { request_id: startId.current, revision: card.revision, version: next.version, sense_id: item.sense_id, action: "start", mode: item.mode, used_help: false });
        next = { ...next, cards: next.cards.map(c => c.sense_id === item.sense_id ? started : c) };
      } else if (card.active.mode !== item.mode) throw new Error("这个词的另一种回忆尚未结束，请先完成已开启的词卡。");
      if (current) setData(next);
    })().catch(e => { if (current) setError(readingError(e)); }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; alive.current = false; window.speechSynthesis?.cancel(); };
  }, [url, item.sense_id, item.mode, item.attempts, retry]); // eslint-disable-line react-hooks/exhaustive-deps
  const card = data?.cards.find(c => c.sense_id === item.sense_id), active = card?.active, sense = data?.entry.senses.find(s => s.id === item.sense_id);
  const act = async (action: "reveal" | "rate", rating?: string) => {
    if (!data || !card || flight.current) return;
    const body = { revision: card.revision, version: data.version, sense_id: item.sense_id, mode: item.mode, action, answer, used_help: help, ...(rating ? { rating } : {}) };
    const key = JSON.stringify(body); if (pending.current?.key !== key) pending.current = { key, id: readingRequestId() };
    flight.current = true; setBusy(true); setError("");
    try {
      const next = await apiPost<WordCard>(url, { ...body, request_id: pending.current.id });
      if (!alive.current) return;
      pending.current = null; setData({ ...data, cards: data.cards.map(c => c.sense_id === item.sense_id ? next : c) });
      if (action === "rate") await onAdvance();
    } catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  const rate = (rating: string) => { if (active?.revealed && (rating === "again" || item.mode !== "spelling" || active.correct)) void act("rate", rating); };
  return <>
    <div className="word-flashcard" tabIndex={0} role="group" aria-label="单词闪卡" data-revealed={!!active?.revealed} aria-busy={busy}
      onKeyDown={e => { if (e.target !== e.currentTarget || busy) return; if ([" ", "Enter"].includes(e.key) && active && !active.revealed) { e.preventDefault(); void act("reveal"); } if (active?.revealed && ["ArrowLeft", "ArrowRight"].includes(e.key)) { e.preventDefault(); rate(e.key === "ArrowLeft" ? "again" : "good"); } }}
      onPointerDown={e => { if ((e.target as HTMLElement).closest("button,input,select,a,summary") || !active?.revealed || busy) return; pointer.current = { x: e.clientX, y: e.clientY }; }}
      onPointerMove={e => { if (pointer.current && Math.abs(e.clientY - pointer.current.y) < 50) setSwipe(Math.max(-80, Math.min(80, e.clientX - pointer.current.x))); }}
      onPointerCancel={() => { pointer.current = null; setSwipe(0); }}
      onPointerUp={e => { const p = pointer.current; pointer.current = null; setSwipe(0); if (!p || busy || Math.abs(e.clientY - p.y) > 60) return; if (e.clientX - p.x > 65) rate("good"); else if (e.clientX - p.x < -65) rate("again"); }}>
      {!data ? <p role="status">正在准备这一张…</p> : <>
        <div className="word-flash-face" style={{ transform: `translateX(${swipe}px)` }}>
          <p className="word-card-prompt">{item.mode === "meaning" ? active?.revealed ? "对照释义，回想翻面前的表现" : "先在心里想一想：这个词是什么意思？" : "根据词义，写出英文单词"}</p>
          <h3 lang={item.mode === "spelling" && !active?.revealed ? "zh-CN" : "en"}>{item.mode === "spelling" && !active?.revealed ? sense?.definition : data.entry.word}</h3>
          {(item.mode === "meaning" || active?.revealed) && <>{data.entry.phonetic && <p className="word-card-phonetic">/{data.entry.phonetic}/</p>}<WordPronunciation word={data.entry.word} /></>}
          {active?.revealed && <div className="word-card-definition"><p>{sense?.definition}</p><small>{sense?.source_label || "ECDICT 社区词典释义"} · <a href={sense?.source_url || data.entry.dictionary_url} target="_blank" rel="noreferrer">核对来源 ↗</a></small>{item.mode === "spelling" && <p>你的拼写：{active.answer || "未填写"} · {active.correct ? "拼写一致" : "还需要再练"}</p>}</div>}
        </div>
        {active?.used_help && <p className="cet6-muted">{active.help_reason || "本次借助了提示，按重新学习安排。"}</p>}
        {active && !active.revealed && <div className="word-flip-actions">{item.mode === "spelling" && <label className="cet6-field">我的拼写<input value={answer} autoComplete="off" spellCheck={false} maxLength={500} onChange={e => setAnswer(e.target.value)} /></label>}<label className="cet6-check"><input type="checkbox" checked={help} onChange={e => setHelp(e.target.checked)} />这次看过提示</label><button className="primary-action" disabled={busy} onClick={() => void act("reveal")}>翻面看释义</button><p>可以口头回忆，无需抄写笔记。翻面后再记录回忆结果。</p></div>}
        {active?.revealed && <><p className="word-swipe-hint">左滑：忘记了 · 右滑：想起来了 · 也可使用下方按钮{item.mode === "spelling" && !active.correct ? "（拼写不一致时仅可选忘记了）" : ""}</p><div className="word-rating-grid">{([["again", "忘记了"], ["hard", "吃力想起"], ["good", "想起来了"], ["easy", "很轻松"]] as const).map(([rating, label]) => <button key={rating} disabled={busy || (rating !== "again" && item.mode === "spelling" && !active.correct)} onClick={() => rate(rating)}><strong>{label}</strong>{card?.rating_options?.[rating] && <small>{readingDate(card.rating_options[rating])}</small>}</button>)}</div><p className="cet6-muted">按翻面前的表现选择；下方时间是预计的下次复习时间。保存后进入下一张。</p></>}
        {!active && card?.last && <button className="primary-action" disabled={busy} onClick={() => void onAdvance().catch(e => setError(readingError(e)))}>记录已保存，继续本轮</button>}
      </>}
    </div>
    {data && active?.revealed && <div className="word-round-lesson"><button className="secondary-action" aria-expanded={lesson} onClick={() => setLesson(v => !v)}>{lesson ? "收起用法精讲" : "想理解得更深：看用法与例句"}</button>{lesson && <WordLesson notebookId={notebookId} wordId={item.entry_id} senseId={item.sense_id} />}</div>}
    {error && <div className="cet6-error" role="alert"><p>{error}</p><button disabled={busy} onClick={() => setRetry(n => n + 1)}>重新读取，保留本轮</button></div>}
  </>;
}
