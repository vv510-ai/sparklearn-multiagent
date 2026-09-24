"use client";

import { useRef, useState } from "react";

/** Mount with the question id as key: a new question needs a new playback. */
export default function ListeningAudio({ src, onListened }: { src: string; onListened: () => void }) {
  const [failed, setFailed] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const [buffering, setBuffering] = useState(false);
  return <div className="cet6-listening">
    <p>原创合成英语音频 · 先完整听一遍，再提交答案。文字稿在提交后提供。</p>
    {/* The transcript is intentionally deferred in this listening exercise.
        Learners unable to access audio can skip; that is never graded wrong. */}
    <audio ref={audio} controls preload="auto" onWaiting={() => setBuffering(true)} onPlaying={() => setBuffering(false)} aria-label="英语听力音频" src={src} onEnded={onListened} onError={() => setFailed(true)} onCanPlay={() => { setFailed(false); setBuffering(false); }} />
    {buffering && !failed && <p role="status">正在缓冲音频…</p>}
    {failed && <button type="button" onClick={() => { setFailed(false); setBuffering(true); audio.current?.load(); }}>重新加载听力音频</button>}
    {failed && <p role="alert">音频暂时无法播放。请检查网络后重新播放，或暂时跳过／返回计划，稍后再练。播放失败不能说明听力水平。</p>}
  </div>;
}
