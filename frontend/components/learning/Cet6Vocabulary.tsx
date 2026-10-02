"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Search, Volume2 } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { readingDate, readingError, readingRequestId } from "@/lib/reading";
import { cet6Route, type WordCatalogue, type WordDetail, type WordCard } from "@/lib/cet6";

export function speakEnglish(text: string, onError: (message: string) => void, onEnd?: () => void) {
  if (!("speechSynthesis" in window)) { onError("当前浏览器不支持朗读，请使用有音频的资料或换支持朗读的浏览器。"); return false; }
  const voice = window.speechSynthesis.getVoices().find(v => /^en(-|_)/i.test(v.lang));
  if (!voice) { onError("当前设备尚未提供英语语音。请安装英语语音或使用资料中心的原站音频。"); return false; }
  window.speechSynthesis.cancel();
  const speech = new SpeechSynthesisUtterance(text); speech.lang = voice.lang; speech.voice = voice; speech.rate = .9;
  speech.onerror = e => { if (e.error !== "canceled" && e.error !== "interrupted") onError("这次朗读未成功，请重试或使用原站音频。"); onEnd?.(); };
  speech.onend = () => onEnd?.(); window.speechSynthesis.speak(speech); return true;
}

export default function Cet6Vocabulary({ notebookId, onChat, initialWord, onChanged }: {
  notebookId: string; onChat: (prompt: string) => void; initialWord?: string; onChanged: () => void;
}) {
  const [view, setView] = useState("today"), [query, setQuery] = useState(""), [group, setGroup] = useState("all"), [offset, setOffset] = useState(0);
  const [data, setData] = useState<WordCatalogue | null>(null), [word, setWord] = useState(initialWord || "");
  const [review, setReview] = useState(() => typeof window !== "undefined" && new URLSearchParams(window.location.search).get("cet6_review") === "1");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [refresh, setRefresh] = useState(0);
  const request = useRef(0);
  useEffect(() => {
    if (word) return;
    const ticket = ++request.current; const timer = setTimeout(async () => {
      setBusy(true); setError("");
      try { const result = await apiGet<WordCatalogue>(`/notebooks/${notebookId}/cet6/words?view=${view}&group=${group}&q=${encodeURIComponent(query)}&offset=${offset}`); if (ticket === request.current) setData(result); }
      catch (e) { if (ticket === request.current) setError(readingError(e)); }
      finally { if (ticket === request.current) setBusy(false); }
    }, query ? 250 : 0);
    return () => { clearTimeout(timer); request.current++; };
  }, [notebookId, view, query, group, offset, word, refresh]);
  const open = (id: string) => { setWord(id); setReview(view === "today"); cet6Route(notebookId, "vocabulary", id, view === "today"); };
  if (word) return <VocabularyWord key={word} notebookId={notebookId} wordId={word} review={review} onChat={onChat} onExit={() => { setWord(""); setRefresh(n => n + 1); onChanged(); cet6Route(notebookId, "vocabulary"); }} />;
  return <section className="cet6-vocabulary" aria-label="六级词汇学习">
    <div className="cet6-section-heading"><div><h2>把词记在语境里</h2><p>先回忆，再核对；认得词义和写得出来分别记录。</p></div></div><details className="cet6-source"><summary>复习时间怎么安排？</summary><p>使用 Anki 也支持的 FSRS 算法，根据每张词卡的回忆记录安排间隔。新词先短间隔复习，能稳定想起后逐渐拉长；忘记后重新学习。词义与拼写单独安排。</p><p>初期使用通用参数，目标记忆保留率设为 90%，这是调度设置，不是学习效果保证。提前练习保留原时间；看过提示不算独立回忆。记录随本站账号保存，关闭网站后不会推送通知。</p></details>
    <nav className="cet6-tabs" aria-label="词汇范围">{[["today", "今天学什么"], ["all", "全部词汇"], ["mine", "我的生词"]].map(([id, title]) => <button key={id} aria-pressed={view === id} onClick={() => { setView(id); setOffset(0); }}>{title}</button>)}</nav>
    <div className="cet6-search"><label><Search size={16} /><span className="sr-only">搜索单词或派生词</span><input value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }} placeholder="搜索单词或派生词" maxLength={100} /></label><label><span className="sr-only">词汇级别</span><select value={group} onChange={e => { setGroup(e.target.value); setOffset(0); }}><option value="all">基础与六级</option><option value="foundation">基础词汇</option><option value="cet6">六级标记词</option></select></label></div>
    {busy && <p role="status">正在读取词库…</p>}{error && <p role="alert" className="cet6-error">{error}<button onClick={() => setRefresh(n => n + 1)}>重试</button></p>}
    {data && <><p className="cet6-muted">{view === "today" ? "按到期记录、可用时间和学习偏好选一小组。逾期词卡仍保留，可在全部词汇查看。" : view === "mine" ? "收藏来自词库或阅读中的生词，原句保存在对应义项里。" : "基础词与六级标记词都可学习；派生词单独查找，原词表关系保留。"} · 当前 {data.total} 个结果</p>
      {!data.items.length && !busy && <p className="cet6-empty">{view === "mine" ? "还没有符合条件的生词。打开词条或阅读中的“保存题中生词”即可收藏。" : "这组暂时没有待学词汇。可以清空搜索、切换级别或查看全部词汇。"}</p>}
      <div className="cet6-word-list" aria-busy={busy}>{data.items.map((item, index) => <button key={item.id} disabled={busy} onClick={() => open(item.id)}><span><strong lang={item.word ? "en" : "zh-CN"}>{item.word || `待回忆词卡 ${offset + index + 1}`}</strong><small>{item.level === "cet6" ? "六级标记" : "基础词汇"}{item.collected ? " · 已收藏" : ""}</small></span><span className="cet6-word-meaning">{view === "today" ? "打开后先回忆，再显示答案" : item.meaning}</span><small>{item.status}</small></button>)}</div>
      <div className="cet6-actions"><button className="secondary-action" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</button><span>{data.total ? `${offset + 1}–${Math.min(offset + 30, data.total)} / ${data.total}` : "0 个结果"}</span><button className="secondary-action" disabled={busy || offset + 30 >= data.total} onClick={() => setOffset(offset + 30)}>下一页</button></div>
      <details className="cet6-source"><summary>词库范围与来源 · {data.manifest.entry_count} 个去重学习词条</summary><p>{data.manifest.scope}</p>{data.manifest.notes.map((note, i) => <p key={i}>{note}</p>)}<p>版本 {data.version} · <a href={data.manifest.source_url} target="_blank" rel="noreferrer">官方词表</a> · <a href={data.manifest.dictionary_url} target="_blank" rel="noreferrer">ECDICT 词义与读音</a> · <a href={data.manifest.license_url} target="_blank" rel="noreferrer">词典许可</a></p></details>
    </>}
  </section>;
}

function VocabularyWord({ notebookId, wordId, review, onExit, onChat }: { notebookId: string; wordId: string; review: boolean; onExit: () => void; onChat: (prompt: string) => void }) {
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
      if (current) { setData(r); setSenseId(r.cards.find(c => c.active)?.sense_id || r.entry.senses[0]?.id || ""); setError(""); }
    })().catch(e => { if (current) setError(readingError(e)); }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; alive.current = false; window.speechSynthesis?.cancel(); };
  }, [url, loadCount, review]);
  const card = data?.cards.find(c => c.sense_id === senseId), sense = data?.entry.senses.find(s => s.id === senseId), active = card?.active;
  const action = async (kind: string, rating?: string) => {
    if (!data || !card || flight.current) return;
    const body = { version: data.version, sense_id: senseId, revision: card.revision, action: kind, mode, answer, used_help: kind === "start" || help, ...(rating ? { rating } : {}) };
    const key = JSON.stringify(body); if (receipt.current?.key !== key) receipt.current = { key, id: readingRequestId() };
    flight.current = true; setBusy(true); setError(""); setNotice("");
    try { const result = await apiPost<WordCard>(url, { ...body, request_id: receipt.current.id }); if (alive.current) { setData({ ...data, cards: data.cards.map(c => c.sense_id === senseId ? result : c) }); receipt.current = null; if (kind === "collect") setNotice("已收藏到我的生词。"); if (kind === "rate") { reviewDone.current = true; cet6Route(notebookId, "vocabulary", wordId); setNotice("已保存回忆记录。下次安排见下方；本次不等于已掌握。"); setAnswer(""); setHelp(false); } } }
    catch (e) { if (alive.current) setError(readingError(e)); }
    finally { flight.current = false; if (alive.current) setBusy(false); }
  };
  const ask = () => { if (data && sense) onChat(`请按英语词汇精讲方法帮助我理解 ${data.entry.word}，本次义项：${sense.definition}。\n释义来源：ECDICT 固定词库 ${data.version}，${data.entry.dictionary_url}。\n语境：${card?.contexts.map(c => c.text + "（我记的意思：" + c.note + "）").join("\n") || "尚未提供，请用明确标为自编的简短例句。"}\n先讲当前义项、用法和一个易混点，再给一个不直接露答案的回忆问题。真实词源仅在有可核查依据时写；AI助记明确标成助记，非真实词源；不要编造真题年份、考频或老师原讲。`); };
  return <section className="cet6-word-detail" aria-label="词汇回忆卡"><button className="cet6-back" disabled={busy} onClick={onExit}><ArrowLeft size={16} />返回词汇列表</button>
    {!data ? <p role="status">{error || "正在恢复词卡…"}</p> : <>
      <p className="cet6-eyebrow">{data.entry.level === "cet6" ? "六级标记词" : "基础词汇"} · {active ? active.used_help ? "看过参考后的练习" : "先独立回忆" : "词义与拼写分别练习"}</p>
      <h2 lang="en">{active?.mode === "spelling" && !active.revealed ? "根据词义回忆拼写" : data.entry.word}</h2>
      {(!active || active.revealed || active.mode === "meaning") && <p className="cet6-pronunciation">{data.entry.phonetic && <span>/{data.entry.phonetic}/</span>}<button className="secondary-action" onClick={() => speakEnglish(data.entry.word, setError)}><Volume2 size={16} />设备朗读</button><small>合成语音，口音由设备提供</small></p>}
      {!active && <><label className="cet6-field">本次义项<select value={senseId} disabled={busy} onChange={e => { setSenseId(e.target.value); setAnswer(""); }}>{data.entry.senses.map((s, i) => <option key={s.id} value={s.id}>义项 {i + 1} · {s.definition}</option>)}</select></label>{!sense && <p>这个词的释义尚待补充，请先查看来源原页。</p>}
        <div className="cet6-actions"><button className="secondary-action" disabled={busy || !sense} onClick={() => void action("collect")}>{card?.collected ? "已收藏" : "加入我的生词"}</button><button className="secondary-action" disabled={!sense} onClick={ask}>讲清楚一点</button></div>
        <p className="cet6-muted">当前页已展示参考，从这里练习会按借助提示记录。独立复习请从“今天学什么”打开词卡。</p><div className="cet6-recall-start"><label className="cet6-field">这次练什么<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="meaning">看词回忆词义（自己核对）</option><option value="spelling">看释义回忆拼写</option></select></label><button className="primary-action" disabled={busy || !sense} onClick={() => { setAnswer(""); setHelp(false); void action("start"); }}>开始回忆</button></div>
      </>}
      {active && <div className="cet6-recall"><p>{active.mode === "meaning" ? "这个词在所选义项中是什么意思？可以先口头回忆，再写下关键词。" : sense?.definition}</p>{active.early && <p className="cet6-muted">这是提前练习，原到期时间保留。</p>}
        {!active.revealed ? <><label className="cet6-field">我的回忆<input lang="en" autoComplete="off" spellCheck={false} value={answer} maxLength={500} disabled={busy} onChange={e => setAnswer(e.target.value)} /></label><label className="cet6-check"><input type="checkbox" checked={help} onChange={e => setHelp(e.target.checked)} />这次借助了提示</label><button className="primary-action" disabled={busy} onClick={() => void action("reveal")}>核对答案</button></> : <>
          <div className="cet6-feedback"><strong lang="en">{data.entry.word}</strong><p>{sense?.definition}</p><p>我的回忆：{active.answer || "未写下答案"}</p>{active.mode === "spelling" && <p>{active.correct ? "拼写一致" : "拼写还需要再练"}</p>}</div>
          <p className="cet6-muted">{active.mode === "meaning" ? "词义由你对照释义自评；不自动判定掌握。" : "只核对这次拼写，不代表已经会在语境中使用。"}</p>
          <p className="cet6-muted">忘记时请选择“忘记了”；“吃力想起”表示确实回忆正确。{active.used_help || help ? "本次看过提示，按重新学习安排，不计为独立回忆。" : "下方显示预计的下次复习时间。"}</p><div className="cet6-actions cet6-ratings">{([["again", "忘记了"], ["hard", "吃力想起"], ["good", "正常想起"], ["easy", "轻松想起"]] as const).map(([rating, label]) => <button key={rating} className={rating === "good" ? "primary-action" : "secondary-action"} disabled={busy || (rating !== "again" && active.mode === "spelling" && !active.correct)} onClick={() => void action("rate", rating)}><strong>{label}</strong>{card?.rating_options?.[rating] && <small>{readingDate(card.rating_options[rating])}</small>}</button>)}</div>
        </>}
      </div>}
      {!active && card?.last && <p className="cet6-next-review">下次{card.last.mode === "meaning" ? "词义" : "拼写"}复习：{readingDate(card.last.due_at)} · {card.last.basis}。{card.last.scheduling_reason}。关闭网站后不会发送通知。</p>}
      {!active && !!card?.contexts.length && <details open className="cet6-source"><summary>这个义项的原句与笔记</summary>{card.contexts.map((c, i) => <article key={i}><blockquote lang="en">{c.text}</blockquote><p>{c.note && `我记的意思：${c.note} · `}{c.source}</p>{c.question_prompt && <p>第 {c.question_number} 题：{c.question_prompt}</p>}{c.reading_id && <a href={`/?notebook=${encodeURIComponent(notebookId)}&reading=${encodeURIComponent(c.reading_id)}${c.question_id ? `&reading_question=${encodeURIComponent(c.question_id)}` : ""}`}>回到原阅读</a>}</article>)}</details>}
      {!active && <details className="cet6-source"><summary>词形、派生关系与来源</summary><p>异体：{data.entry.variants.join(" / ") || "无另列异体"}</p><p>原词表派生词：{data.entry.derivatives.join(" · ") || "未另列"}</p><p><a href={data.entry.source_url} target="_blank" rel="noreferrer">官方词表原页</a>（PDF 第 {data.entry.source_pages.join("、")} 页）；释义与读音：<a href={data.entry.dictionary_url} target="_blank" rel="noreferrer">ECDICT 社区词典</a>。词典记录可能有误，遇到疑问需核验。</p></details>}
    </>}
    {notice && <p role="status" className="cet6-notice">{notice}</p>}{error && <div role="alert" className="cet6-error"><p>{error}</p><button disabled={busy} onClick={() => setLoadCount(n => n + 1)}>重新读取词卡</button></div>}
  </section>;
}
