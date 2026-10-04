"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Volume2 } from "lucide-react";

/** Same-origin, prebuilt audio works without an installed device speech engine. */
export default function WordPronunciation({ word, entryId }: { word: string; entryId: string }) {
  const [accent, setAccent] = useState("en-US"), [slow, setSlow] = useState(false);
  const [error, setError] = useState(""), [status, setStatus] = useState("");
  const [showPlayer, setShowPlayer] = useState(false);
  const player = useRef<HTMLAudioElement>(null), attempt = useRef(0);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const src = `/word-audio/v1/${accent}/${encodeURIComponent(entryId)}.mp3`;
  const clearWait = () => { if (timeout.current) clearTimeout(timeout.current); timeout.current = null; };

  useEffect(() => {
    try { if (localStorage.getItem("learnloop:word-accent") === "en-GB") setAccent("en-GB"); } catch {}
  }, []);
  // Finish stopping the previous source before the next tap can start playback.
  useLayoutEffect(() => {
    const audio = player.current;
    setError(""); setStatus(""); setShowPlayer(false);
    return () => { attempt.current++; clearWait(); audio?.pause(); };
  }, [src]);
  useEffect(() => { if (player.current) player.current.playbackRate = slow ? .75 : 1; }, [slow, src]);

  const failed = (message: string) => { clearWait(); setStatus(""); setError(message); setShowPlayer(true); };
  const speak = () => {
    const audio = player.current;
    if (!audio) return;
    const ticket = ++attempt.current;
    clearWait(); setError(""); setStatus("正在加载发音…");
    audio.pause();
    if (audio.error || error) audio.load();
    if (audio.readyState >= 1) audio.currentTime = 0;
    audio.playbackRate = slow ? .75 : 1;
    timeout.current = setTimeout(() => {
      if (attempt.current !== ticket) return;
      attempt.current++; audio.pause();
      failed("音频加载超时，请检查网络后再点“听发音”。");
    }, 15000);
    // Call play synchronously inside the tap, before any fetch/await, for Safari
    // and Android autoplay policies. Native media handles loading and Range.
    void audio.play().catch((e: DOMException) => {
      if (attempt.current !== ticket) return;
      failed(e.name === "NotAllowedError"
        ? "浏览器暂未允许播放，请再点“听发音”，或用音频控件播放。"
        : "这次音频未能播放，请检查网络后重试，或用音频控件播放。");
    });
  };
  return <div className="word-pronunciation">
    <div className="word-voice-controls"><button type="button" className="secondary-action" onClick={speak}><Volume2 size={18} />听发音</button>
      <label><span className="sr-only">发音口音</span><select aria-label="发音口音" value={accent} onChange={e => { setAccent(e.target.value); setError(""); try { localStorage.setItem("learnloop:word-accent", e.target.value); } catch {} }}><option value="en-US">美式英语</option><option value="en-GB">英式英语</option></select></label>
      <label><input type="checkbox" checked={slow} onChange={e => setSlow(e.target.checked)} />慢速</label></div>
    <audio ref={player} src={src} preload="none" controls={showPlayer} hidden={!showPlayer} aria-label={`${word}的发音`} style={{ maxWidth: "100%" }}
      onPlaying={() => { clearWait(); setError(""); setStatus("正在播放…"); }}
      onPause={() => setStatus("")}
      onEnded={() => { clearWait(); setStatus(""); }}
      onError={() => { attempt.current++; failed("音频暂时未加载成功，请检查网络后再点“听发音”。"); }} />
    {status && <p role="status" className="cet6-muted">{status}</p>}
    <details><summary>发音来源与声音</summary><p>本站合成音频 · {accent === "en-GB" ? "英式英语（Cori）" : "美式英语（LJSpeech）"}。无需安装设备语音；多音词请结合词典核对。</p>
      <p><a href={`https://dictionary.cambridge.org/dictionary/english/${encodeURIComponent(word)}`} target="_blank" rel="noreferrer">到 Cambridge 词典核对音标、听英美发音 ↗</a></p>
    </details>{error && <p role="alert" className="cet6-error">{error}</p>}
  </div>;
}
