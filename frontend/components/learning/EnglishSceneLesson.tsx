"use client";

import { useEffect, useRef, useState } from "react";

export type EnglishScene = {
  context: string; alignment: string;
  lines: { id: string; speaker: string; text: string; translation: string }[];
  steps: { id: string; title: string; parts: string[]; explanation: string }[];
  references: { title: string; url: string }[];
  audio: { url: string; sha256: string; duration: number; notice: string; cues: { line_id: string; start: number; end: number }[] };
};

type Props = { scene: EnglishScene; busy: boolean; recorded: boolean; onRecord: () => void };

export default function EnglishSceneLesson({ scene, busy, recorded, onRecord }: Props) {
  const audio = useRef<HTMLAudioElement>(null);
  const mode = useRef<"whole" | "line" | "idle">("idle");
  const selected = useRef(0);
  const loopRef = useRef(false);
  const [lineIndex, setLineIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [finished, setFinished] = useState(false);
  const [failed, setFailed] = useState(false);
  const [english, setEnglish] = useState(false);
  const [chinese, setChinese] = useState(false);
  const [loop, setLoop] = useState(false);
  const [rate, setRate] = useState(1);
  const [stepIndex, setStepIndex] = useState(0);
  const [animating, setAnimating] = useState(false);
  const step = scene.steps[stepIndex];
  const line = scene.lines[lineIndex];

  useEffect(() => {
    const player = audio.current;
    const hidden = () => { if (document.hidden && mode.current === "line") player?.pause(); };
    const leaving = () => player?.pause();
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("pagehide", leaving);
    return () => { player?.pause(); document.removeEventListener("visibilitychange", hidden); window.removeEventListener("pagehide", leaving); };
  }, []);

  useEffect(() => {
    if (!animating) return;
    const timer = window.setTimeout(() => {
      if (stepIndex === scene.steps.length - 1) setAnimating(false);
      else setStepIndex(i => i + 1);
    }, 4200);
    return () => window.clearTimeout(timer);
  }, [animating, stepIndex, scene.steps.length]);

  // Animation-frame boundaries keep short line repeats inside their actual PCM cue.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const player = audio.current;
      if (player && mode.current === "line") {
        const cue = scene.audio.cues[selected.current];
        if (player.currentTime >= cue.end) {
          if (loopRef.current) player.currentTime = cue.start;
          else player.pause();
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, scene.audio.cues]);

  const play = async () => {
    try { await audio.current?.play(); setFailed(false); }
    catch { setFailed(true); setFinished(false); }
  };
  const jump = (index: number) => {
    const target = Math.max(0, Math.min(scene.lines.length - 1, index));
    audio.current?.pause(); mode.current = "idle";
    selected.current = target; setLineIndex(target);
    if (audio.current) audio.current.currentTime = scene.audio.cues[target].start;
  };
  const full = () => {
    const player = audio.current;
    if (!player) return;
    if (mode.current === "whole" && !player.paused) { player.pause(); return; }
    if (mode.current !== "whole" || player.ended) {
      player.currentTime = 0; selected.current = 0; setLineIndex(0); setFinished(false);
    }
    mode.current = "whole"; void play();
  };
  const repeat = () => {
    const player = audio.current;
    if (!player) return;
    player.pause(); mode.current = "line";
    player.currentTime = scene.audio.cues[selected.current].start;
    void play();
  };
  const moveStep = (index: number) => { setAnimating(false); setStepIndex(Math.max(0, Math.min(scene.steps.length - 1, index))); };
  const toggleSteps = () => {
    if (!animating && stepIndex === scene.steps.length - 1) setStepIndex(0);
    setAnimating(value => !value);
  };

  return <div className="english-scene">
    <section aria-label="场景听力" className="scene-listening">
      <p className="library-eyebrow">01 · 先听情境</p><h2>他们最后商量好了什么？</h2><p>{scene.context}</p>
      <audio ref={audio} preload="metadata" src={scene.audio.url}
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        onError={() => { setFailed(true); setFinished(false); setPlaying(false); mode.current = "idle"; }}
        onEnded={() => { if (mode.current === "whole") setFinished(true); setPlaying(false); mode.current = "idle"; }}
        onTimeUpdate={() => {
          if (mode.current !== "whole" || !audio.current) return;
          const time = audio.current.currentTime;
          const at = scene.audio.cues.findIndex(c => time >= c.start && time < c.end);
          if (at >= 0) { selected.current = at; setLineIndex(at); }
        }} />
      <div className="scene-controls">
        <button className="library-primary" onClick={full}>{playing && mode.current === "whole" ? "暂停整段" : mode.current === "whole" ? "继续整段" : "播放整段"}</button>
        <button disabled={!playing} onClick={() => audio.current?.pause()}>暂停音频</button>
        <label>语速 <select aria-label="语速" value={rate} onChange={e => { const value = Number(e.target.value); setRate(value); if (audio.current) audio.current.playbackRate = value; }}><option value={0.85}>0.85 倍</option><option value={1}>1 倍</option><option value={1.15}>1.15 倍</option></select></label>
        <span>{Math.round(scene.audio.duration)} 秒</span>
      </div>
      <p className="library-small">{scene.audio.notice}</p>
      {failed && <div className="library-error" role="alert">音频暂时无法播放。可以继续看文字，不会记录完整播放。<button onClick={() => { audio.current?.load(); setFailed(false); }}>重新载入音频</button></div>}
      <div className="scene-controls"><label className="library-check"><input type="checkbox" checked={english} onChange={e => setEnglish(e.target.checked)} />显示英文字幕</label><label className="library-check"><input type="checkbox" checked={chinese} onChange={e => setChinese(e.target.checked)} />显示中文释义</label></div>
      <div className="scene-current-line" aria-label="当前句子">
        <p className="library-eyebrow">{line.speaker} · 第 {lineIndex + 1} / {scene.lines.length} 句</p>
        <p className="scene-english" lang="en">{english ? line.text : "先听声音，需要时再打开字幕。"}</p>
        {chinese && <p>{line.translation}</p>}
      </div>
      <div className="scene-controls">
        <button disabled={lineIndex === 0} onClick={() => jump(lineIndex - 1)}>上一句</button>
        <button onClick={repeat}>复听当前句</button>
        <button disabled={lineIndex === scene.lines.length - 1} onClick={() => jump(lineIndex + 1)}>下一句</button>
        <label className="library-check"><input type="checkbox" checked={loop} onChange={e => { setLoop(e.target.checked); loopRef.current = e.target.checked; }} />循环当前句</label>
      </div>
      <label className="scene-jump">跳到句子 <select aria-label="跳到句子" value={lineIndex} onChange={e => jump(Number(e.target.value))}>{scene.lines.map((item, index) => <option key={item.id} value={index}>第 {index + 1} 句 · {item.speaker}</option>)}</select></label>
      <p className="library-small">{scene.alignment}。复听后暂停，试着自己说一遍；无需录音，不做发音评分。切到后台时单句复听会暂停。</p>
      <button disabled={busy || !finished || failed || recorded} onClick={onRecord}>{recorded ? "已记录完整播放" : "记录完整播放"}</button>
      <p className="library-small">{finished || recorded ? "完整播放只是一条学习记录，不代表已经听懂或掌握。" : "整段自然播放结束后可记录；单句循环不计为完整播放。"}</p>
      <details><summary>展开完整对话</summary>{scene.lines.map((item, index) => <div className="scene-transcript-line" key={item.id}><button aria-label={`复习第 ${index + 1} 句`} onClick={() => jump(index)}>{index + 1} · {item.speaker}</button><p lang="en">{item.text}</p><p>{item.translation}</p></div>)}</details>
    </section>
    <section aria-label="表达拆解" className="scene-animation" tabIndex={0} onKeyDown={e => {
      if (e.target !== e.currentTarget) return;
      if ([" ", "ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) e.preventDefault();
      if (e.key === " ") toggleSteps();
      else if (e.key === "ArrowLeft") moveStep(stepIndex - 1);
      else if (e.key === "ArrowRight") moveStep(stepIndex + 1);
      else if (e.key === "Home") moveStep(0);
      else if (e.key === "End") moveStep(scene.steps.length - 1);
    }}>
      <p className="library-eyebrow">02 · 看懂表达怎么用</p><h2>{step.title}</h2>
      <div className="scene-parts" lang="en" key={step.id}>{step.parts.map((part, i) => <span key={i}>{part}</span>)}</div>
      <p>{step.explanation}</p>
      <div className="scene-controls"><button disabled={stepIndex === 0} onClick={() => moveStep(stepIndex - 1)}>上一步</button><button onClick={toggleSteps}>{animating ? "暂停拆解" : stepIndex === scene.steps.length - 1 ? "重播拆解" : "播放拆解"}</button><button disabled={stepIndex === scene.steps.length - 1} onClick={() => moveStep(stepIndex + 1)}>下一步</button><button onClick={() => moveStep(0)}>回到第一步</button><span>{stepIndex + 1} / {scene.steps.length}</span></div>
      <p className="library-small">聚焦此区域后，空格播放或暂停，左右键切换，Home / End 跳到首尾。</p>
    </section>
  </div>;
}
