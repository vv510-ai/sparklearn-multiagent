"use client";

import { FormEvent, useRef, useState } from "react";
import { LoaderCircle, Send } from "lucide-react";

const QUICK_ACTIONS = [
  {
    label: "换种说法",
    question: "请把刚才听到的核心概念换成更简单、更口语化的说法，先讲结论，再给一个最小解释。",
    resumeAfterAnswer: true,
  },
  {
    label: "举个例子",
    question: "请针对刚才听到的内容举一个贴近日常或编程实践的最小例子，并说明例子和概念如何对应。",
    resumeAfterAnswer: true,
  },
  {
    label: "考考我",
    question: "请只针对刚才听到的内容出一道基础检查题，先不要给答案，等我回答后再判断我的理解。",
    resumeAfterAnswer: false,
  },
] as const;

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60).toString().padStart(2, "0");
  const rest = (whole % 60).toString().padStart(2, "0");
  return `${minutes}:${rest}`;
}

export default function InteractiveAudioPlayer({
  src,
  resourceTitle,
  disabled = false,
  onAsk,
}: {
  src: string;
  resourceTitle: string;
  disabled?: boolean;
  onAsk?: (prompt: string, display: string) => Promise<boolean>;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [status, setStatus] = useState("");

  const ask = async (rawQuestion: string, display: string, resumeAfterAnswer = true) => {
    const clean = rawQuestion.trim();
    if (!clean || !onAsk || disabled || asking) return;

    const audio = audioRef.current;
    const position = audio?.currentTime || 0;
    const shouldResume = Boolean(audio && !audio.paused && !audio.ended);
    audio?.pause();
    setAsking(true);
    setStatus("学伴正在根据当前资料回答，音频已暂停…");

    const prompt = [
      `我正在听来源约束的学习资料《${resourceTitle}》，在 ${formatClock(position)} 处暂停。`,
      `我的请求：${clean}`,
      "请只围绕当前学习主题和已选择的资料回答；如果资料不足，请明确说明，不要补写资料外事实。先解决当前卡点，回答尽量简洁。",
    ].join("\n");

    try {
      const completed = await onAsk(prompt, display);
      if (!completed) {
        setStatus("回答未完成，音频保持暂停。可以重试，或手动继续播放。");
        return;
      }
      setQuestion("");
      if (!resumeAfterAnswer) {
        setStatus("问题已生成，音频保持暂停。先在对话里作答，再继续播放。");
        return;
      }
      if (shouldResume && audio) {
        try {
          await audio.play();
          setStatus("回答完成，已从暂停位置继续播放。");
        } catch {
          setStatus("回答完成，请点击播放键从暂停位置继续。");
        }
      } else {
        setStatus("回答完成，可以从当前进度继续播放。");
      }
    } catch {
      setStatus("回答未完成，音频保持暂停。可以重试，或手动继续播放。");
    } finally {
      setAsking(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void ask(question, question);
  };

  return (
    <div className="mt-2 space-y-2.5">
      <audio
        ref={audioRef}
        src={src}
        controls
        preload="metadata"
        aria-label={`${resourceTitle} 音频讲解`}
        className="h-9 w-full"
      />

      {onAsk && (
        <div className="rounded-[10px] border border-emerald-200 bg-white/80 p-2.5" aria-busy={asking}>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action.label}
                type="button"
                disabled={disabled || asking}
                onClick={() => void ask(action.question, action.label, action.resumeAfterAnswer)}
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
              aria-label="播放中向学伴提问"
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

          {status && (
            <p className="mt-2 text-[11px] leading-4 text-[#68746C]" aria-live="polite">
              {status}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
