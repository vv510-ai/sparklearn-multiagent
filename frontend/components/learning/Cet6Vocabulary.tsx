"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Search, Volume2 } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { readingDate, readingError, readingRequestId } from "@/lib/reading";
import { cet6Route, wordOrders, type WordOrder, type WordCatalogue, type WordDetail, type WordCard, type WordPlan } from "@/lib/cet6";
import WordLesson from "./WordLesson";
import WordRound, { type RecallRound } from "./WordRound";
import WordPronunciation from "./WordPronunciation";

export function speakEnglish(text: string, onError: (message: string) => void, onEnd?: () => void) {
  if (!("speechSynthesis" in window)) { onError("当前浏览器不支持朗读，请使用有音频的资料或换支持朗读的浏览器。"); return false; }
  const voice = window.speechSynthesis.getVoices().find(v => /^en(-|_)/i.test(v.lang));
  if (!voice) { onError("当前设备尚未提供英语语音。请安装英语语音或使用资料中心的原站音频。"); return false; }
  window.speechSynthesis.cancel();
  const speech = new SpeechSynthesisUtterance(text); speech.lang = voice.lang; speech.voice = voice; speech.rate = .9;
  speech.onerror = e => { if (e.error !== "canceled" && e.error !== "interrupted") onError("这次朗读未成功，请重试或使用原站音频。"); onEnd?.(); };
  speech.onend = () => onEnd?.(); window.speechSynthesis.speak(speech); return true;
}

export default function Cet6Vocabulary({ notebookId, onChat, initialWord, onChanged, onFocus }: {
  notebookId: string; onChat: (prompt: string) => void; initialWord?: string; onChanged: () => void; onFocus: (active: boolean) => void;
}) {
  const [view, setView] = useState("all"), [query, setQuery] = useState(""), [group, setGroup] = useState("all"), [offset, setOffset] = useState(0);
  const [order, setOrder] = useState<WordOrder | "">(""), [family, setFamily] = useState<{id:string;label:string} | null>(null);
  const [data, setData] = useState<WordCatalogue | null>(null), [word, setWord] = useState(initialWord || "");
  const [review, setReview] = useState(() => typeof window !== "undefined" && new URLSearchParams(window.location.search).get("cet6_review") === "1");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [refresh, setRefresh] = useState(0);
  const [sessionNumber, setSessionNumber] = useState(0), [completion, setCompletion] = useState("");
  const [roundId, setRoundId] = useState(() => typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("cet6_round") || "");
  const [round, setRound] = useState<RecallRound | null>(null);
  useEffect(() => { onFocus(!!roundId); return () => onFocus(false); }, [roundId, onFocus]);
  const starting = useRef(false), roundRequest = useRef<{kind:string;id:string} | null>(null);
  const leaveRound = () => { setRoundId(""); setRound(null); setRefresh(n => n + 1); onChanged(); cet6Route(notebookId, "vocabulary"); const url = new URL(location.href); url.searchParams.delete("cet6_round"); history.replaceState(null, "", url.pathname + url.search); };
  const startRound = async (kind: "new" | "review") => {
    if (starting.current) return;
    starting.current = true; setBusy(true); setError("");
    if (roundRequest.current?.kind !== kind) roundRequest.current = {kind,id:readingRequestId()};
    try {
      const next = await apiPost<RecallRound>(`/notebooks/${notebookId}/cet6/word-rounds`, { kind, request_id: roundRequest.current.id });
      roundRequest.current = null;
      if (!next.total) { leaveRound(); setCompletion(kind === "new" ? "今天的新词计划已完成。到期复习可以单独进行，也可调整每日新词目标。" : "目前没有到期复习卡。可以去练一组阅读，稍后再回来。"); return; }
      setWord(""); setRound(next); setRoundId(next.id); setCompletion(""); cet6Route(notebookId, "vocabulary");
      const url = new URL(location.href); url.searchParams.set("cet6_round",next.id); history.replaceState(null,"",url.pathname+url.search);
    } catch(e) { setError(readingError(e)); } finally { starting.current=false; setBusy(false); }
  };
  const request = useRef(0);
  useEffect(() => {
    if (word || roundId) return;
    const ticket = ++request.current; const timer = setTimeout(async () => {
      setBusy(true); setError("");
      try { const result = await apiGet<WordCatalogue>(`/notebooks/${notebookId}/cet6/words?view=${view}&group=${group}&q=${encodeURIComponent(query)}&offset=${offset}${order ? `&order=${order}` : ""}${family ? `&family=${encodeURIComponent(family.id)}` : ""}`); if (ticket === request.current) setData(result); }
      catch (e) { if (ticket === request.current) setError(readingError(e)); }
      finally { if (ticket === request.current) setBusy(false); }
    }, query ? 250 : 0);
    return () => { clearTimeout(timer); request.current++; };
  }, [notebookId, view, query, group, offset, word, roundId, refresh, order, family]);
  const open = (id: string, fromPlan = view === "today") => { setWord(id); setReview(fromPlan); setSessionNumber(n => n + 1); setCompletion(""); cet6Route(notebookId, "vocabulary", id, fromPlan); };
  const next = async () => { setWord(""); leaveRound(); setCompletion("这张词卡已保存。可以从新词或复习入口开始一轮练习。"); };
  if (roundId) return <><WordRound key={roundId} notebookId={notebookId} roundId={roundId} initial={round} onExit={leaveRound} onAnother={kind => void startRound(kind)} onChanged={onChanged} />{error && <p role="alert" className="cet6-error">{error}</p>}</>;
  if (word) return <VocabularyWord key={`${word}:${sessionNumber}`} notebookId={notebookId} wordId={word} review={review} onChat={onChat} onNext={next} onExit={() => { setWord(""); setRefresh(n => n + 1); onChanged(); cet6Route(notebookId, "vocabulary"); }} />;
  return <section className="cet6-vocabulary" aria-label="六级词汇学习">
    <div className="cet6-section-heading"><div><h2>词汇精学</h2><p>完整备考词表包含基础词和派生词。默认先学六级重点词，也可按自己的习惯分组。</p></div></div>
    <DailyWordPlan notebookId={notebookId} refresh={refresh} onSaved={() => { setOrder(""); setOffset(0); setRefresh(n => n + 1); onChanged(); }} onStart={kind => void startRound(kind)} starting={starting.current} />
    {completion && <p role="status" className="cet6-notice">{completion}</p>}
    <details className="cet6-source"><summary>复习时间怎么安排？</summary><p>根据每张词卡的回忆记录安排间隔。新学数量按不同单词计算，词义和拼写的复习分别安排；到期词卡不会占用新词名额。</p><p>使用 FSRS 通用参数，目标保留率为90%，这是调度设置。记录随账号保存；每天按北京时间更新计划。</p></details>
    <nav className="cet6-tabs" aria-label="词汇范围">{[["all", "查词与全部词汇"], ["mine", "我的生词"]].map(([id, title]) => <button key={id} aria-pressed={view === id} onClick={() => { setView(id); setOffset(0); }}>{title}</button>)}</nav>
    <div className="cet6-search"><label><Search size={16} /><span className="sr-only">搜索单词或派生词</span><input value={query} onChange={e => { setQuery(e.target.value); setOffset(0); setFamily(null); }} placeholder="搜索单词或派生词" maxLength={100} /></label><label><span className="sr-only">词汇级别</span><select value={group} onChange={e => { setGroup(e.target.value); setOffset(0); }}><option value="all">完整备考词表</option><option value="foundation">基础词（备考范围内）</option><option value="cet6">六级重点词</option></select></label><label><span className="sr-only">词表排序</span><select value={order || data?.order || "priority"} onChange={e => { setOrder(e.target.value as WordOrder); setOffset(0); }}>{Object.entries(wordOrders).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
    {family && <p className="cet6-family-filter">正在查看 <strong lang="en">{family.label}</strong> 词族 <button className="cet6-link-button" onClick={() => { setFamily(null); setOffset(0); }}>返回全部词表</button></p>}
    {busy && <p role="status">正在读取词库…</p>}{error && <p role="alert" className="cet6-error">{error}<button onClick={() => setRefresh(n => n + 1)}>重试</button></p>}
    {data && <><p className="cet6-muted">{view === "today" ? "先续上未完成的词卡和到期复习，再学习今天的新词。刷新或退出后，计划与进度会保留。" : view === "mine" ? "收藏来自词库或阅读中的生词，原句保存在对应义项里。" : "基础词与六级标记词都可学习；派生词单独查找，原词表关系保留。"} · 当前 {data.total} 个结果</p>
      {!data.items.length && !busy && <p className="cet6-empty">{view === "mine" ? "还没有符合条件的生词。打开词条或阅读中的“保存题中生词”即可收藏。" : "这组暂时没有待学词汇。可以清空搜索、切换级别或查看全部词汇。"}</p>}
      <div className="cet6-word-list" aria-busy={busy}>{data.items.map((item, index) => <div className="cet6-word-row" key={item.id}>
        {data.order === "family" && item.family && item.family.id !== data.items[index - 1]?.family?.id && <div className="cet6-family-heading"><strong lang="en">{item.family.label}</strong><span>{item.family.total > 1 ? `词族 · 已学 ${item.family.learned} / ${item.family.total}` : "独立词条"}</span>{item.family.total > 1 && !family && <button className="cet6-link-button" onClick={() => { setFamily(item.family); setQuery(""); setGroup("all"); setView("all"); setOffset(0); }}>查看整个词族</button>}</div>}
        <button disabled={busy} onClick={() => open(item.id)}><span><strong lang={item.word ? "en" : "zh-CN"}>{item.word || `待回忆词卡 ${offset + index + 1}`}</strong><small>{item.level === "cet6" ? "六级重点" : "大纲基础词"}{item.collected ? " · 已收藏" : ""}</small></span><span className="cet6-word-meaning">{view === "today" ? "打开后先回忆，再显示答案" : item.meaning}</span><small>{item.status}</small></button>
      </div>)}</div>
      <div className="cet6-actions"><button className="secondary-action" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</button><span>{data.total ? `${offset + 1}–${Math.min(offset + 30, data.total)} / ${data.total}` : "0 个结果"}</span><button className="secondary-action" disabled={busy || offset + 30 >= data.total} onClick={() => setOffset(offset + 30)}>下一页</button></div>
      <details className="cet6-source"><summary>词库范围与来源 · {data.manifest.entry_count} 个去重学习词条</summary><p>{data.manifest.scope}</p>{data.manifest.notes.map((note, i) => <p key={i}>{note}</p>)}<p>版本 {data.version} · <a href={data.manifest.source_url} target="_blank" rel="noreferrer">官方词表</a> · <a href={data.manifest.dictionary_url} target="_blank" rel="noreferrer">ECDICT 词义与读音</a> · <a href={data.manifest.license_url} target="_blank" rel="noreferrer">词典许可</a></p></details>
    </>}
  </section>;
}

function DailyWordPlan({ notebookId, refresh, onSaved, onStart, starting }: { notebookId: string; refresh: number; onSaved: () => void; onStart: (kind: "new" | "review") => void; starting: boolean }) {
  const [plan, setPlan] = useState<WordPlan | null>(null), [editing, setEditing] = useState(false), [target, setTarget] = useState("20");
  const [wordOrder, setWordOrder] = useState<WordOrder>("priority");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [reload, setReload] = useState(0);
  const alive = useRef(true);
  useEffect(() => { let current = true; alive.current = true; void apiGet<WordPlan>(`/notebooks/${notebookId}/cet6/word-plan`).then(p => { if (current) { setPlan(p); setError(""); } }).catch(e => { if (current) setError(readingError(e)); }); return () => { current = false; alive.current = false; }; }, [notebookId, refresh, reload]);
  const save = async () => {
    const n = Number(target);
    if (!plan || target.trim() === "" || !Number.isInteger(n) || n < 0 || n > 200) { setError("请输入0到200之间的整数；0表示只复习。"); return; }
    setBusy(true); setError("");
    try { const p = await apiPost<WordPlan>(`/notebooks/${notebookId}/cet6/word-plan`, { revision: plan.profile_revision, daily_new_words: n, word_order: wordOrder }); if (alive.current) { setPlan(p); setEditing(false); onSaved(); } }
    catch (e) { if (alive.current) setError(readingError(e)); }
    finally { if (alive.current) setBusy(false); }
  };
  return <section className="cet6-daily-plan" aria-label="每日背词计划">
    {plan ? <>
      <section className="cet6-coverage" aria-label="大纲词表学习进度"><h3>大纲词表进度</h3><div className="cet6-coverage-grid">
        <div><span>六级重点词</span><strong>{plan.coverage.priority_learned} <small>/ {plan.coverage.priority_total} 个已学</small></strong><progress aria-label="六级重点词进度" value={plan.coverage.priority_learned} max={plan.coverage.priority_total || 1} /></div>
        <div><span>完整备考词表</span><strong>{plan.coverage.learned} <small>/ {plan.coverage.total} 个已学</small></strong><progress aria-label="完整备考词表进度" value={plan.coverage.learned} max={plan.coverage.total || 1} /></div>
      </div><p>还剩 {plan.coverage.remaining} 个未学 · 基础词与派生词都在范围内。同一个词练多个义项或拼写，只计一个已学词。</p><details><summary>重点词和进度怎样计算？</summary><p>重点词是大纲标星的六级新增词及其派生词，默认先学，再按通用词频安排；不是历年真题考频。“已学”表示至少完成过一次回忆，掌握情况需要后续复习检验。</p></details></section>
      <div className="cet6-plan-progress"><div><span>今日新学</span><strong>{plan.new_done}<small> / {plan.target} 个</small></strong><progress aria-label="今日新词进度" value={Math.min(plan.new_done, plan.target)} max={Math.max(1, plan.target)} /></div><div><span>待复习</span><strong>{plan.review_due}<small> 张词卡</small></strong><small>今天已复习 {plan.review_done} 次</small></div></div>
      <div className="cet6-plan-round-actions"><button disabled={busy || starting} onClick={() => onStart("new")}><strong>开始 / 继续新词</strong><span>本轮最多 5 个 · 今日还剩 {plan.new_remaining} 个新词</span></button><button disabled={busy || starting} onClick={() => onStart("review")}><strong>开始 / 继续到期复习</strong><span>本轮最多 20 张 · 当前 {plan.review_due} 张到期</span></button></div>
      <div className="cet6-actions"><span className="cet6-muted">学习方式：{wordOrders[plan.word_order]}</span><button className="secondary-action" disabled={busy} aria-expanded={editing} onClick={() => { setEditing(v => !v); setTarget(String(plan.target)); setWordOrder(plan.word_order); }}>背词设置</button></div>
      {plan.next_family && plan.next_family.total > 1 && <p className="cet6-family-preview">接下来的词族：<span lang="en">{plan.next_family.words.join(" · ")}</span>（已学 {plan.next_family.learned} / {plan.next_family.total}）。同族连续安排，超过今日额度的词顺延。</p>}
      {plan.target === 0 && <p className="cet6-muted">今天只复习。已开始的词卡仍可继续，已有记录会保留。</p>}
      {plan.new_done > plan.target && <p className="cet6-muted">今天已学数量超过新目标，已完成记录仍保留。</p>}
      {editing && <form className="cet6-target-form" onSubmit={e => { e.preventDefault(); void save(); }}>
        <label className="cet6-field">背词顺序<select value={wordOrder} disabled={busy} onChange={e => setWordOrder(e.target.value as WordOrder)}>{Object.entries(wordOrders).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <p className="cet6-muted">{{priority:"先学六级新增词及其派生词，再补基础词。",family:"按大纲的原词与派生关系一起学，例如 able → ability；词族也优先安排六级重点。",alphabetical:"从 A 到 Z 依次学习完整词表。",random:"打散未学词。当天顺序保持稳定，刷新不会重新洗牌。"}[wordOrder]}</p>
        <label className="cet6-field">每日新词数<input type="number" min={0} max={200} step={1} required value={target} disabled={busy} onChange={e => setTarget(e.target.value)} /></label><div className="cet6-target-presets">{[0, 10, 20, 30, 50].map(n => <button key={n} type="button" disabled={busy} aria-pressed={target === String(n)} onClick={() => setTarget(String(n))}>{n === 0 ? "只复习" : `${n}个`}</button>)}</div><p className="cet6-muted">新顺序用于尚未开始的词；已打开的轮次先继续完成。已学记录保留，到期复习单独安排。</p><button className="primary-action" type="submit" disabled={busy}>保存背词设置</button></form>}
    </> : <p role="status">正在恢复每日计划…</p>}
    {error && <div role="alert" className="cet6-error"><p>{error}</p><button disabled={busy} onClick={() => setReload(n => n + 1)}>刷新目标，保留输入</button></div>}
  </section>;
}

function VocabularyWord({ notebookId, wordId, review, onExit, onChat, onNext }: { notebookId: string; wordId: string; review: boolean; onExit: () => void; onChat: (prompt: string) => void; onNext: () => Promise<void> }) {
  const [data, setData] = useState<WordDetail | null>(null), [senseId, setSenseId] = useState("");
  const [mode, setMode] = useState<"meaning" | "spelling">("meaning"), [answer, setAnswer] = useState(""), [help, setHelp] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [loadCount, setLoadCount] = useState(0);
  const alive = useRef(true), flight = useRef(false), receipt = useRef<{ key: string; id: string } | null>(null);
  const reviewDone = useRef(false);
  const url = `/notebooks/${notebookId}/cet6/words/${wordId}`;
  useEffect(() => {
    let current = true; alive.current = true; setBusy(true);
    void (async () => {
      let r = await apiGet<WordDetail>(url);
      if (!current) return;
      if (review && !reviewDone.current && !r.cards.some(c => c.active) && r.next_review.sense_id) {
        const c = r.cards.find(c => c.sense_id === r.next_review.sense_id)!;
        const body = { version: r.version, sense_id: c.sense_id, revision: c.revision, action: "start", mode: r.next_review.mode, used_help: false };
        const key = JSON.stringify(body); if (receipt.current?.key !== key) receipt.current = { key, id: readingRequestId() };
        const started = await apiPost<WordCard>(url, { ...body, request_id: receipt.current.id });
        r = { ...r, cards: r.cards.map(card => card.sense_id === c.sense_id ? started : card) }; receipt.current = null;
      }
      if (current) { setData(r); setSenseId(r.cards.find(c => c.active)?.sense_id || r.cards.filter(c => c.last).sort((a, b) => b.last!.submitted_at.localeCompare(a.last!.submitted_at))[0]?.sense_id || r.preferred_sense_id || r.entry.senses[0]?.id || ""); setError(""); }
    })().catch(e => { if (current) setError(readingError(e)); }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; alive.current = false; window.speechSynthesis?.cancel(); };
  }, [url, loadCount, review]);
  const card = data?.cards.find(c => c.sense_id === senseId), sense = data?.entry.senses.find(s => s.id === senseId), active = card?.active;
  const action = async (kind: string, rating?: string) => {
    if (!data || !card || flight.current) return;
    const body = { version: data.version, sense_id: senseId, revision: card.revision, action: kind, mode, answer, used_help: kind === "start" || help, ...(rating ? { rating } : {}) };
    const key = JSON.stringify(body); if (receipt.current?.key !== key) receipt.current = { key, id: readingRequestId() };
    flight.current = true; setBusy(true); setError(""); setNotice("");
    try { const result = await apiPost<WordCard>(url, { ...body, request_id: receipt.current.id }); if (alive.current) { setData({ ...data, cards: data.cards.map(c => c.sense_id === senseId ? result : c) }); receipt.current = null; if (kind === "collect") setNotice("已收藏到我的生词。"); if (kind === "rate") { reviewDone.current = true; cet6Route(notebookId, "vocabulary", wordId); setNotice("已保存回忆记录。下次安排见下方；本次不等于已掌握。"); setAnswer(""); setHelp(false); if (review) await onNext(); } } }
    catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  const ask = () => { if (data && sense) onChat(`请按英语词汇精讲方法帮助我理解 ${data.entry.word}，本次义项：${sense.definition}。\n释义来源：ECDICT 固定词库 ${data.version}，${data.entry.dictionary_url}。\n语境：${card?.contexts.map(c => c.text + "（我记的意思：" + c.note + "）").join("\n") || "尚未提供，请用明确标为自编的简短例句。"}\n先讲当前义项、用法和一个易混点，再给一个不直接露答案的回忆问题。真实词源仅在有可核查依据时写；AI助记明确标成助记，非真实词源；不要编造真题年份、考频或老师原讲。`); };
  return <section className="cet6-word-detail" aria-label="词汇回忆卡"><button className="cet6-back" disabled={busy} onClick={onExit}><ArrowLeft size={16} />返回词汇列表</button>
    {!data ? <p role="status">{error || "正在恢复词卡…"}</p> : <>
      <p className="cet6-eyebrow">{data.entry.level === "cet6" ? "六级标记词" : "基础词汇"} · {active ? active.used_help ? "看过参考后的练习" : "先独立回忆" : "词义与拼写分别练习"}</p>
      <h2 lang="en">{active?.mode === "spelling" && !active.revealed ? "根据词义回忆拼写" : data.entry.word}</h2>
      {(!active || active.revealed || active.mode === "meaning") && <><p className="cet6-pronunciation">{data.entry.phonetic && <span>/{data.entry.phonetic}/</span>}</p><WordPronunciation word={data.entry.word} /></>}
      {!active && <><label className="cet6-field">本次义项<select value={senseId} disabled={busy} onChange={e => { setSenseId(e.target.value); setAnswer(""); }}>{data.entry.senses.map((s, i) => <option key={s.id} value={s.id}>义项 {i + 1} · {s.definition}</option>)}</select></label>{!sense && <p>这个词的释义尚待补充，请先查看来源原页。</p>}
        <div className="cet6-actions"><button className="secondary-action" disabled={busy || !sense} onClick={() => void action("collect")}>{card?.collected ? "已收藏" : "加入我的生词"}</button><button className="secondary-action" disabled={!sense} onClick={ask}>讲清楚一点</button></div>
        <p className="cet6-muted">当前页已展示参考，从这里练习会按借助提示记录。独立复习请从“今日词卡”打开。</p><div className="cet6-recall-start"><label className="cet6-field">这次练什么<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="meaning">看词回忆词义（自己核对）</option><option value="spelling">看释义回忆拼写</option></select></label><button className="primary-action" disabled={busy || !sense} onClick={() => { setAnswer(""); setHelp(false); void action("start"); }}>开始回忆</button></div>
      </>}
      {active && <div className="cet6-recall">{active.help_reason && <p className="cet6-notice">{active.help_reason}</p>}<p>{active.mode === "meaning" ? "这个词在所选义项中是什么意思？可以先口头回忆，再写下关键词。" : sense?.definition}</p>{active.early && <p className="cet6-muted">这是提前练习，原到期时间保留。</p>}
        {!active.revealed ? <><label className="cet6-field">我的回忆<input lang="en" autoComplete="off" spellCheck={false} value={answer} maxLength={500} disabled={busy} onChange={e => setAnswer(e.target.value)} /></label><label className="cet6-check"><input type="checkbox" checked={help} onChange={e => setHelp(e.target.checked)} />这次借助了提示</label><button className="primary-action" disabled={busy} onClick={() => void action("reveal")}>核对答案</button></> : <>
          <div className="cet6-feedback"><strong lang="en">{data.entry.word}</strong><p>{sense?.definition}</p>{sense?.source_url && <p className="cet6-muted"><a href={sense.source_url} target="_blank" rel="noreferrer">{sense.source_label}</a></p>}<p>我的回忆：{active.answer || "未写下答案"}</p>{active.mode === "spelling" && <p>{active.correct ? "拼写一致" : "拼写还需要再练"}</p>}</div>
          {sense && <WordLesson notebookId={notebookId} wordId={wordId} senseId={senseId} />}
          <p className="cet6-muted">{active.mode === "meaning" ? "词义由你对照释义自评；不自动判定掌握。" : "只核对这次拼写，不代表已经会在语境中使用。"}</p>
          <p className="cet6-muted">请按翻面前的回忆评分。忘记时请选择“忘记了”；“吃力想起”表示确实回忆正确。{active.used_help || help ? "本次看过提示，按重新学习安排。" : "下方是预计的下次复习时间。"}{review && "保存后自动进入下一张。"}</p><div className="cet6-actions cet6-ratings">{([["again", "忘记了"], ["hard", "吃力想起"], ["good", "正常想起"], ["easy", "轻松想起"]] as const).map(([rating, label]) => <button key={rating} className={rating === "good" ? "primary-action" : "secondary-action"} disabled={busy || (rating !== "again" && active.mode === "spelling" && !active.correct)} onClick={() => void action("rate", rating)}><strong>{label}</strong>{card?.rating_options?.[rating] && <small>{readingDate(card.rating_options[rating])}</small>}</button>)}</div>
        </>}
      </div>}
      {!active && sense && <WordLesson notebookId={notebookId} wordId={wordId} senseId={senseId} />}
      {!active && reviewDone.current && <button className="primary-action" disabled={busy} onClick={() => void onNext().catch(e => setError(readingError(e)))}>继续今日词卡</button>}
      {!active && card?.last && <p className="cet6-next-review">下次{card.last.mode === "meaning" ? "词义" : "拼写"}复习：{readingDate(card.last.due_at)} · {card.last.basis}。{card.last.scheduling_reason}。关闭网站后不会发送通知。</p>}
      {!active && !!card?.contexts.length && <details open className="cet6-source"><summary>这个义项的原句与笔记</summary>{card.contexts.map((c, i) => <article key={i}><blockquote lang="en">{c.text}</blockquote><p>{c.note && `我记的意思：${c.note} · `}{c.source}</p>{c.question_prompt && <p>第 {c.question_number} 题：{c.question_prompt}</p>}{c.reading_id && <a href={`/?notebook=${encodeURIComponent(notebookId)}&reading=${encodeURIComponent(c.reading_id)}${c.question_id ? `&reading_question=${encodeURIComponent(c.question_id)}` : ""}`}>回到原阅读</a>}{c.paper_id && <a href={`/?notebook=${encodeURIComponent(notebookId)}&cet6=papers&cet6_paper=${encodeURIComponent(c.paper_id)}&cet6_paper_question=${c.paper_question || ""}`}>回到原卷 · 第{c.paper_question}题</a>}</article>)}</details>}
      {!active && <details className="cet6-source"><summary>词形、派生关系与来源</summary><p>异体：{data.entry.variants.join(" / ") || "无另列异体"}</p><p>原词表派生词：{data.entry.derivatives.join(" · ") || "未另列"}</p><p><a href={data.entry.source_url} target="_blank" rel="noreferrer">官方词表原页</a>（PDF 第 {data.entry.source_pages.join("、")} 页）；原始释义与读音：<a href={data.entry.dictionary_url} target="_blank" rel="noreferrer">ECDICT 社区词典</a>。核验后的补充义单独列出出处与复习记录；原词典记录可能有误，遇到疑问需核验。</p></details>}
    </>}
    {notice && <p role="status" className="cet6-notice">{notice}</p>}{error && <div role="alert" className="cet6-error"><p>{error}</p><button disabled={busy} onClick={() => setLoadCount(n => n + 1)}>重新读取词卡</button></div>}
  </section>;
}
