"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { LoaderCircle, Pause, Play, RefreshCw, RotateCcw, Send, Volume2 } from "lucide-react";

const QUICK_ACTIONS = [
  {
    action: "rephrase",
    label: "换种说法",
    question: "请把刚才听到的核心概念换成更简单、更口语化的说法，先讲结论，再给一个最小解释。",
    resumeAfterAnswer: true,
  },
  {
    action: "example",
    label: "举个例子",
    question: "请针对刚才听到的内容举一个贴近日常或编程实践的最小例子，并说明例子和概念如何对应。",
    resumeAfterAnswer: true,
  },
  {
    action: "quiz",
    label: "考考我",
    question: "请只针对刚才听到的内容出一道基础检查题，先不要给答案，等我回答后再判断我的理解。",
    resumeAfterAnswer: false,
  },
] as const;

interface AudioState {
  status?: string;
  provider?: string;
  error?: string;
  retryable?: boolean;
  strict_voice?: boolean;
}

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60).toString().padStart(2, "0");
  const rest = (whole % 60).toString().padStart(2, "0");
  return `${minutes}:${rest}`;
}

export default function InteractiveAudioPlayer({
  src,
  narration = "",
  audioState,
  resourceTitle,
  disabled = false,
  onAsk,
  onRetry,
}: {
  src?: string;
  narration?: string;
  audioState?: AudioState;
  resourceTitle: string;
  disabled?: boolean;
  onAsk?: (prompt: string, display: string, action: "rephrase" | "example" | "quiz" | "question") => Promise<boolean>;
  onRetry?: () => Promise<boolean>;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [audioLoadFailed, setAudioLoadFailed] = useState(false);
  const [speechState, setSpeechState] = useState<"idle" | "playing" | "paused">("idle");
  const [status, setStatus] = useState("");
  const useCloudAudio = Boolean(src && !audioLoadFailed);
  const strictSuperVoice = Boolean(
    audioState?.strict_voice
      || (audioState?.provider === "spark_super_tts" && !src),
  );
  const canUseBrowserSpeech = Boolean(narration.trim()) && !strictSuperVoice;

  useEffect(() => {
    setAudioLoadFailed(false);
  }, [src]);

  useEffect(() => () => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }, []);

  useEffect(() => {
    if (useCloudAudio && typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      setSpeechState("idle");
    }
  }, [useCloudAudio]);

  function startBrowserSpeech(restart = false) {
    if (disabled || !canUseBrowserSpeech || typeof window === "undefined" || !("speechSynthesis" in window)) {
      setStatus("当前浏览器不支持朗读，请重试生成云端语音。");
      return;
    }
    const synth = window.speechSynthesis;
    if (!restart && speechState === "paused") {
      synth.resume();
      setSpeechState("playing");
      return;
    }
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(narration);
    const voices = synth.getVoices();
    utterance.voice = voices.find((voice) => voice.lang.toLowerCase().startsWith("zh")) || null;
    utterance.lang = "zh-CN";
    utterance.rate = 0.88;
    utterance.pitch = 1;
    utterance.onstart = () => setSpeechState("playing");
    utterance.onpause = () => setSpeechState("paused");
    utterance.onresume = () => setSpeechState("playing");
    utterance.onend = () => setSpeechState("idle");
    utterance.onerror = () => {
      setSpeechState("idle");
      setStatus("浏览器朗读中断，可以重新播放或重试云端语音。");
    };
    utteranceRef.current = utterance;
    synth.speak(utterance);
  }

  function pauseBrowserSpeech() {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.pause();
      setSpeechState("paused");
    }
  }

  const ask = async (
    rawQuestion: string,
    display: string,
    resumeAfterAnswer = true,
    action: "rephrase" | "example" | "quiz" | "question" = "question",
  ) => {
    const clean = rawQuestion.trim();
    if (!clean || !onAsk || disabled || asking) return;

    const audio = audioRef.current;
    const cloudWasPlaying = Boolean(useCloudAudio && audio && !audio.paused && !audio.ended);
    const browserWasPlaying = !useCloudAudio && speechState === "playing";
    const positionLabel = useCloudAudio ? `${formatClock(audio?.currentTime || 0)} 处` : "浏览器朗读过程中";
    if (cloudWasPlaying) audio?.pause();
    if (browserWasPlaying) pauseBrowserSpeech();
    setAsking(true);
    setStatus("小知正在根据当前资料回答，讲解已暂停…");

    const prompt = [
      `我正在听来源约束的学习资料《${resourceTitle}》，在${positionLabel}暂停。`,
      `我的请求：${clean}`,
      "请只围绕当前学习主题和已选择的资料回答；如果资料不足，请明确说明，不要补写资料外事实。先解决当前卡点，回答尽量简洁。",
    ].join("\n");

    try {
      const completed = await onAsk(prompt, display, action);
      if (!completed) {
        setStatus("回答未完成，讲解保持暂停。可以重试，或手动继续播放。");
        return;
      }
      setQuestion("");
      if (!resumeAfterAnswer) {
        setStatus("问题已生成，讲解保持暂停。先在对话里作答，再继续播放。");
        return;
      }
      if (cloudWasPlaying && audio) {
        try {
          await audio.play();
          setStatus("回答完成，已从暂停位置继续播放。");
        } catch {
          setStatus("回答完成，请点击播放键从暂停位置继续。");
        }
      } else if (browserWasPlaying && typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.resume();
        setSpeechState("playing");
        setStatus("回答完成，浏览器朗读已继续。");
      } else {
        setStatus("回答完成，可以继续播放讲解。");
      }
    } catch {
      setStatus("回答未完成，讲解保持暂停。可以重试，或手动继续播放。");
    } finally {
      setAsking(false);
    }
  };

  async function retryCloudAudio() {
    if (!onRetry || retrying) return;
    setRetrying(true);
    setStatus("正在重新生成云端语音…");
    try {
      const ready = await onRetry();
      setStatus(ready ? "云端语音已生成，可以直接播放。" : "云端语音仍不可用，已保留浏览器朗读。");
    } catch {
      setStatus("云端语音重试失败，已保留浏览器朗读。");
    } finally {
      setRetrying(false);
    }
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void ask(question, question, true, "question");
  };

  return (
    <div className="mt-2 space-y-2.5">
      {useCloudAudio ? (
        <audio
          ref={audioRef}
          src={src}
          controls
          preload="metadata"
          onError={() => {
            setAudioLoadFailed(true);
            setStatus("云端音频文件无法加载，已切换到浏览器朗读。");
          }}
          aria-label={`${resourceTitle} 音频讲解`}
          className="h-9 w-full"
        />
      ) : strictSuperVoice ? (
        <div className="rounded-[10px] border border-emerald-200 bg-emerald-50/70 p-3">
          <div className="flex items-center gap-2 text-xs font-bold text-emerald-900">
            <Volume2 size={15} /> 已锁定星火超拟人音色
          </div>
          <p className="mt-2 text-[11px] leading-5 text-emerald-800">
            当前云端没有返回有效音频。为避免播放成普通星火或设备自带音色，系统已暂停朗读；可稍后点击“重新生成云端语音”。
          </p>
          {audioState?.error && (
            <p className="mt-1 text-[10px] text-emerald-700">
              云端状态：{audioState.error}
            </p>
          )}
        </div>
      ) : canUseBrowserSpeech ? (
        <div className="rounded-[10px] border border-amber-200 bg-amber-50/70 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-amber-900">
              <Volume2 size={15} /> 浏览器中文朗读
            </div>
            <div className="flex items-center gap-1.5">
              {speechState === "playing" ? (
                <button type="button" onClick={pauseBrowserSpeech} disabled={disabled} className="rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-bold text-amber-900 disabled:opacity-50">
                  <Pause size={13} className="mr-1 inline" />暂停
                </button>
              ) : (
                <button type="button" onClick={() => startBrowserSpeech()} disabled={disabled} className="rounded-md bg-amber-600 px-2.5 py-1.5 text-xs font-bold text-white disabled:opacity-50">
                  <Play size={13} className="mr-1 inline" />{speechState === "paused" ? "继续" : "播放"}
                </button>
              )}
              <button type="button" onClick={() => startBrowserSpeech(true)} disabled={disabled} className="rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-bold text-amber-900 disabled:opacity-50">
                <RotateCcw size={13} className="mr-1 inline" />重播
              </button>
            </div>
          </div>
          <p className="mt-2 text-[11px] leading-4 text-amber-800">
            云端 TTS 暂时不可用，当前使用设备自带中文语音；学习内容仍来自同一份资料。
          </p>
          {audioState?.error && <p className="mt-1 text-[10px] text-amber-700">云端原因：{audioState.error}</p>}
        </div>
      ) : (
        <p className="rounded-[10px] border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          当前没有可朗读内容，请重新生成互动讲解。
        </p>
      )}

      {onRetry && (!useCloudAudio || audioLoadFailed || audioState?.retryable) && (
        <button
          type="button"
          onClick={() => void retryCloudAudio()}
          disabled={disabled || retrying}
          className="inline-flex items-center rounded-md border border-emerald-300 bg-white px-3 py-1.5 text-xs font-bold text-emerald-800 transition hover:bg-emerald-50 disabled:opacity-50"
        >
          {retrying ? <LoaderCircle size={13} className="mr-1 animate-spin" /> : <RefreshCw size={13} className="mr-1" />}
          重新生成云端语音
        </button>
      )}

      {onAsk && (
        <div className="rounded-[10px] border border-emerald-200 bg-white/80 p-2.5" aria-busy={asking}>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action.label}
                type="button"
                disabled={disabled || asking}
                onClick={() => void ask(action.question, action.label, action.resumeAfterAnswer, action.action)}
                className="rounded-full border border-[#D7DED8] bg-[#F7F9F7] px-2.5 py-1 text-[11px] font-bold text-[#425248] transition hover:border-emerald-300 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {action.label}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="flex items-center gap-2">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={disabled || asking}
              aria-label="播放中向小知提问"
              placeholder="没听懂？暂停并问一句…"
              className="min-w-0 flex-1 rounded-[8px] border border-[#DCE2DD] bg-white px-3 py-2 text-xs text-[#182119] outline-none transition placeholder:text-[#9AA0AD] focus:border-emerald-400"
            />
            <button
              type="submit"
              disabled={!question.trim() || disabled || asking}
              aria-label="发送播放中的问题"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#0F6B50] text-white transition hover:bg-[#0B5A42] disabled:cursor-not-allowed disabled:bg-[#C9D3CD]"
            >
              {asking ? <LoaderCircle size={15} className="animate-spin" /> : <Send size={14} />}
            </button>
          </form>

        </div>
      )}
      {status && <p className="text-[11px] leading-4 text-[#68746C]" aria-live="polite">{status}</p>}
    </div>
  );
}
