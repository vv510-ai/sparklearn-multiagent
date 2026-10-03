"use client";

import { useEffect, useState } from "react";
import { Volume2 } from "lucide-react";

/** Explicit accent and voice selection; never labels device synthesis as dictionary audio. */
export default function WordPronunciation({ word }: { word: string }) {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]), [accent, setAccent] = useState("en-US");
  const [voiceName, setVoiceName] = useState(""), [slow, setSlow] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const update = () => setVoices(speechSynthesis.getVoices().filter(v => /^en[-_]/i.test(v.lang)));
    update(); speechSynthesis.addEventListener("voiceschanged", update);
    try { setAccent(localStorage.getItem("learnloop:word-accent") || "en-US"); setVoiceName(localStorage.getItem("learnloop:word-voice") || ""); } catch {}
    return () => { speechSynthesis.removeEventListener("voiceschanged", update); speechSynthesis.cancel(); };
  }, []);
  const available = voices.filter(v => v.lang.replace("_", "-").toLowerCase() === accent.toLowerCase());
  const selected = available.find(v => v.name === voiceName) || available[0];
  const speak = () => {
    setError("");
    if (!selected) { setError("这台设备没有所选口音的英语语音。可以更换口音，或到词典听真人发音。"); return; }
    speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(word);
    utterance.voice = selected; utterance.lang = selected.lang; utterance.rate = slow ? .75 : 1;
    utterance.onerror = e => { if (!["canceled", "interrupted"].includes(e.error)) setError("设备朗读失败，请重试或打开词典发音。"); };
    speechSynthesis.speak(utterance);
  };
  return <div className="word-pronunciation">
    <div className="word-voice-controls"><button className="secondary-action" onClick={speak}><Volume2 size={18} />听发音</button>
      <label><span className="sr-only">发音口音</span><select aria-label="发音口音" value={accent} onChange={e => { setAccent(e.target.value); setError(""); try { localStorage.setItem("learnloop:word-accent", e.target.value); } catch {} }}><option value="en-US">美式英语</option><option value="en-GB">英式英语</option></select></label>
      <label><input type="checkbox" checked={slow} onChange={e => setSlow(e.target.checked)} />慢速</label></div>
    <details><summary>发音来源与声音</summary><p>设备合成语音{selected ? ` · ${selected.name}` : " · 所选口音暂不可用"}。音质取决于设备安装的语音。</p>
      {!!available.length && <label>选择声音<select value={selected?.name || ""} onChange={e => { setVoiceName(e.target.value); try { localStorage.setItem("learnloop:word-voice", e.target.value); } catch {} }}>{available.map(v => <option key={v.voiceURI} value={v.name}>{v.name}</option>)}</select></label>}
      <p><a href={`https://dictionary.cambridge.org/dictionary/english/${encodeURIComponent(word)}`} target="_blank" rel="noreferrer">到 Cambridge 词典核对音标、听英美发音 ↗</a></p>
    </details>{error && <p role="alert" className="cet6-error">{error}</p>}
  </div>;
}
