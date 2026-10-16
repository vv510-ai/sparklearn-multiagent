"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, USER_ID } from "@/lib/api";
import { formatReviewTime, recallHelp, takeRecallLyricsHelp } from "@/lib/review";
import { Notice } from "@/components/ui";
import MathText from "@/components/chat/MathText";

type Rating = "again" | "hard" | "good" | "easy";
interface Card {
  key: string; front: string; back?: string; hint: string; mode: "self" | "cloze";
  registered: boolean; revision: number; due_at?: string; attempts: number;
}
interface Deck { resource_id: string; title: string; kind: string; items: Card[]; total: number; registered: number }
interface Result {
  card_key: string; revision: number; correct: boolean; answer: string; due_at: string;
  attempts: number; effective_rating: Rating; scheduling_applied: boolean; scheduling_reason: string;
}
const ratings: { value: Rating; label: string }[] = [
  { value: "again", label: "没想起" }, { value: "hard", label: "费力想起" },
  { value: "good", label: "想起来了" }, { value: "easy", label: "轻松想起" },
];

export default function RecallPractice({ resourceId, dueOnly = false, onRecorded }: {
  resourceId: string; dueOnly?: boolean; onRecorded?: () => void;
}) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [hintShown, setHintShown] = useState(false);
  const [usedHelp, setUsedHelp] = useState(false);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const root = `/eval/recall/${encodeURIComponent(resourceId)}`;
  const load = useCallback(async () => {
    setError("");
    try {
      const loaded = await apiGet<Deck>(`${root}?user_id=${USER_ID}&due_only=${dueOnly}`);
      if (takeRecallLyricsHelp(resourceId)) loaded.items.forEach(item => recallHelp(resourceId, item.key, item.revision, true));
      setDeck(loaded);
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "复习记录暂时无法读取"); }
  }, [root, dueOnly, resourceId]);
  useEffect(() => { void load(); }, [load]);
  const resetCard = () => { setFlipped(false); setHintShown(false); setUsedHelp(false); setAnswer(""); setResult(null); setError(""); pending.current = null; };
  const card = deck?.items[index];
  useEffect(() => {
    setHintShown(card ? recallHelp(resourceId, card.key, card.revision) : false);
  }, [resourceId, card?.key, card?.revision]);

  async function enroll() {
    setBusy(true); setError("");
    try {
      setDeck(await apiPost<Deck>(`${root}/enroll`, { user_id: USER_ID }));
      setIndex(0); resetCard(); onRecorded?.();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "加入复习失败，请重试"); }
    finally { setBusy(false); }
  }
  async function submit(rating: Rating) {
    if (!card || busy) return;
    setBusy(true); setError("");
    const body = { user_id: USER_ID, card_key: card.key, revision: card.revision, rating,
      answer, used_help: usedHelp || hintShown || recallHelp(resourceId, card.key, card.revision) };
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    try {
      const saved = await apiPost<Result>(root, { ...body, request_id: pending.current.id });
      recallHelp(resourceId, card.key, card.revision, false);
      setResult(saved);
      setDeck(current => current ? { ...current, items: current.items.map(item => item.key === saved.card_key
        ? { ...item, revision: saved.revision, due_at: saved.due_at, attempts: saved.attempts } : item) } : current);
      pending.current = null;
      onRecorded?.();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "保存失败，请重试；已提交的记录不会重复计算"); }
    finally { setBusy(false); }
  }
  function move(delta: number) {
    if (!deck) return;
    setIndex(current => (current + delta + deck.items.length) % deck.items.length);
    resetCard();
  }

  if (!deck) return <div role="status" className="space-y-2 text-sm text-slate-600">{error || "正在读取复习记录…"}{error && <button className="secondary-action" onClick={() => void load()}>重新读取</button>}</div>;
  if (!card) return <Notice tone="success" title={dueOnly ? "这组到期复习已完成" : "暂无可复习内容"} desc="复习记录会保留，之后可在今日复习查看安排。" />;
  return <section className="space-y-3" aria-label={deck.kind === "song" ? "口诀复习" : "复习闪卡"}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <strong className="text-sm text-slate-900">{deck.kind === "song" ? "口诀回忆" : "复习闪卡"} · {index + 1}/{deck.items.length}</strong>
      <span className="text-xs text-slate-600">{card.attempts ? `已记录 ${card.attempts} 次 · 下次 ${formatReviewTime(card.due_at)}` : card.registered ? "待首次回忆" : "还未加入复习"}</span>
    </div>
    {!card.registered && <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-fuchsia-50 p-3 text-xs text-slate-700">
      <span>加入后会保存回忆记录，并安排下次复习。</span>
      <button className="primary-action" disabled={busy} onClick={() => void enroll()}>加入复习（{deck.total} 张）</button>
    </div>}
    <div className={`min-h-48 rounded-2xl border p-5 ${flipped || result ? "border-emerald-200 bg-emerald-50" : "border-fuchsia-200 bg-fuchsia-50/40"}`}>
      <div className="mb-4 text-xs font-semibold text-slate-500">{flipped && card.mode === "self" ? "对照答案" : "先独立回忆"}</div>
      <div className="whitespace-pre-wrap text-base leading-8 text-slate-950"><MathText text={flipped && card.mode === "self" ? card.back || "" : card.front} /></div>
      {card.mode === "cloze" && <input aria-label="填写口诀关键词" value={answer} disabled={busy || !!result}
        onChange={event => setAnswer(event.target.value)} placeholder="填写缺少的关键词" className="mt-4 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" />}
      {card.mode === "self" && <button className="secondary-action mt-4" disabled={busy || !!result} onClick={() => setFlipped(value => !value)}>{flipped ? "返回问题" : "翻面查看答案"}</button>}
      {!!card.hint && !flipped && <div className="mt-3 text-xs text-slate-600">{hintShown ? `提示：${card.hint}` : <button className="secondary-action" disabled={busy || !!result} onClick={() => { recallHelp(resourceId, card.key, card.revision, true); setHintShown(true); }}>查看提示</button>}</div>}
    </div>
    {card.registered && !result && <>
      <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={usedHelp || hintShown} disabled={busy || hintShown} onChange={event => { setUsedHelp(event.target.checked); recallHelp(resourceId, card.key, card.revision, event.target.checked); }} />借助了提示、歌词或资料</label>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="本次回忆情况">{ratings.map(rating => <button key={rating.value} className="secondary-action justify-center" disabled={busy || (card.mode === "self" ? !flipped : rating.value !== "again" && !answer.trim())}
        onClick={() => void submit(rating.value)}>{rating.label}</button>)}</div>
      <p className="text-xs leading-5 text-slate-500">{card.mode === "self" ? "先回忆再翻面，对照答案自评。" : "填好后选择回忆情况，提交时核对关键词。"}看过提示会安排重新学习；提前练习会保留原复习时间。</p>
    </>}
    {result && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm leading-6">
      <strong>{card.mode === "cloze" ? result.correct ? "关键词正确，已保存" : "关键词还需巩固，已保存" : "回忆情况已保存"}</strong>
      {card.mode === "cloze" && <p>参考关键词：{result.answer}</p>}
      <p>{result.scheduling_reason}。下次复习：{formatReviewTime(result.due_at)}</p>
      {dueOnly && index === deck.items.length - 1 && <p>本组已记录完成，可返回今日复习查看其他内容。</p>}
    </div>}
    {error && <div role="alert" className="text-sm text-red-700">{error}<button className="secondary-action ml-2" disabled={busy} onClick={() => { resetCard(); void load(); }}>重新读取记录</button></div>}
    {deck.items.length > 1 && <div className="flex justify-between gap-2"><button className="secondary-action" disabled={busy} onClick={() => move(-1)}>上一张</button><button className="secondary-action" disabled={busy} onClick={() => move(1)}>下一张</button></div>}
  </section>;
}
