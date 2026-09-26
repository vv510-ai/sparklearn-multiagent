"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Play, RotateCcw } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import Markdown from "@/components/chat/Markdown";

type Question = { stem: string; options: string[]; answer: string; explanation: string };
type Scene = {
  resource_id?: string; title: string; provenance: string; notes: string;
  lines: { speaker: string; text: string; translation: string; timestamp: string }[];
  vocabulary: { word: string; meaning: string; usage: string; memory: string; contrast: string }[];
  question: Question | null;
  generation?: { status: string; message: string };
  request?: { words: string; scene: string; goal: string; level: string };
  source_text?: string;
};
const input = "mt-2 w-full rounded-xl border border-[#D8E1D8] bg-white p-3 text-sm";
const goals = ["影视理解与日常交流", "高考", "英语四级", "英语六级", "考研英语", "雅思", "托福", "职场英语"];
const presets = [
  { title: "周末邀约", scene: "朋友一起商量周末计划", words: "hesitate, awkward, figure out" },
  { title: "咖啡店点单", scene: "在咖啡店点单并说明自己的偏好", words: "recommend, instead, take away" },
  { title: "工作沟通", scene: "和同事确认任务进度与下一步安排", words: "follow up, clarify, deadline" },
];
const readableError = (e: unknown) => e instanceof Error
  ? e.message.replace(/^(GET|POST) \S+ → \d+:\s*/, "")
  : "暂时无法完成，请重试。";

export default function EnglishScenes({ notebookId, onBack }: { notebookId: string; onBack: () => void }) {
  const [goal, setGoal] = useState(goals[0]);
  const [level, setLevel] = useState("中等");
  const [words, setWords] = useState(presets[0].words);
  const [scene, setScene] = useState(presets[0].scene);
  const [subtitles, setSubtitles] = useState("");
  const [result, setResult] = useState<Scene | null>(null);
  const [busy, setBusy] = useState(false);
  const [questionBusy, setQuestionBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [questionError, setQuestionError] = useState("");
  const [notice, setNotice] = useState("");
  const [showTranslation, setShowTranslation] = useState(false);
  const [selected, setSelected] = useState("");
  const [checked, setChecked] = useState(false);
  const [videoUrl, setVideoUrl] = useState("");
  const [videoSource, setVideoSource] = useState("");
  const [videoError, setVideoError] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const epoch = useRef(0);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const waiting = busy || questionBusy || loading;

  useEffect(() => () => { if (videoUrl) URL.revokeObjectURL(videoUrl); }, [videoUrl]);
  useEffect(() => {
    const request = ++epoch.current;
    setResult(null); setError(""); setQuestionError(""); setNotice(""); setLoading(true);
    void apiGet<Scene | null>("/learning/english/scene/latest?notebook_id=" + encodeURIComponent(notebookId)).then(saved => {
      if (request !== epoch.current || !saved) return;
      setResult(saved);
      if (saved.request) {
        setWords(saved.request.words); setScene(saved.request.scene);
        setGoal(saved.request.goal); setLevel(saved.request.level);
      }
      setSubtitles(saved.source_text || "");
      setNotice("已恢复本课程最近保存的场景。");
    }).catch(() => {
      if (request === epoch.current) setNotice("暂时无法读取上次场景；已有资料仍在归档中。");
    }).finally(() => { if (request === epoch.current) setLoading(false); });
    return () => { epoch.current++; };
  }, [notebookId]);

  async function generate() {
    if (waiting) return;
    const request = ++epoch.current;
    setBusy(true); setError(""); setQuestionError(""); setNotice("");
    try {
      const next = await apiPost<Scene>("/learning/english/scene", { words, scene, goal, level, subtitles, notebook_id: notebookId });
      if (request !== epoch.current) return;
      setResult(next); setSelected(""); setChecked(false); setShowTranslation(false);
      // A local video is only associated with the exact subtitle input for this result.
      setVideoSource(videoUrl ? subtitles : "");
      setNotice("新场景已保存到资料归档。");
      requestAnimationFrame(() => resultHeading.current?.focus());
    } catch (e) {
      if (request === epoch.current) setError(readableError(e) + (result ? " 上次保存的场景仍保留在下方。" : ""));
    } finally { if (request === epoch.current) setBusy(false); }
  }

  async function retryQuestion() {
    if (waiting || !result?.resource_id) return;
    const request = ++epoch.current;
    const resourceId = result.resource_id;
    setQuestionBusy(true); setQuestionError("");
    try {
      const update = await apiPost<Pick<Scene, "question" | "generation">>("/learning/english/scene/question", { resource_id: resourceId, notebook_id: notebookId });
      if (request !== epoch.current) return;
      setResult(previous => previous?.resource_id === resourceId ? { ...previous, ...update } : previous);
      setSelected(""); setChecked(false);
    } catch (e) { if (request === epoch.current) setQuestionError(readableError(e)); }
    finally { if (request === epoch.current) setQuestionBusy(false); }
  }

  function replay(timestamp: string) {
    const match = timestamp.match(/(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[,.](\d+))?/);
    if (!video.current || !match) return;
    video.current.currentTime = Number(match[1] || 0) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number("0." + (match[4] || 0));
    void video.current.play().catch(() => setVideoError("视频暂时无法播放，请检查文件后重试；可以继续阅读原句。"));
  }

  const canReplay = !!videoUrl && !!result?.source_text && videoSource === result.source_text;
  const question = result?.question;
  return <div className="notebook-content-scroll">
    <div className="notebook-content-heading">
      <div><span>ENGLISH IN CONTEXT</span><h1>英语场景学习</h1><p>读懂一段对话，再试着用出其中的表达。</p></div>
      <button className="secondary-action" onClick={onBack}><ArrowLeft size={15} />返回</button>
    </div>
    <div className="mx-auto max-w-4xl space-y-5 p-5 pb-16">
      <section aria-label="现成英语场景" className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#DDE5D9] bg-emerald-50 p-5">
        <div><h2 className="font-bold">从现成场景开始学</h2><p className="mt-1 text-sm leading-6 text-slate-600">同学邀约、咖啡店点单、室友协商。含原创对话和合成音频，无需上传。</p></div>
        <a href="/library#course-english-scenes" className="primary-action">进入场景课程</a>
      </section>
      <form onSubmit={e => { e.preventDefault(); void generate(); }} className="space-y-4 rounded-2xl border border-[#DDE5D9] bg-white p-5">
        <h2 className="font-bold">用想学的词，自定义一个场景</h2>
        <fieldset disabled={waiting} className="min-w-0 space-y-4">
          <div className="flex flex-wrap gap-2" aria-label="场景示例">{presets.map(p => <button key={p.title} type="button" className="secondary-action" onClick={() => { setWords(p.words); setScene(p.scene); }}>{p.title}</button>)}</div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm font-semibold">学习目标<select className={input} value={goal} onChange={e => setGoal(e.target.value)}>{goals.map(g => <option key={g}>{g}</option>)}</select></label>
            <label className="text-sm font-semibold">当前水平<select className={input} value={level} onChange={e => setLevel(e.target.value)}>{["入门", "中等", "进阶"].map(g => <option key={g}>{g}</option>)}</select></label>
          </div>
          <label className="block text-sm font-semibold">想学的单词或短语<input className={input} required maxLength={400} value={words} onChange={e => setWords(e.target.value)} /></label>
          <label className="block text-sm font-semibold">生活场景或影视片段说明<input className={input} maxLength={300} value={scene} onChange={e => setScene(e.target.value)} /></label>
          <details>
            <summary className="cursor-pointer text-sm font-semibold">使用自己的字幕或本地视频（可选）</summary>
            <div className="mt-3 space-y-3">
              <label className="block text-sm font-semibold">真实字幕或原句（可选）<textarea className={input} rows={5} maxLength={16000} value={subtitles} onChange={e => setSubtitles(e.target.value)} placeholder="粘贴有权使用的字幕，可保留时间戳。留空会生成原创教学对话。" /></label>
              <div className="flex flex-wrap gap-5 text-xs text-slate-600">
                <label>读取字幕文件<input className="mt-2 block max-w-full" type="file" accept=".srt,.vtt,.txt" onChange={async e => {
                  const file = e.target.files?.[0]; if (!file) return;
                  if (file.size > 100000) { setError("字幕文件过大，请截取当前片段。"); return; }
                  const current = epoch.current;
                  try {
                    const text = await file.text();
                    if (current !== epoch.current) return;
                    if (text.length > 16000) { setError("字幕超过16000字，请选取一个完整片段。"); return; }
                    setSubtitles(text); setError("");
                  } catch { if (current === epoch.current) setError("未能读取字幕文件，请重新选择。"); }
                }} /></label>
                <label>选择本地视频<input className="mt-2 block max-w-full" type="file" accept="video/*" onChange={e => {
                  const file = e.target.files?.[0]; if (!file) return;
                  setVideoUrl(URL.createObjectURL(file)); setVideoError(""); setVideoSource(subtitles);
                }} /></label>
              </div>
              <p className="text-xs leading-6 text-slate-500">视频只在浏览器播放；生成时发送文字和学习目标。没有原字幕时使用原创对话，未核验的词源和发音不作为已查证事实。</p>
            </div>
          </details>
          {!!subtitles && <p className="text-xs text-slate-600">本次将使用已填写的字幕原句。</p>}
          <button className="primary-action" disabled={waiting || !words.trim()}>{busy ? "正在整理场景与词汇…" : "生成场景笔记"}</button>
        </fieldset>
      </form>
      {loading && <p role="status" className="text-sm text-slate-600">正在读取上次保存的场景…</p>}
      {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {videoUrl && <video ref={video} src={videoUrl} controls className="max-h-80 w-full rounded-xl bg-black" onError={() => setVideoError("视频暂时无法播放，可以继续阅读原句。")} />}
      {videoError && <p role="alert" className="text-sm text-amber-800">{videoError}</p>}
      {result && <>
        <section aria-label="场景原句" className="space-y-3 rounded-2xl border bg-white p-5">
          <p className="text-xs leading-6 text-emerald-800">{result.provenance} · 已保存到资料归档</p>
          <div className="flex flex-wrap items-center justify-between gap-3"><h2 ref={resultHeading} tabIndex={-1} className="font-bold">{result.title}</h2><button className="secondary-action" onClick={() => setShowTranslation(v => !v)}>{showTranslation ? "隐藏中文" : "显示中文"}</button></div>
          {result.lines.map((line, i) => <div key={i} className="rounded-xl bg-slate-50 p-3">
            <p className="text-xs text-slate-500">{line.speaker} {line.timestamp}</p>
            <p lang="en" className="mt-1 break-words text-base leading-7">{line.text}</p>
            {showTranslation && <p className="mt-1 text-sm leading-6 text-slate-600">{line.translation}</p>}
            {canReplay && line.timestamp && <button className="mt-2 flex items-center gap-1 text-xs text-emerald-700" onClick={() => replay(line.timestamp)}><Play size={12} />回到原片段</button>}
          </div>)}
        </section>
        <section aria-label="词汇与搭配" className="grid gap-3 sm:grid-cols-2">{result.vocabulary.map((word, i) => <article key={i} className="min-w-0 rounded-xl border bg-white p-4">
          <h3 lang="en" className="break-words text-lg font-bold">{word.word}</h3>
          <p className="mt-2 text-sm font-semibold">{word.meaning}</p><p className="mt-2 text-sm leading-6 text-slate-600">{word.usage}</p>
          {word.contrast && <p className="mt-2 text-sm leading-6 text-slate-600">辨析：{word.contrast}</p>}
        </article>)}</section>
        <details className="rounded-2xl border bg-white p-5"><summary className="cursor-pointer font-bold">展开用法笔记</summary><div className="mt-4"><Markdown text={result.notes} /></div></details>
        <section aria-label="场景练习" className="rounded-2xl border bg-white p-5">
          <h2 className="font-bold">在场景中回忆</h2>
          {question ? <>
            <p className="my-3 whitespace-pre-wrap text-sm leading-7">{question.stem}</p>
            <div role="group" aria-label="英语练习选项" className="grid gap-2 sm:grid-cols-2">{question.options.map((option, i) => {
              const letter = String.fromCharCode(65 + i);
              return <button key={letter} disabled={checked} aria-pressed={selected === letter} onClick={() => setSelected(letter)} className={"rounded-xl border p-3 text-left text-sm " + (selected === letter ? "border-emerald-600 bg-emerald-50" : "border-slate-200")}>{letter}. {option}</button>;
            })}</div>
            {!checked ? <button className="primary-action mt-4" disabled={!selected} onClick={() => setChecked(true)}>确认答案</button> : <div role="status" className="mt-4 space-y-3 text-sm">
              <p className="font-semibold">{selected === question.answer ? "回答正确" : "再看一下本句语境"} · 答案 {question.answer}</p><p className="leading-7">{question.explanation}</p>
              <button className="secondary-action" onClick={() => { setSelected(""); setChecked(false); }}><RotateCcw size={14} />重新回忆</button>
            </div>}
          </> : <>
            <p role="status" className="my-3 text-sm leading-7 text-slate-600">{result.generation?.message || "对话和词汇笔记已保存，可以先学习；练习暂未就绪。"}</p>
            {result.resource_id && <button className="primary-action" disabled={waiting} onClick={() => void retryQuestion()}>{questionBusy ? "正在补生成练习…" : "只补生成练习"}</button>}
          </>}
          {questionError && <p role="alert" className="mt-3 text-sm text-red-800">{questionError} 对话与笔记仍然保留。</p>}
        </section>
      </>}
    </div>
  </div>;
}
