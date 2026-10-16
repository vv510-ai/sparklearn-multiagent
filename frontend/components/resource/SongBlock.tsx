"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Download, Mic2, Music4, PencilLine } from "lucide-react";
import { apiAssetUrl } from "@/lib/api";
import type { SongPayload } from "@/lib/types";

type Line = { text: string; section: boolean; start: number | null };

/** Split Suno-style lyrics ([Verse]/[Chorus] markers) into display lines. */
function lyricLines(lyrics: string): Line[] {
  return lyrics
    .split(/\r?\n/)
    .map(raw => raw.trim())
    .filter(Boolean)
    .map(text => ({ text: text.replace(/^\[(.*)\]$/, "$1"), section: /^\[.*\]$/.test(text), start: null }));
}

/**
 * Attach start times. Real word-level timelines (from the music service) are
 * merged line by line; without one, singable lines share the track evenly so
 * the highlight still follows the song approximately.
 */
function timed(lines: Line[], timeline: { text: string; start: number; end: number }[] | undefined, duration: number): Line[] {
  const singable = lines.filter(line => !line.section);
  if (timeline && timeline.length) {
    const queue = [...timeline];
    return lines.map(line => {
      if (line.section) return line;
      const compact = line.text.replace(/\s+/g, "");
      const hit = queue.findIndex(seg => seg.text && compact.startsWith(seg.text.replace(/\s+/g, "").slice(0, Math.min(4, compact.length))));
      if (hit < 0) return line;
      const [seg] = queue.splice(0, hit + 1).slice(-1);
      return { ...line, start: seg.start };
    });
  }
  if (!duration || !singable.length) return lines;
  const intro = Math.min(12, duration * 0.08);
  const step = (duration - intro) / singable.length;
  let index = 0;
  return lines.map(line => (line.section ? line : { ...line, start: intro + step * index++ }));
}

export default function SongBlock({ song, title }: { song: SongPayload; title: string }) {
  const versions = (song.versions || []).filter(version => version.audio_url);
  const [current, setCurrent] = useState(0);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [cloze, setCloze] = useState(false);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const audio = useRef<HTMLAudioElement>(null);
  const lyricsBox = useRef<HTMLDivElement>(null);
  const version = versions[current];
  const lines = useMemo(() => timed(lyricLines(song.lyrics || ""), version?.timeline, duration || version?.duration || 0),
    [song.lyrics, version?.timeline, version?.duration, duration]);
  const activeIndex = useMemo(() => {
    let found = -1;
    lines.forEach((line, index) => { if (line.start != null && line.start <= time + 0.15) found = index; });
    return found;
  }, [lines, time]);

  useEffect(() => {
    const box = lyricsBox.current;
    const node = box?.querySelector<HTMLElement>(`[data-line="${activeIndex}"]`);
    if (box && node) box.scrollTo({ top: Math.max(0, node.offsetTop - box.clientHeight / 2 + node.clientHeight), behavior: "smooth" });
  }, [activeIndex]);

  const plan = song.plan || {};
  const coverUrl = apiAssetUrl(version?.cover_url);
  const audioUrl = apiAssetUrl(version?.audio_url);
  const clozeItems = song.cloze || [];

  return (
    <section className="ll-song" aria-label={`${title} 记忆歌曲`}>
      <div className="ll-song-hero">
        {coverUrl
          // eslint-disable-next-line @next/next/no-img-element
          ? <img className="ll-song-cover" src={coverUrl} alt="" />
          : <div className="ll-song-cover grid place-items-center"><Music4 size={34} aria-hidden /></div>}
        <div className="min-w-0">
          <div className="text-[10px] font-black tracking-[0.2em] text-[#ffe7b0]">MEMORY SONG · 记忆歌曲</div>
          <h3 className="mt-1 truncate">{song.title || version?.title || title}</h3>
          <div className="ll-song-meta">
            {plan.genre && <span>{plan.genre}</span>}
            {plan.bpm ? <span>{plan.bpm} BPM</span> : null}
            {plan.mood && <span>{plan.mood}</span>}
            {plan.vocal_gender && <span>{/^f/i.test(plan.vocal_gender) ? "女声" : /^m/i.test(plan.vocal_gender) ? "男声" : plan.vocal_gender}</span>}
          </div>
          {versions.length > 1 && <div className="ll-song-versions" role="group" aria-label="选择歌曲版本">
            {versions.map((item, index) => <button key={item.song_id} type="button" aria-pressed={index === current} onClick={() => { setCurrent(index); setTime(0); }}>版本 {index + 1}</button>)}
          </div>}
          {audioUrl ? <audio ref={audio} key={audioUrl} src={audioUrl} controls preload="metadata"
            onTimeUpdate={event => setTime(event.currentTarget.currentTime)}
            onLoadedMetadata={event => setDuration(event.currentTarget.duration || 0)} />
            : <p className="mt-3 rounded-lg bg-black/20 px-3 py-2 text-xs leading-5">{song.error || "音乐还没有生成成功；口诀和歌词已经保存，可以先读一读。"}</p>}
        </div>
      </div>

      {plan.reason && <p className="border-b border-[#f1e2c2] bg-[#fffaf0] px-4 py-3 text-xs leading-6 text-[#7a5310]"><strong>为什么选这个风格：</strong>{plan.reason}</p>}

      <div className="ll-song-body">
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <strong className="flex items-center gap-1.5 text-sm text-[#5d3a0d]"><Mic2 size={16} aria-hidden />{cloze ? "跟唱填空" : "歌词跟唱"}</strong>
            {clozeItems.length > 0 && <button type="button" className="secondary-action !min-h-[32px] !px-3 !py-1 text-xs" onClick={() => setCloze(value => !value)}><PencilLine size={14} />{cloze ? "看完整歌词" : "填空检验"}</button>}
          </div>
          {cloze ? (
            <div className="ll-lyrics ll-cloze" aria-label="填空检验：唱出关键词">
              {clozeItems.map((item, index) => {
                const [before, ...rest] = item.line.split(item.answer);
                const value = answers[index] || "";
                const right = value.trim() !== "" && value.replace(/\s+/g, "") === item.answer.replace(/\s+/g, "");
                return <p key={index}>{before}<input aria-label={`第 ${index + 1} 处关键词`} value={value} className={right ? "is-right" : ""}
                  onChange={event => setAnswers(current => ({ ...current, [index]: event.target.value }))} />{rest.join(item.answer)}</p>;
              })}
              <p className="mt-3 text-xs text-[#8a7a5e]">先不看歌词唱一遍，再把关键词填回去。全部变绿说明已经能主动回忆。</p>
            </div>
          ) : (
            <div ref={lyricsBox} className="ll-lyrics" aria-live="off">
              {lines.length ? lines.map((line, index) => (
                <p key={index} data-line={index} className={`${line.section ? "is-section" : ""} ${index === activeIndex ? "is-active" : ""}`}
                  onClick={() => { if (line.start != null && audio.current) { audio.current.currentTime = line.start; void audio.current.play(); } }}>
                  {line.text}
                </p>
              )) : <p>歌词为空。</p>}
            </div>
          )}
        </div>
        <div className="space-y-3">
          {!!song.mnemonic?.length && <div className="ll-mnemonic">
            <h4>记忆口诀</h4>
            <ol>{song.mnemonic.map((item, index) => <li key={index}><strong>{item.line}</strong>{item.meaning && <small>{item.meaning}</small>}</li>)}</ol>
          </div>}
          {song.review && song.review.status !== "passed" && !!song.review.issues?.length && <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-xs leading-6 text-amber-900">
            <strong>歌词核对提示</strong>
            <ul className="mt-1 list-disc pl-5">{song.review.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>
          </div>}
          {audioUrl && <a className="secondary-action w-full" href={audioUrl} download={`${song.title || title}.mp3`}><Download size={15} />下载这首歌</a>}
          <p className="text-[11px] leading-5 text-[#8a7a5e]">歌曲由 AI 演唱，旋律只是记忆钩子；正式定义与条件请以讲解和资料为准。</p>
        </div>
      </div>
    </section>
  );
}
