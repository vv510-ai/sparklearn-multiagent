"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, BookPlus, FileUp, Gauge, LoaderCircle, MessageSquarePlus, Mic, NotebookPen, Plus, Route, Square } from "lucide-react";
import { USER_ID, apiUpload, postSSE } from "@/lib/api";
import type { ResourceItem, SparkEvent } from "@/lib/types";
import InlineConceptAnimation from "./InlineConceptAnimation";
import Markdown from "./Markdown";
import ResourceCard from "@/components/resource/ResourceCard";

interface Msg {
  role: "user" | "assistant";
  text: string;
  resources: ResourceItem[];
  citations: string[];
  streaming?: boolean;
}

interface VoiceRecorder {
  stream: MediaStream;
  context: AudioContext;
  source: MediaStreamAudioSourceNode;
  processor: ScriptProcessorNode;
  chunks: Float32Array[];
  sampleRate: number;
  startedAt: number;
  timeoutId: number;
}

function disposeRecorder(recorder: VoiceRecorder) {
  window.clearTimeout(recorder.timeoutId);
  recorder.processor.onaudioprocess = null;
  recorder.processor.disconnect();
  recorder.source.disconnect();
  recorder.stream.getTracks().forEach((track) => track.stop());
  void recorder.context.close();
}

function pcm16Blob(chunks: Float32Array[], sourceRate: number, targetRate = 16000): Blob {
  const inputLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const input = new Float32Array(inputLength);
  let offset = 0;
  chunks.forEach((chunk) => {
    input.set(chunk, offset);
    offset += chunk.length;
  });

  const ratio = sourceRate / targetRate;
  const outputLength = Math.max(1, Math.floor(input.length / ratio));
  const buffer = new ArrayBuffer(outputLength * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < outputLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += input[j];
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/pcm" });
}
const STARTERS = [
  "请围绕当前课程，先解释一个最基础的概念",
  "根据我现在的学习起点，给我一道可以独立尝试的新题",
  "请用这门课程的一个例子，帮我区分容易混淆的概念",
  "我今天时间有限，请带我完成计划中的第一小步",
];

const BEGINNER_PRESET =
  "请用完全零基础、由浅入深的方式教我【在这里填写知识点】。先判断我现在需要学习路线还是概念讲解，只回答当下最需要的内容；练习、导图或笔记等我需要时会单独提出。";

const FLOW = [
  ["01", "先判断需求", "路线还是概念"],
  ["02", "只答眼前问题", "不强塞全套"],
  ["03", "需要再展开", "由你决定深度"],
  ["04", "产物按需生成", "导图练习可选"],
];

function isProductOperation(question: string, answer: string): boolean {
  const q = question.replace(/\s+/g, "");
  return (
    /(?:清空|清除|清掉|删掉|删除|重置).*(?:聊天|对话|消息|记录)/.test(q)
    || /(?:看见|看(?:得|的)?到|读取|读到|知道|识别).*(?:资料|文件)/.test(q)
    || answer.includes("当前科目里的聊天记录已经清空")
    || answer.startsWith("能看到。目前这轮对话选中了")
  );
}

export default function Chat({
  onEvent,
  seed,
  request,
  notebookId = "",
  sessionId = "",
  initialMessages = [],
  sourceIds = [],
  topic = "",
  onUploadClick,
  onCreateNotebook,
  onNewConversation,
  onSeedConsumed,
  onLearningTurn,
  onSessionReady,
  onQuizEvaluated,
  onOpenMistakes,
  recommendedTask,
  onOpenPath,
  onOpenAssessment,
}: {
  onEvent?: (ev: SparkEvent) => void;
  /** 外部(首页快捷入口)注入的一次性发送内容 */
  seed?: string;
  request?: { path: string; body: Record<string, unknown>; display: string };
  notebookId?: string;
  sessionId?: string;
  initialMessages?: { role: "user" | "assistant"; content: string }[];
  sourceIds?: string[];
  topic?: string;
  onUploadClick?: () => void;
  onCreateNotebook?: () => void;
  onNewConversation?: () => void;
  onSeedConsumed?: () => void;
  onLearningTurn?: (text: string) => void;
  onSessionReady?: (sessionId: string) => void;
  onQuizEvaluated?: (report: { path?: import("@/lib/types").PathPlan; profile_version?: number }) => void;
  onOpenMistakes?: () => void;
  recommendedTask?: { title: string; prompt: string; reason: string };
  onOpenPath?: () => void;
  onOpenAssessment?: () => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>(() => initialMessages.map((message) => ({
    role: message.role,
    text: message.content,
    resources: [],
    citations: [],
  })));
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [queuedHint, setQueuedHint] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [composerMenuOpen, setComposerMenuOpen] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);
  const voiceRecorderRef = useRef<VoiceRecorder | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef(sessionId || `s-${Math.random().toString(36).slice(2, 8)}`);
  const consumedSeedRef = useRef("");
  const consumedRequestRef = useRef("");

  useEffect(() => {
    onSessionReady?.(sessionRef.current);
  }, [onSessionReady]);

  const stopRecording = useCallback(async () => {
    const recorder = voiceRecorderRef.current;
    if (!recorder) return;
    voiceRecorderRef.current = null;
    setRecording(false);
    disposeRecorder(recorder);
    if (performance.now() - recorder.startedAt < 350 || recorder.chunks.length === 0) {
      setVoiceStatus("录音时间太短，请重新说一次。");
      return;
    }

    setTranscribing(true);
    setVoiceStatus("正在将语音转成文字…");
    try {
      const form = new FormData();
      form.set("user_id", USER_ID);
      form.set("encoding", "raw");
      form.set("sample_rate", "16000");
      form.set("file", pcm16Blob(recorder.chunks, recorder.sampleRate), "voice-question.pcm");
      const result = await apiUpload<{ text: string; provider: string; elapsed_ms: number }>(
        "/tutor/transcribe",
        form,
      );
      const text = result.text.trim();
      if (!text) throw new Error("没有识别到有效语音");
      setInput(text);
      setVoiceStatus("已转成文字，可检查后发送。");
    } catch (error) {
      setVoiceStatus(`语音识别失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setTranscribing(false);
    }
  }, []);

  const toggleRecording = useCallback(async () => {
    if (recording) {
      await stopRecording();
      return;
    }
    if (busy || transcribing) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setVoiceStatus("当前浏览器不支持麦克风录音。");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const context = new AudioContext();
      await context.resume();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const chunks: Float32Array[] = [];
      processor.onaudioprocess = (event) => {
        chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(context.destination);
      const recorder: VoiceRecorder = {
        stream,
        context,
        source,
        processor,
        chunks,
        sampleRate: context.sampleRate,
        startedAt: performance.now(),
        timeoutId: 0,
      };
      recorder.timeoutId = window.setTimeout(() => void stopRecording(), 60_000);
      voiceRecorderRef.current = recorder;
      setRecording(true);
      setVoiceStatus("正在录音，再点一次麦克风结束（最长60秒）。");
    } catch (error) {
      setVoiceStatus(`无法使用麦克风：${error instanceof Error ? error.message : String(error)}`);
    }
  }, [busy, recording, stopRecording, transcribing]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs]);

  const send = useCallback(
    (
      text: string,
      directRequest?: { path: string; body: Record<string, unknown>; display: string },
      displayText?: string,
      captureLearningTurn = true,
    ): Promise<boolean> => {
      const q = text.trim();
      if (!q) return Promise.resolve(false);
      if (busy) {
        setQueuedHint("当前任务还在整理中。可以先停止，再开始新的任务。");
        return Promise.resolve(false);
      }
      setQueuedHint("");
      setInput("");
      setBusy(true);
      setMsgs((m) => [
        ...m,
        { role: "user", text: displayText?.trim() || q, resources: [], citations: [] },
        { role: "assistant", text: "", resources: [], citations: [], streaming: true },
      ]);

      const patchLast = (fn: (a: Msg) => Msg) =>
        setMsgs((m) => {
          const out = [...m];
          out[out.length - 1] = fn(out[out.length - 1]);
          return out;
        });

      return new Promise<boolean>((resolve) => {
        let settled = false;
        const finish = (completed: boolean) => {
          if (settled) return;
          settled = true;
          abortRef.current = null;
          resolve(completed);
        };

        abortRef.current = postSSE(
          directRequest?.path || "/chat",
          directRequest?.body || {
            user_id: USER_ID,
            session_id: sessionRef.current,
            notebook_id: notebookId,
            message: q,
            topic_label: topic,
            source_ids: sourceIds,
            display_message: displayText?.trim() || q,
          },
          (ev) => {
            onEvent?.(ev);
            switch (ev.type) {
              case "token":
                patchLast((a) => ({ ...a, text: a.text + (ev.delta || "") }));
                break;
              case "resource":
                if (ev.resource) patchLast((a) => ({ ...a, resources: [...a.resources, ev.resource!] }));
                break;
              case "citations":
                if (ev.items?.length && (!directRequest || directRequest.path === "/chat")) {
                  patchLast((a) => ({ ...a, citations: Array.from(new Set([...a.citations, ...ev.items!])) }));
                }
                break;
              case "summary":
                patchLast((a) => ({ ...a, text: a.text || (ev.text as string) || "" }));
                break;
              case "progress":
                if (captureLearningTurn && ev.stage === "learning_focus" && ev.text?.trim()) {
                  onLearningTurn?.(ev.text.trim());
                }
                break;
              case "conversation_cleared":
                setMsgs([{
                  role: "assistant",
                  text: ev.text || "当前科目里的聊天记录已经清空。",
                  resources: [],
                  citations: [],
                  streaming: false,
                }]);
                break;
              case "error":
                patchLast((a) => ({ ...a, text: a.text + `\n\n> 服务异常:${ev.detail || "请稍后重试"}`, streaming: false }));
                setBusy(false);
                finish(false);
                break;
              case "done":
                patchLast((a) => ({ ...a, streaming: false }));
                setBusy(false);
                finish(true);
                break;
            }
          },
          () => {
            setBusy(false);
            patchLast((a) => ({ ...a, streaming: false }));
            finish(false);
          },
        );
      });
    },
    [busy, notebookId, onEvent, onLearningTurn, sourceIds, topic],
  );

  useEffect(() => {
    const key = seed?.trim() || "";
    if (!key) consumedSeedRef.current = "";
    if (!key || busy || consumedSeedRef.current === key) return;
    const timer = window.setTimeout(() => {
      if (consumedSeedRef.current === key) return;
      consumedSeedRef.current = key;
      send(seed!);
      onSeedConsumed?.();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [busy, onSeedConsumed, seed, send]);

  useEffect(() => {
    const key = request ? `${request.path}:${request.display}` : "";
    if (!key) consumedRequestRef.current = "";
    if (!request || busy || consumedRequestRef.current === key) return;
    const timer = window.setTimeout(() => {
      if (consumedRequestRef.current === key) return;
      consumedRequestRef.current = key;
      send(request.display, request, undefined, false);
      onSeedConsumed?.();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [busy, onSeedConsumed, request, send]);

  useEffect(() => {
    return () => {
      abortRef.current?.();
      const recorder = voiceRecorderRef.current;
      if (recorder) disposeRecorder(recorder);
    };
  }, []);

  return (
    <div className="notebook-chat-shell flex h-full min-h-0 flex-col overflow-hidden">
      <div className="notebook-chat-header border-b border-[#E1E4EC] px-5 py-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold tracking-[0.18em] text-[#737B8B]">LEARNING CONVERSATION</div>
            <h2 className="mt-0.5 text-lg font-bold leading-tight tracking-tight text-[#182119]">
              学习对话
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {onNewConversation && (
              <button
                type="button"
                onClick={onNewConversation}
                disabled={busy}
                className="notebook-soft-control inline-flex items-center gap-1.5 rounded-full border border-[#DDE3ED] px-3 py-1.5 text-xs font-bold text-[#4E5665] transition hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
                title="保留当前书本和资料，打开一页干净的新对话"
              >
                <MessageSquarePlus size={14} />
                新对话
              </button>
            )}
            {msgs.length > 0 && (
              <button
                type="button"
                onClick={() => send("请把本次学习对话整理成一份可复习、可继续使用的个人笔记。", undefined, undefined, false)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-800 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <NotebookPen size={14} />
                整理本次笔记
              </button>
            )}
            <div className="notebook-soft-control rounded-full border border-[#DDE3ED] px-3 py-1.5 text-xs font-medium text-[#596171]">
              {sourceIds.length ? `${sourceIds.length} 份已选资料` : "当前课程 · 尚未选择上传资料"}
            </div>
          </div>
        </div>
      </div>

      <div className="notebook-chat-scroll flex-1 space-y-4 overflow-y-auto p-5">
        {msgs.length === 0 && (
          <div className="mx-auto max-w-3xl space-y-5 pt-8">
            <div className="text-center">
              <div className="mx-auto grid h-12 w-12 place-items-center rounded-[12px] bg-[#EEF0FA] text-2xl">📘</div>
              <h3 className="mt-4 text-2xl font-semibold tracking-tight text-[#1D2028]">从一个问题开始</h3>
              <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-[#737B8B]">先判断你要学习路线还是具体讲解，只回答当前问题；导图、练习和笔记都按需生成。</p>
            </div>
            {recommendedTask && (
              <div className="rounded-[16px] border border-[#B9D9C5] bg-[#EDF7F0] p-4 shadow-[0_1px_2px_rgba(18,30,22,0.04),0_10px_24px_rgba(18,30,22,0.06)]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-[10px] font-bold tracking-[0.16em] text-[#176C6B]">根据你的学习画像</div>
                    <h3 className="mt-1 text-lg font-bold text-[#182119]">第一步：{recommendedTask.title}</h3>
                    <p className="mt-1 text-xs leading-5 text-[#5D7062]">{recommendedTask.reason}</p>
                  </div>
                  {onOpenPath && <button type="button" onClick={onOpenPath} className="inline-flex min-h-10 items-center gap-1 rounded-lg border border-[#B9D9C5] bg-white px-3 text-xs font-bold text-[#176C6B] transition hover:bg-[#F5FBF7]"><Route size={14} /> 查看路径</button>}
                </div>
                <button type="button" onClick={() => void send(recommendedTask.prompt)} className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#176C6B] px-4 text-sm font-bold text-white transition hover:bg-[#125856]"><BookPlus size={16} /> 开始第一项任务 <ArrowRight size={15} /></button>
              </div>
            )}
            <div className="grid gap-2 sm:grid-cols-3">
              <button type="button" onClick={() => void send(recommendedTask?.prompt || `请根据“${topic || "当前课程"}”的学习目标与已选资料，带我了解学习路线，再给我第一道小题；没有教材时请说明。`)} className="flex min-h-12 items-center gap-2 rounded-xl border border-[#DDE5DE] bg-white px-3 text-left text-xs font-semibold text-[#3F4E43] transition hover:border-[#A8C6B3] hover:bg-[#F4F8F4]"><BookPlus size={15} className="shrink-0 text-[#176C6B]" /> 从当前课程开始</button>
              {onOpenAssessment && <button type="button" onClick={onOpenAssessment} className="flex min-h-12 items-center gap-2 rounded-xl border border-[#DDE5DE] bg-white px-3 text-left text-xs font-semibold text-[#3F4E43] transition hover:border-[#A8C6B3] hover:bg-[#F4F8F4]"><Gauge size={15} className="shrink-0 text-[#176C6B]" /> 先测一下我的水平</button>}
              <button type="button" onClick={onUploadClick} className="flex min-h-12 items-center gap-2 rounded-xl border border-[#DDE5DE] bg-white px-3 text-left text-xs font-semibold text-[#3F4E43] transition hover:border-[#A8C6B3] hover:bg-[#F4F8F4]"><FileUp size={15} className="shrink-0 text-[#176C6B]" /> 上传自己的资料</button>
            </div>
            <button
              type="button"
              onClick={() => setInput(BEGINNER_PRESET)}
              className="notebook-beginner-preset w-full rounded-[14px] border border-emerald-200 p-4 text-left transition hover:border-emerald-300 hover:bg-[#EDF6F1]"
            >
              <span className="font-mono text-[10px] font-bold tracking-[0.18em] text-emerald-700">零基础学习预设 · 点击填入</span>
              <span className="mt-2 block text-sm leading-6 text-[#425248]">{BEGINNER_PRESET}</span>
            </button>
            <div className="notebook-flow-card rounded-[12px] border border-[#E1E4EC] p-3">
              <div className="mb-2 text-xs font-bold text-emerald-800">
                一次完整学习会这样推进
              </div>
              <div className="grid gap-2 sm:grid-cols-4">
                {FLOW.map(([code, title, desc]) => (
                  <div key={code} className="notebook-flow-step rounded-[10px] border border-[#E5E9E3] px-3 py-2">
                    <div className="font-mono text-[10px] font-bold tracking-[0.18em] text-emerald-700">{code}</div>
                    <div className="mt-1 text-xs font-bold text-[#182119]">{title}</div>
                    <div className="mt-0.5 text-[11px] leading-4 text-[#8B958D]">{desc}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 text-xs font-bold text-[#8B958D]">可以从一个示例目标开始</div>
              <div className="grid gap-3 sm:grid-cols-2">
                {STARTERS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="notebook-starter-card rounded-[14px] border border-[#E5E9E3] p-4 text-left text-sm text-[#57635A] shadow-sm transition hover:-translate-y-0.5 hover:border-[#D2DAD2] hover:shadow-[0_1px_2px_rgba(18,30,22,0.05),0_6px_20px_rgba(18,30,22,0.08)]"
                  >
                    <span className="mb-2 block font-mono text-[10px] tracking-[0.2em] text-emerald-700">学习目标</span>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[82%] rounded-[14px] rounded-br-md bg-[#0E1411] px-4 py-2.5 text-sm leading-6 text-white shadow-sm">
                {m.text}
              </div>
            </div>
          ) : (
            <div key={i} className="flex gap-3">
              <div className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-[10px] border border-emerald-200 bg-[#E3F0E9] font-mono text-[10px] font-bold text-emerald-800">
                学伴
              </div>
              <div className="min-w-0 flex-1 space-y-3">
                {(m.text || m.streaming) && (
                  <div
                    className="notebook-assistant-message rounded-[14px] rounded-tl-md border border-[#E5E9E3] px-4 py-3 shadow-sm"
                    aria-label="学伴回答"
                    aria-live={m.streaming ? "polite" : "off"}
                  >
                    <Markdown text={m.text} streaming={m.streaming} citeBase={`chat-${i}`} citations={m.citations} />
                  </div>
                )}
                {!m.streaming && m.text && !isProductOperation(
                  [...msgs.slice(0, i)].reverse().find((item) => item.role === "user")?.text || "",
                  m.text,
                ) && (
                  <InlineConceptAnimation
                    question={[...msgs.slice(0, i)].reverse().find((item) => item.role === "user")?.text || topic}
                    text={m.text}
                  />
                )}
                {m.resources.map((r) => (
                  <ResourceCard
                    key={r.id}
                    r={r}
                    onQuizEvaluated={onQuizEvaluated}
                    interactionBusy={busy}
                    onAudioQuestion={(prompt, display, action) => send(
                      prompt,
                      {
                        path: "/chat",
                        display,
                        body: {
                          user_id: USER_ID,
                          session_id: sessionRef.current,
                          notebook_id: notebookId,
                          message: prompt,
                          display_message: display,
                          topic_label: topic,
                          source_ids: sourceIds,
                          resource_id: r.id,
                          interaction_action: action,
                        },
                      },
                      display,
                      false,
                    )}
                    onOpenMistakes={onOpenMistakes}
                  />
                ))}
              </div>
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <div className="notebook-chat-footer border-t border-[#E1E4EC] p-4">
        <div className="notebook-composer relative flex items-end gap-2">
          {composerMenuOpen && (
            <div className="notebook-composer-menu absolute bottom-14 left-0 z-20 w-60 overflow-hidden rounded-2xl border border-[#DDE2DA] p-2 shadow-[0_18px_55px_rgba(20,35,27,0.18)]">
              {onNewConversation && (
                <button type="button" onClick={() => { setComposerMenuOpen(false); onNewConversation(); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition hover:bg-emerald-50">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-emerald-100 text-emerald-700"><MessageSquarePlus size={18} /></span>
                  <span><strong className="block text-sm text-slate-900">新开一页对话</strong><small className="mt-0.5 block text-[11px] text-slate-500">保留本书资料，清空当前聊天</small></span>
                </button>
              )}
              <button type="button" onClick={() => { setComposerMenuOpen(false); onCreateNotebook?.(); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition hover:bg-emerald-50">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-emerald-100 text-emerald-700"><BookPlus size={18} /></span>
                <span><strong className="block text-sm text-slate-900">新建知识书本</strong><small className="mt-0.5 block text-[11px] text-slate-500">开始一段独立的学习对话</small></span>
              </button>
              <button type="button" onClick={() => { setComposerMenuOpen(false); onUploadClick?.(); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition hover:bg-slate-50">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-sky-100 text-sky-700"><FileUp size={18} /></span>
                <span><strong className="block text-sm text-slate-900">添加学习资料</strong><small className="mt-0.5 block text-[11px] text-slate-500">PDF、图片、Markdown 或文本</small></span>
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => setComposerMenuOpen((open) => !open)}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#596171] transition hover:bg-[#EEF0F6] hover:text-[#1D2028]"
            aria-label="新建知识书本或添加资料"
            aria-expanded={composerMenuOpen}
            title="新建知识书本或添加资料"
          >
            <Plus size={20} className={`transition ${composerMenuOpen ? "rotate-45" : ""}`} />
          </button>
          <button
            type="button"
            onClick={() => void toggleRecording()}
            disabled={busy || transcribing}
            className={`grid h-10 w-10 shrink-0 place-items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50 ${
              recording
                ? "bg-red-50 text-red-600 ring-2 ring-red-200"
                : "text-[#596171] hover:bg-[#EEF0F6] hover:text-emerald-700"
            }`}
            aria-label={recording ? "停止录音并识别" : "语音提问"}
            title={recording ? "停止录音并识别" : "语音输入"}
          >
            {transcribing ? <LoaderCircle size={19} className="animate-spin" /> : <Mic size={19} />}
          </button>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            aria-label="学习目标输入"
            placeholder="你今天想学什么知识？"
            className="max-h-28 flex-1 resize-none border-0 bg-transparent px-1 py-2.5 text-sm text-[#182119] outline-none placeholder:text-[#9AA0AD]"
          />
          {busy ? (
            <button
              onClick={() => abortRef.current?.()}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#F4ECEA] text-[#A33A25] transition hover:bg-[#EEDDD8]"
              aria-label="停止生成"
            >
              <Square size={15} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={() => send(input)}
              disabled={!input.trim()}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#14161B] text-white transition hover:scale-[1.03] disabled:cursor-not-allowed disabled:bg-[#E1E3E8] disabled:text-[#9AA0AD]"
              aria-label="发送"
            >
              <ArrowRight size={19} />
            </button>
          )}
        </div>
        {queuedHint && <div className="mt-2 text-xs font-semibold text-orange-700">{queuedHint}</div>}
        {voiceStatus && (
          <div className={`mt-2 text-xs font-semibold ${recording ? "text-red-600" : "text-emerald-700"}`}>
            {voiceStatus}
          </div>
        )}
      </div>
    </div>
  );
}
