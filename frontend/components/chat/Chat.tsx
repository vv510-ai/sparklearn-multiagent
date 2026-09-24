"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUp, BookOpen, BookPlus, Check, ChevronDown, Copy, FileText, FileUp, Gauge, LoaderCircle, Maximize2, Mic, NotebookPen, PanelRightOpen, Play, Plus, Route, Square } from "lucide-react";
import { USER_ID, apiPost, apiUpload, postSSE } from "@/lib/api";
import type { ResourceItem, SparkEvent, SourceEvidence as Evidence } from "@/lib/types";
import AnswerChoices from "./AnswerChoices";
import Markdown from "./Markdown";
import SourceEvidence from "./SourceEvidence";
import ResourceCard from "@/components/resource/ResourceCard";
import StudySuggestion from "./StudySuggestion";
import StudyDialog from "@/components/ui/StudyDialog";
import AdaptiveMenu from "@/components/ui/AdaptiveMenu";
import { readStudyDraft, writeStudyDraft } from "@/lib/study-workspace";
import { dismissGuidance, emptyGuidance, readGuidance, recordLearningTurn, studyStage, type LearningGuidance, type StudyStage, type SuggestedTool } from "@/lib/learning-guidance";

interface Msg {
  role: "user" | "assistant";
  text: string;
  resources: ResourceItem[];
  citations: string[];
  evidence?: Evidence[];
  streaming?: boolean;
  progress?: string;
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
const BEGINNER_PRESET =
  "请用完全零基础、由浅入深的方式教我【在这里填写知识点】。先判断我现在需要学习路线还是概念讲解，只回答当下最需要的内容；练习、导图或笔记等我需要时会单独提出。";

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
  sourcePolicy = "auto",
  onSourcePolicyChange,
  topic = "",
  onUploadClick,
  onCreateNotebook,
  onSeedConsumed,
  onLearningTurn,
  onSessionReady,
  onQuizEvaluated,
  onOpenMistakes,
  recommendedTask,
  onOpenPath,
  onOpenAssessment,
  learnerId = "",
  onStudyStage,
  onSuggestedTool,
  sourceLabel = "已选资料",
  onOpenSources,
  onOpenStudio,
  onBusyChange,
}: {
  onEvent?: (ev: SparkEvent) => void;
  /** 外部(首页快捷入口)注入的一次性发送内容 */
  seed?: string;
  request?: { path: string; body: Record<string, unknown>; display: string };
  notebookId?: string;
  sessionId?: string;
  initialMessages?: { role: "user" | "assistant"; content: string; source_evidence?: Evidence[] }[];
  sourceIds?: string[];
  sourcePolicy?: "auto" | "strict" | "supplement";
  onSourcePolicyChange?: (value: "auto" | "strict" | "supplement") => void;
  topic?: string;
  onUploadClick?: () => void;
  onCreateNotebook?: () => void;
  onSeedConsumed?: () => void;
  onLearningTurn?: (text: string) => void;
  onSessionReady?: (sessionId: string) => void;
  onQuizEvaluated?: (report: { path?: import("@/lib/types").PathPlan; profile_version?: number }) => void;
  onOpenMistakes?: () => void;
  recommendedTask?: { title: string; prompt: string; reason: string };
  onOpenPath?: () => void;
  onOpenAssessment?: () => void;
  learnerId?: string;
  onStudyStage?: (stage: StudyStage) => void;
  onSuggestedTool?: (tool: SuggestedTool) => void;
  sourceLabel?: string;
  onOpenSources?: () => void;
  onOpenStudio?: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>(() => initialMessages.map((message) => ({
    role: message.role,
    text: message.content,
    evidence: message.source_evidence || [],
    resources: [],
    citations: [],
  })));
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [queuedHint, setQueuedHint] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [copiedMessage, setCopiedMessage] = useState<number | null>(null);
  const [copyError, setCopyError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [restoredDraft, setRestoredDraft] = useState("");
  const draftKey = `learnloop:chat-draft:${learnerId}:${notebookId || "welcome"}:${notebookId ? sessionId : "new"}`;
  const abortRef = useRef<(() => void) | null>(null);
  const voiceRecorderRef = useRef<VoiceRecorder | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef(sessionId || `s-${Math.random().toString(36).slice(2, 8)}`);
  const consumedSeedRef = useRef("");
  const consumedRequestRef = useRef("");
  const [guidance, setGuidance] = useState<LearningGuidance>(emptyGuidance);
  const guidanceRef = useRef(guidance);
  const mountedRef = useRef(true);
  const guidanceKey = `learnloop-guidance-v1:${learnerId}:${notebookId}:${sessionRef.current}`;
  const updateGuidance = useCallback((update: (current: LearningGuidance) => LearningGuidance) => {
    if (!mountedRef.current) return;
    const next = update(guidanceRef.current);
    guidanceRef.current = next;
    setGuidance(next);
    try { sessionStorage.setItem(guidanceKey, JSON.stringify(next)); } catch { /* Discovery works without browser storage. */ }
  }, [guidanceKey]);
  useEffect(() => {
    mountedRef.current = true;
    let restored = emptyGuidance();
    try { restored = readGuidance(sessionStorage.getItem(guidanceKey)); } catch { /* Optional storage. */ }
    guidanceRef.current = restored;
    setGuidance(restored);
    return () => { mountedRef.current = false; };
  }, [guidanceKey]);
  useEffect(() => { onStudyStage?.(studyStage(guidance)); }, [guidance, onStudyStage]);
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);

  useEffect(() => {
    setInput(readStudyDraft(draftKey, (value): value is string => typeof value === "string") || "");
    setRestoredDraft(draftKey);
  }, [draftKey]);
  useEffect(() => {
    if (learnerId && restoredDraft === draftKey) writeStudyDraft(draftKey, input);
  }, [draftKey, input, learnerId, restoredDraft]);
  useEffect(() => {
    const resize = () => {
      const element = inputRef.current;
      if (!element) return;
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, Math.max(56, Math.min(160, (window.visualViewport?.height || innerHeight) * 0.3)))}px`;
    };
    resize();
    window.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("resize", resize);
    };
  }, [input, expanded]);

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
    if (msgs.length) bottomRef.current?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "end" });
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
      // Continuing the conversation is also a choice to defer the current card.
      updateGuidance(current => current.pending ? dismissGuidance(current) : current);
      setInput("");
      setBusy(true);
      setMsgs((m) => [
        ...m,
        { role: "user", text: displayText?.trim() || q, resources: [], citations: [] },
        { role: "assistant", text: "", resources: [], citations: [], streaming: true,
          progress: directRequest ? "正在准备本次学习内容…" : "正在理解你的问题…" },
      ]);

      const patchLast = (fn: (a: Msg) => Msg) =>
        setMsgs((m) => {
          const out = [...m];
          out[out.length - 1] = fn(out[out.length - 1]);
          return out;
        });

      return new Promise<boolean>((resolve) => {
        let settled = false;
        let teachingFocus = false;
        let answer = "";
        let generatedResource = false;
        const finish = (completed: boolean) => {
          if (settled) return;
          settled = true;
          abortRef.current = null;
          if (!completed && !directRequest && mountedRef.current) setInput(current => current || q);
          if (completed && captureLearningTurn && !directRequest && teachingFocus && !generatedResource
            && answer.trim().length >= 80 && !isProductOperation(q, answer)) {
            updateGuidance(current => recordLearningTurn(current, q));
          }
          resolve(completed);
        };

        abortRef.current = postSSE(
          directRequest?.path || "/chat",
          directRequest ? { source_policy: sourcePolicy, ...directRequest.body } : {
            user_id: USER_ID,
            session_id: sessionRef.current,
            notebook_id: notebookId,
            message: q,
            topic_label: topic,
            source_ids: sourceIds,
            source_policy: sourcePolicy,
            display_message: displayText?.trim() || q,
          },
          (ev) => {
            if (settled || !mountedRef.current) return;
            onEvent?.(ev);
            switch (ev.type) {
              case "token":
                answer += ev.delta || "";
                patchLast((a) => ({ ...a, text: a.text + (ev.delta || "") }));
                break;
              case "resource":
                generatedResource = true;
                if (ev.resource) patchLast((a) => ({ ...a, resources: [...a.resources, ev.resource!] }));
                break;
              case "citations":
                if (ev.agent === "tutor" && ev.evidence) patchLast(a => ({ ...a, evidence: ev.evidence }));
                if (ev.items?.length && (!directRequest || directRequest.path === "/chat")) {
                  patchLast((a) => ({ ...a, citations: Array.from(new Set([...a.citations, ...ev.items!])) }));
                }
                break;
              case "summary":
                answer ||= (ev.text as string) || "";
                patchLast((a) => ({ ...a, text: a.text || (ev.text as string) || "" }));
                break;
              case "progress":
                if (["resource_content", "resource_check", "resource_audio"].includes(ev.stage || "") && ev.text?.trim()) {
                  patchLast((a) => ({ ...a, progress: ev.text!.trim() }));
                }
                if (captureLearningTurn && ev.stage === "learning_focus" && ev.text?.trim()) {
                  teachingFocus = true;
                  onLearningTurn?.(ev.text.trim());
                }
                break;
              case "conversation_cleared":
                teachingFocus = false;
                updateGuidance(() => emptyGuidance());
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
            if (settled || !mountedRef.current) return;
            setBusy(false);
            patchLast((a) => ({ ...a, streaming: false }));
            finish(false);
          },
        );
      });
    },
    [busy, notebookId, onEvent, onLearningTurn, sourceIds, sourcePolicy, topic, updateGuidance],
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
      {(sourceIds.length > 0 || sourcePolicy === "strict") && <button type="button" className="chat-source-context" onClick={onOpenSources} aria-label="查看已选资料" title={sourceIds.length ? sourceLabel : "尚未选择资料"}>
        <FileText size={19} aria-hidden />
        <span className="chat-source-title">{sourceIds.length ? sourceLabel : "尚未选择资料"}</span>
        <span className="chat-source-count">{sourcePolicy === "strict" ? "仅依据资料" : `已选 ${sourceIds.length} 份`}</span>
        <ChevronDown size={16} aria-hidden />
      </button>}

      <div className="notebook-chat-scroll min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {msgs.length === 0 && (
          <div className="learning-welcome">
            <BookOpen size={28} className="text-[#176c58]" />
            <h3>从一个问题开始</h3>
            <p>今天想弄懂什么？</p>
            {recommendedTask && notebookId && (
              <div className="chat-next-task">
                <strong>下一步：{recommendedTask.title}</strong>
                <p>{recommendedTask.reason}</p>
                <button type="button" className="study-primary" onClick={() => void send(recommendedTask.prompt)}><Play size={16} />开始第一项任务</button>
                {onOpenPath && <button type="button" onClick={onOpenPath}><Route size={16} />查看路径</button>}
              </div>
            )}
            <div className="chat-start-actions">
              {!recommendedTask && <button type="button" onClick={() => void send(`请根据“${topic || "当前课程"}”的学习目标与已选资料，带我了解学习路线，再给我第一道小题；没有教材时请说明。`)}><BookPlus size={18} />从当前课程开始<ArrowRight size={16} /></button>}
              {onOpenAssessment && <button type="button" onClick={onOpenAssessment}><Gauge size={18} />先测一下我的水平<ArrowRight size={16} /></button>}
              <button type="button" onClick={onUploadClick}><FileUp size={18} />上传自己的资料<ArrowRight size={16} /></button>
            </div>
          </div>
        )}

        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="chat-user-message">
                {m.text}
              </div>
            </div>
          ) : (
            <div key={i} className="chat-assistant-row flex gap-3">
              <div className="min-w-0 flex-1 space-y-3">
                <div className="chat-author">小知</div>
                {(m.text || (m.streaming && !m.resources.length)) && (
                  <div
                    className="notebook-assistant-message rounded-[14px] rounded-tl-md border border-[#E5E9E3] px-4 py-3 shadow-sm"
                    aria-label="小知回答"
                    aria-live={m.streaming ? "polite" : "off"}
                  >
                    {m.text ? (
                      <><Markdown text={m.text} streaming={m.streaming} citeBase={`chat-${i}`} evidence={m.evidence} />
                      <SourceEvidence citeBase={`chat-${i}`} evidence={m.evidence} /></>
                    ) : (
                      <p role="status" aria-label="生成进度" className="flex items-center gap-2 text-sm text-[#57635A]">
                        <LoaderCircle size={15} className="shrink-0 motion-safe:animate-spin" aria-hidden />
                        {m.progress || "正在准备回答…"}
                      </p>
                    )}
                  </div>
                )}
                {!m.streaming && i === msgs.length - 1 && m.text && (
                  <AnswerChoices text={m.text} disabled={busy} onChoose={(prompt,display)=>void send(prompt, undefined, display)}/>
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
                {!m.streaming && m.text && <div className="chat-answer-actions">
                  {i === msgs.length - 1 && onSuggestedTool && !m.resources.length && <button type="button" disabled={busy} onClick={() => onSuggestedTool("quiz")}><Play size={17} />练一题</button>}
                  <button type="button" className="study-icon chat-copy" aria-label="复制回答" title={copiedMessage === i ? "已复制" : "复制回答"} onClick={async () => {
                    try { await navigator.clipboard.writeText(m.text); setCopiedMessage(i); setCopyError(""); }
                    catch { setCopyError("复制失败，请选择正文复制。"); }
                  }}>{copiedMessage === i ? <Check size={18} /> : <Copy size={18} />}</button>
                </div>}
              </div>
            </div>
          ),
        )}
        {!busy && guidance.pending && onSuggestedTool && <StudySuggestion tool={guidance.pending}
          onChoose={tool => { updateGuidance(current => dismissGuidance(current)); onSuggestedTool(tool); }}
          onDismiss={mute => updateGuidance(current => dismissGuidance(current, mute))} />}
        <div ref={bottomRef} />
      </div>

      <div className="notebook-chat-footer shrink-0 border-t border-[#E1E4EC] p-4">
        <label htmlFor="learning-chat-input" className="sr-only">和小知对话</label>
        <div className="notebook-composer relative">
          <textarea
            ref={inputRef}
            id="learning-chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229 && !window.matchMedia("(pointer: coarse)").matches) {
                e.preventDefault();
                void send(input);
              }
            }}
            rows={2}
            aria-label="学习目标输入"
            placeholder="继续提问，或写下你的理解…"
            className="study-chat-input"
          />
          <div className="composer-toolbar">
          <AdaptiveMenu className="composer-options" label="对话选项" icon={<Plus size={22} />} guide="studio-nav" expandedAt={100000}>
            <button type="button" onClick={onOpenSources}><BookOpen size={18} />学习来源</button>
            <button type="button" onClick={onUploadClick}><FileUp size={18} />添加学习资料</button>
            <button type="button" onClick={onOpenStudio}><PanelRightOpen size={18} />学习工坊</button>
            <button type="button" onClick={onCreateNotebook}><BookPlus size={18} />新建知识书本</button>
            <button type="button" onClick={() => { setInput(BEGINNER_PRESET); inputRef.current?.focus(); }}><BookOpen size={18} />零基础学习</button>
            {msgs.length > 0 && <button type="button" disabled={busy} onClick={() => void send("请把本次学习对话整理成一份可复习、可继续使用的个人笔记。", undefined, undefined, false)}><NotebookPen size={18} />整理本次笔记</button>}
            {onSourcePolicyChange && <label className="chat-policy-setting">回答依据
              <select aria-label="回答依据" value={sourcePolicy} disabled={busy} onChange={event => onSourcePolicyChange(event.target.value as "auto" | "strict" | "supplement")}>
                <option value="auto">按对话要求（默认可补充）</option>
                <option value="supplement">资料优先，允许补充</option>
                <option value="strict">仅依据资料</option>
              </select>
            </label>}
          </AdaptiveMenu>
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
          <button type="button" className="study-icon" onClick={() => setExpanded(true)} aria-label="展开编辑" title="展开编辑"><Maximize2 size={18} /></button>
          <span className="flex-1" />
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
              className="chat-send grid h-10 w-10 shrink-0 place-items-center rounded-full text-white transition disabled:cursor-not-allowed disabled:bg-[#E1E3E8] disabled:text-[#9AA0AD]"
              aria-label="发送"
              title="发送"
            >
              <ArrowUp size={22} />
            </button>
          )}
          </div>
        </div>
        {queuedHint && <div className="mt-2 text-xs font-semibold text-orange-700">{queuedHint}</div>}
        {copyError && <div role="status" className="mt-2 text-xs text-orange-700">{copyError}</div>}
        {voiceStatus && (
          <div className={`mt-2 text-xs font-semibold ${recording ? "text-red-600" : "text-emerald-700"}`}>
            {voiceStatus}
          </div>
        )}
      </div>
      <StudyDialog open={expanded} title="编辑消息" onClose={() => setExpanded(false)} className="composer-dialog"
        footer={<button type="button" className="study-primary" disabled={busy || !input.trim()} onClick={() => { setExpanded(false); void send(input); }}><ArrowRight size={18} />发送</button>}>
        {msgs.filter(message => message.role === "assistant" && message.text).length > 0 && <details className="composer-context">
          <summary>查看上一条回复</summary>
          <Markdown text={msgs.filter(message => message.role === "assistant" && message.text).at(-1)!.text} />
        </details>}
        <textarea aria-label="展开的消息编辑器" autoFocus value={input} onChange={event => setInput(event.target.value)} placeholder="写下你的问题、答案或思路…" />
      </StudyDialog>
    </div>
  );
}
