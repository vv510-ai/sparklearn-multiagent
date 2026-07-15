"use client";

import {
  ArrowRight,
  BookOpen,
  FolderOpen,
  PanelLeftOpen,
  PanelRightOpen,
  Plus,
  Route,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AgentTrace, { applyTraceEvent, emptyTrace, type TraceState } from "@/components/agent/AgentTrace";
import Chat from "@/components/chat/Chat";
import SourcePanel, { isSourceSelectable, type KnowledgeSource } from "@/components/notebook/SourcePanel";
import StudioPanel from "@/components/notebook/StudioPanel";
import PathDag from "@/components/path/PathDag";
import LearningEvidence from "@/components/profile/LearningEvidence";
import ProfileRadar from "@/components/profile/ProfileRadar";
import ReviewQueue from "@/components/profile/ReviewQueue";
import ResourceCard from "@/components/resource/ResourceCard";
import CinematicBackground from "@/components/ui/CinematicBackground";
import { apiGet, apiUpload, USER_ID } from "@/lib/api";
import { inferKpFromTopic } from "@/lib/kp";
import type { PathPlan, ResourceItem, SparkEvent, StudentProfile } from "@/lib/types";

type PanelKey = "chat" | "profile" | "path" | "resources";
type ResourceFilter = "all" | "doc" | "mindmap" | "quiz" | "video";
type ChatRequest = { path: string; body: Record<string, unknown>; display: string };
type EvalReportSummary = { path?: PathPlan; profile_version?: number };
type UploadResult = { source: KnowledgeSource; sample?: { text: string; citation: string }[] };
type QualityEvidence = {
  retrievalCount: number | null;
  knowledgePoint: string;
  grounded: boolean | null;
  verdict: string;
  citationCount: number | null;
  degradedReason: string;
  promptCapability: string;
};

const emptyQualityEvidence = (): QualityEvidence => ({
  retrievalCount: null,
  knowledgePoint: "",
  grounded: null,
  verdict: "",
  citationCount: null,
  degradedReason: "",
  promptCapability: "",
});

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function dedupeSources(items: KnowledgeSource[]): KnowledgeSource[] {
  const byDocument = new Map<string, KnowledgeSource>();
  for (const source of items) {
    const key = String(source.filename || source.title || source.id).trim().toLocaleLowerCase();
    const existing = byDocument.get(key);
    if (!existing) {
      byDocument.set(key, source);
      continue;
    }
    const sourceRank = (isSourceSelectable(source) ? 4 : source.status === "processing" ? 3 : 1);
    const existingRank = (isSourceSelectable(existing) ? 4 : existing.status === "processing" ? 3 : 1);
    const sourceTime = source.updated_at || source.created_at || "";
    const existingTime = existing.updated_at || existing.created_at || "";
    if (sourceRank > existingRank || (sourceRank === existingRank && sourceTime > existingTime)) {
      byDocument.set(key, source);
    }
  }
  return Array.from(byDocument.values());
}

const RESOURCE_FILTERS: { key: ResourceFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "doc", label: "笔记" },
  { key: "mindmap", label: "导图" },
  { key: "quiz", label: "测验" },
  { key: "video", label: "讲解" },
];

const TRACE_FLOW = [
  { label: "理解目标", ids: ["profile", "orchestrator"] },
  { label: "规划路线", ids: ["planner", "path"] },
  { label: "整理内容", ids: ["doc", "mindmap", "quiz", "media", "tutor"] },
  { label: "检查结果", ids: ["eval"] },
] as const;

function SparkMark({ light = false, running = false }: { light?: boolean; running?: boolean }) {
  return (
    <span className={`inline-grid h-7 w-7 place-items-center ${running ? "animate-pulse" : ""}`} aria-hidden>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <path
          d="M12 1.8c.9 4.8 4.6 8.5 9.4 9.4-4.8.9-8.5 4.6-9.4 9.4-.9-4.8-4.6-8.5-9.4-9.4 4.8-.9 8.5-4.6 9.4-9.4z"
          fill={running ? "#F4C879" : light ? "#F5FFF9" : "#0F6B50"}
        />
      </svg>
    </span>
  );
}

function LearningGate({
  onStart,
  onUpload,
  uploading,
}: {
  onStart: (goal: string) => void;
  onUpload: (file: File) => void;
  uploading: boolean;
}) {
  const [goal, setGoal] = useState("");
  const [transitioning, setTransitioning] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const transitionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current);
  }, []);

  const start = () => {
    const next = goal.trim();
    if (!next || transitioning) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setTransitioning(true);
    transitionTimerRef.current = setTimeout(() => onStart(next), reduceMotion ? 40 : 820);
  };

  return (
    <main
      className={`learning-gate-shell relative min-h-dvh overflow-hidden text-white ${transitioning ? "is-transitioning" : ""}`}
      aria-busy={transitioning}
    >
      <CinematicBackground />
      <div className="learning-gate-stage relative z-10 mx-auto flex min-h-dvh w-full max-w-7xl flex-col px-4 py-5 sm:px-8 sm:py-6">
        <nav className="learning-gate-nav liquid-glass glass-readable flex items-center justify-between rounded-full px-5 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <SparkMark light />
            <span className="text-xl text-white" style={{ fontFamily: "var(--font-display)" }}>
              SparkLearn<sup className="ml-0.5 text-[9px]">®</sup>
            </span>
          </div>
          <button disabled={transitioning} onClick={() => document.getElementById("learning-goal")?.focus()} className="liquid-glass flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium text-white transition-transform hover:scale-[1.03] disabled:pointer-events-none">
            开始学习 <ArrowRight size={16} />
          </button>
        </nav>

        <section className="learning-gate-hero cinematic-copy flex flex-1 flex-col items-center justify-center px-3 py-10 text-center lg:-translate-y-[2%]">
          <h1 className="animate-fade-rise max-w-6xl text-[43px] font-normal leading-[0.98] text-white sm:text-7xl md:text-[82px]" style={{ fontFamily: "var(--font-display)" }}>
            <span className="block">SparkLearn，</span>
            <em className="mt-1 block whitespace-nowrap text-[37px] not-italic text-white/70 sm:text-7xl md:text-[82px]">学习的左膀右臂。</em>
          </h1>

          <div className="liquid-glass glass-readable animate-fade-rise-delay mt-7 flex w-full max-w-[760px] items-center gap-2 rounded-full p-2 pl-2.5 shadow-[0_24px_80px_rgba(0,16,27,0.28)]">
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,.pdf,.png,.jpg,.jpeg,text/plain,text/markdown,application/pdf,image/png,image/jpeg"
              className="hidden"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                if (file) onUpload(file);
              }}
            />
            <button onClick={() => fileRef.current?.click()} disabled={uploading || transitioning} className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-white/75 transition hover:bg-white/10 hover:text-white disabled:cursor-wait" aria-label="添加学习资料" title="添加学习资料">
              {uploading ? <Upload size={19} className="animate-pulse" /> : <Plus size={21} />}
            </button>
            <input
              id="learning-goal"
              value={goal}
              disabled={transitioning}
              onChange={(event) => setGoal(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && start()}
              placeholder="你今天想学什么？"
              className="min-w-0 flex-1 bg-transparent px-1 text-base text-white outline-none placeholder:text-white/45 sm:text-lg"
            />
            <button onClick={start} disabled={!goal.trim() || transitioning} className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white text-[#092B38] transition hover:scale-[1.04] disabled:cursor-not-allowed disabled:bg-white/20 disabled:text-white/35" aria-label="开始学习">
              <ArrowRight size={20} />
            </button>
          </div>
        </section>

      </div>
      <div className="workspace-transition" aria-hidden={!transitioning}>
        <div className="workspace-transition-surface" />
        <div className="workspace-transition-label">
          <SparkMark running={transitioning} />
          <span>正在铺开你的学习工作台</span>
        </div>
      </div>
    </main>
  );
}

function EvidenceSummary({
  trace,
  quality,
  selectedSourceCount,
}: {
  trace: TraceState;
  quality: QualityEvidence;
  selectedSourceCount: number;
}) {
  const qualityRows = [
    { label: "资料范围", value: selectedSourceCount ? `已选 ${selectedSourceCount} 份个人资料` : "课程知识库" },
    { label: "检索片段", value: quality.retrievalCount == null ? "等待检索" : `${quality.retrievalCount} 个可核对片段` },
    { label: "回答溯源", value: quality.grounded == null ? "等待检查" : quality.grounded ? "已通过" : "需要复核" },
    { label: "引用来源", value: quality.citationCount == null ? "等待生成" : `${quality.citationCount} 处` },
  ];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">{TRACE_FLOW.map((stage, index) => {
        const nodes = stage.ids.map((id) => trace[id]).filter(Boolean);
        const status = nodes.some((node) => node.status === "error")
          ? "error"
          : nodes.some((node) => node.status === "running")
            ? "running"
            : nodes.some((node) => node.status === "done")
              ? "done"
              : "idle";
        return (
          <div key={stage.label} className={`evidence-stage is-${status} rounded-[8px] border px-3 py-3`}>
            <div className="flex items-center justify-between gap-2">
              <span className="grid h-6 w-6 place-items-center rounded-full bg-white/10 text-[11px] font-bold text-white">{status === "done" ? "✓" : index + 1}</span>
              <span className="text-[11px] text-white/50">{status === "running" ? "进行中" : status === "done" ? "已完成" : status === "error" ? "需重试" : "等待"}</span>
            </div>
            <div className="mt-2 text-sm font-semibold text-white">{stage.label}</div>
          </div>
        );
      })}</div>
      <div className="rounded-[8px] border border-white/10 bg-white/[0.04] p-3">
        <div className="text-[10px] font-bold tracking-[0.16em] text-[#7ED9A6]">QUALITY EVIDENCE</div>
        <div className="mt-2 divide-y divide-white/10">
          {qualityRows.map((row) => (
            <div key={row.label} className="flex items-center justify-between gap-3 py-2 text-xs">
              <span className="text-white/50">{row.label}</span>
              <strong className="text-right font-semibold text-white/90">{row.value}</strong>
            </div>
          ))}
        </div>
        {quality.knowledgePoint && <div className="mt-2 rounded-md bg-black/10 px-2.5 py-2 text-[11px] text-white/65">检索主题：{quality.knowledgePoint}</div>}
        {quality.promptCapability && <div className="mt-2 text-[11px] text-white/50">教学模板：{quality.promptCapability}</div>}
        {quality.verdict && <div className="mt-2 text-[11px] leading-5 text-white/60">检查结论：{quality.verdict}</div>}
        {quality.degradedReason && <div className="mt-2 rounded-md border border-amber-300/20 bg-amber-300/10 px-2.5 py-2 text-[11px] text-amber-100">已启用备用方案：{quality.degradedReason}</div>}
      </div>
    </div>
  );
}

export default function Home() {
  const [entered, setEntered] = useState(false);
  const [notebookTopic, setNotebookTopic] = useState("");
  const [activePanel, setActivePanel] = useState<PanelKey>("chat");
  const [mobilePane, setMobilePane] = useState<"sources" | "studio" | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [traceDetailsOpen, setTraceDetailsOpen] = useState(false);
  const [trace, setTrace] = useState<TraceState>(emptyTrace());
  const [qualityEvidence, setQualityEvidence] = useState<QualityEvidence>(emptyQualityEvidence());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [seed, setSeed] = useState<string | undefined>();
  const [request, setRequest] = useState<ChatRequest | undefined>();
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [pathPlan, setPathPlan] = useState<PathPlan | null>(null);
  const [selectedPathNode, setSelectedPathNode] = useState<string | null>(null);
  const [resources, setResources] = useState<ResourceItem[]>([]);
  const [resourceFilter, setResourceFilter] = useState<ResourceFilter>("all");
  const [panelError, setPanelError] = useState("");
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadNote, setUploadNote] = useState("");
  const [uploadError, setUploadError] = useState(false);
  const sourceInputRef = useRef<HTMLInputElement>(null);

  const running = useMemo(() => Object.values(trace).some((node) => node.status === "running"), [trace]);
  const finished = useMemo(() => Object.values(trace).some((node) => node.status === "done"), [trace]);

  const loadProfile = useCallback(async () => {
    setPanelError("");
    try {
      const report = await apiGet<{ profile?: StudentProfile }>(`/eval/report?user_id=${USER_ID}`);
      if (report.profile) setProfile(report.profile);
      else setProfile(await apiGet<StudentProfile>(`/profile/${USER_ID}`));
    } catch (error) {
      setPanelError(`学习情况暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const loadPath = useCallback(async () => {
    setPanelError("");
    try {
      const plan = await apiGet<PathPlan>(`/path?user_id=${USER_ID}`);
      setPathPlan(plan);
      setSelectedPathNode(plan.next_kp || plan.nodes[0]?.id || null);
    } catch (error) {
      setPanelError(`知识关系暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const loadResources = useCallback(async () => {
    setPanelError("");
    try {
      const data = await apiGet<{ items: ResourceItem[] }>(`/resources?user_id=${USER_ID}&limit=30`);
      setResources(data.items || []);
    } catch (error) {
      setPanelError(`资料归档暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const loadSources = useCallback(async () => {
    try {
      const data = await apiGet<{ items: KnowledgeSource[] }>(`/knowledge/sources?user_id=${USER_ID}`);
      const items = dedupeSources(data.items || []);
      setSources(items);
      setSelectedSourceIds((ids) => ids.filter((id) => items.some((item) => item.id === id && isSourceSelectable(item))));
    } catch (error) {
      setUploadError(true);
      setUploadNote(`学习资料暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  const uploadSource = async (file: File) => {
    setUploading(true);
    setUploadNote("");
    setUploadError(false);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("user_id", USER_ID);
      form.append("title", file.name.replace(/\.[^.]+$/, ""));
      const result = await apiUpload<UploadResult>("/knowledge/upload", form);
      setSources((items) => dedupeSources([result.source, ...items.filter((item) => item.id !== result.source.id)]));
      if (isSourceSelectable(result.source)) {
        setSelectedSourceIds((ids) => Array.from(new Set([...ids, result.source.id])));
      }
      setUploadNote(
        result.source.status === "degraded"
          ? `已加入「${result.source.title}」· ${result.source.chunk_count} 个片段，当前使用降级解析`
          : `已加入「${result.source.title}」· ${result.source.chunk_count} 个可引用片段`,
      );
    } catch (error) {
      setUploadError(true);
      setUploadNote(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
    }
  };

  const startNotebook = (goal: string) => {
    setEntered(true);
    setNotebookTopic(goal.trim());
    setActivePanel("chat");
    setTrace(emptyTrace());
    setQualityEvidence(emptyQualityEvidence());
    setSeed(goal.trim());
    setRequest(undefined);
  };

  const leave = () => {
    setEntered(false);
    setActivePanel("chat");
    setTrace(emptyTrace());
    setQualityEvidence(emptyQualityEvidence());
    setSeed(undefined);
    setRequest(undefined);
    setEvidenceOpen(false);
    setMobilePane(null);
  };

  const startGenerate = (goal: string, kinds: string[], promptTemplate: string) => {
    const scopedGoal = notebookTopic ? `${goal}\n\n当前学习主题：${notebookTopic}` : goal;
    const topicKp = inferKpFromTopic(notebookTopic);
    setActivePanel("chat");
    setMobilePane(null);
    setTrace(emptyTrace());
    setQualityEvidence(emptyQualityEvidence());
    setSeed(undefined);
    setRequest({
      path: "/resources/generate",
      display: scopedGoal,
      body: {
        user_id: USER_ID,
        goal: scopedGoal,
        topic_label: notebookTopic,
        knowledge_points: topicKp ? [topicKp] : [],
        kinds,
        source_ids: selectedSourceIds,
        prompt_template: promptTemplate,
      },
    });
  };

  const openPanel = (panel: "profile" | "path" | "resources") => {
    setActivePanel(panel);
    setMobilePane(null);
    if (panel === "profile") void loadProfile();
    if (panel === "path") void loadPath();
    if (panel === "resources") void loadResources();
  };

  const refreshAfterEvaluation = useCallback((report?: EvalReportSummary) => {
    if (report?.path) {
      setPathPlan(report.path);
      setSelectedPathNode(report.path.next_kp || report.path.nodes[0]?.id || null);
    }
    void loadProfile();
  }, [loadProfile]);

  const onEvent = useCallback((event: SparkEvent) => {
    setTrace((current) => applyTraceEvent(current, event));
    if (event.type === "agent_start" && event.agent === "profile") setQualityEvidence(emptyQualityEvidence());
    const output = asRecord(event.output);
    const retrieval = asRecord(event.retrieval) || asRecord(output?.retrieval);
    const grounding = asRecord(event.grounding) || asRecord(output?.grounding);
    const promptSkill = asRecord(event.prompt_skill) || asRecord(output?.prompt_skill);
    if (retrieval || grounding || promptSkill || event.degraded || event.type === "citations") {
      setQualityEvidence((current) => ({
        ...current,
        retrievalCount: retrieval ? Number(retrieval.count ?? 0) : current.retrievalCount,
        knowledgePoint: retrieval?.knowledge_point ? String(retrieval.knowledge_point) : current.knowledgePoint,
        grounded: grounding && typeof grounding.grounded === "boolean" ? grounding.grounded : current.grounded,
        verdict: grounding?.verdict ? String(grounding.verdict) : current.verdict,
        citationCount: event.type === "citations" ? (event.items || []).length : current.citationCount,
        degradedReason: event.degraded ? String(event.detail || event.reason || "备用链路") : current.degradedReason,
        promptCapability: promptSkill?.capability ? String(promptSkill.capability) : current.promptCapability,
      }));
    }
    if (event.type === "profile" && event.profile) setProfile(event.profile);
    if (event.type === "path" && event.path) {
      setPathPlan(event.path);
      setSelectedPathNode(event.path.next_kp || event.path.nodes[0]?.id || null);
    }
    if (event.type === "trace" && event.session_id) setSessionId(String(event.session_id));
    if (event.type === "resource" && event.resource) setResources((items) => [event.resource!, ...items].slice(0, 30));
  }, []);

  const filteredResources = useMemo(() => {
    if (resourceFilter === "all") return resources;
    if (resourceFilter === "doc") return resources.filter((item) => ["doc", "code", "reading"].includes(item.kind));
    return resources.filter((item) => item.kind === resourceFilter);
  }, [resourceFilter, resources]);

  const groupedResources = useMemo(() => {
    const groups = new Map<string, ResourceItem[]>();
    filteredResources.forEach((item) => {
      const key = `${item.kind}:${item.title.trim().toLocaleLowerCase()}`;
      groups.set(key, [...(groups.get(key) || []), item]);
    });
    return Array.from(groups.entries()).map(([key, items]) => {
      const versions = [...items].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      return { key, representative: versions[0], versionCount: versions.length };
    });
  }, [filteredResources]);

  if (!entered) {
    return (
      <LearningGate
        onStart={startNotebook}
        onUpload={(file) => void uploadSource(file)}
        uploading={uploading}
      />
    );
  }

  const sourcePanel = (
    <SourcePanel
      sources={sources}
      selectedIds={selectedSourceIds}
      uploading={uploading}
      uploadNote={uploadNote}
      uploadError={uploadError}
      onAdd={() => sourceInputRef.current?.click()}
      onUseCourse={() => setSelectedSourceIds([])}
      onToggle={(sourceId) => setSelectedSourceIds((ids) => ids.includes(sourceId) ? ids.filter((id) => id !== sourceId) : [...ids, sourceId])}
    />
  );
  const studioPanel = <StudioPanel onGenerate={startGenerate} onOpen={openPanel} />;

  return (
    <main className="notebook-app notebook-app-enter flex h-dvh flex-col overflow-hidden text-[#1D2028]">
      <input
        ref={sourceInputRef}
        type="file"
        accept=".txt,.md,.pdf,.png,.jpg,.jpeg,text/plain,text/markdown,application/pdf,image/png,image/jpeg"
        className="hidden"
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file) void uploadSource(file);
        }}
      />

      <header className="notebook-topbar relative z-20 flex h-[68px] shrink-0 items-center gap-3 px-4 sm:px-5">
        <button onClick={() => setActivePanel("chat")} className="flex items-center gap-2.5" title="返回学习对话">
          <SparkMark running={running} />
          <strong className="text-lg tracking-tight">SparkLearn</strong>
        </button>
        <span className="hidden h-5 w-px bg-[#DDE0E8] sm:block" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-[#343944]">{notebookTopic || "新的学习笔记"}</div>
          <div className="hidden text-[11px] text-[#818795] sm:block">{selectedSourceIds.length ? `${selectedSourceIds.length} 份个人资料参与回答` : "课程知识库参与回答"}</div>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={() => setMobilePane("sources")} className="notebook-icon-button xl:hidden" aria-label="打开学习来源"><PanelLeftOpen size={18} /></button>
          <button onClick={() => setMobilePane("studio")} className="notebook-icon-button xl:hidden" aria-label="打开学习工坊"><PanelRightOpen size={18} /></button>
          <span className={`hidden rounded-full px-3 py-1.5 text-xs font-semibold sm:inline-flex ${running ? "bg-[#FFF1DD] text-[#9A5B12]" : finished ? "bg-[#E8F4ED] text-[#0F6B50]" : "bg-[#F0F1F5] text-[#626978]"}`}>
            {running ? "正在整理" : finished ? "已经完成" : "准备就绪"}
          </span>
          <button onClick={leave} className="notebook-home-button" title="开始新的学习">
            <BookOpen size={16} />
            <span className="hidden sm:inline">新的学习</span>
          </button>
          <button onClick={() => setEvidenceOpen(true)} className="notebook-evidence-button">
            <ShieldCheck size={16} /><span className="hidden sm:inline">依据</span>
          </button>
        </div>
      </header>

      <div className="notebook-layout min-h-0 flex-1">
        <aside className="hidden min-h-0 xl:block">{sourcePanel}</aside>

        <section className="notebook-column min-h-0 overflow-hidden">
          {panelError && <div className="m-3 rounded-[8px] border border-[#F1D6C9] bg-[#FFF6F1] px-4 py-3 text-sm text-[#9E4B2D]">{panelError}</div>}

          {activePanel === "chat" && (
            <Chat
              onEvent={onEvent}
              seed={seed}
              request={request}
              topic={notebookTopic}
              sourceIds={selectedSourceIds}
              onUploadClick={() => sourceInputRef.current?.click()}
              onSeedConsumed={() => { setSeed(undefined); setRequest(undefined); }}
              onQuizEvaluated={refreshAfterEvaluation}
            />
          )}

          {activePanel === "profile" && (
            <div className="notebook-content-scroll">
              <div className="notebook-content-heading">
                <div><span>LEARNING PROFILE</span><h1>我的学习情况</h1><p>每次真实作答都会更新掌握度与错因。</p></div>
                <button onClick={() => void loadProfile()} className="secondary-action">刷新</button>
              </div>
              <div className="px-5 pt-5">
                <ReviewQueue onEvaluated={refreshAfterEvaluation} />
              </div>
              <div className="px-5 pt-4">
                <LearningEvidence refreshToken={profile?._version ?? profile?.version ?? 0} />
              </div>
              <div className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_280px]">
                <ProfileRadar profile={profile} />
                <div className="insight-panel p-5">
                  <div className="text-xs font-bold text-[#0F6B50]">下一步</div>
                  <h2 className="mt-3 text-xl font-bold">先补薄弱点，再继续向前。</h2>
                  <p className="mt-3 text-sm leading-7 text-[#6F7684]">提交测验后，掌握度、错因与学习顺序会一起更新。</p>
                  <button onClick={() => openPanel("path")} className="primary-action mt-6">查看知识关系</button>
                </div>
              </div>
            </div>
          )}

          {activePanel === "path" && (
            <div className="notebook-content-scroll">
              <div className="notebook-content-heading">
                <div><span>KNOWLEDGE RELATION</span><h1>知识关系与下一步</h1><p>先修关系、掌握状态和推荐顺序放在同一张图里。</p></div>
                <button onClick={() => void loadPath()} className="secondary-action">重新计算</button>
              </div>
              <div className="p-5">
                {pathPlan ? (
                  <div className="insight-panel overflow-x-auto p-5">
                    <PathDag plan={pathPlan} selected={selectedPathNode} onSelect={setSelectedPathNode} />
                    {pathPlan.remediation?.status === "needed" && (
                      <div className="mt-4 rounded-[10px] border border-amber-200 bg-amber-50 px-4 py-3">
                        <div className="text-[10px] font-bold tracking-[0.16em] text-amber-700">DIAGNOSTIC REMEDIATION</div>
                        <div className="mt-1 text-sm font-bold text-[#3D3122]">
                          {pathPlan.remediation.prerequisite_gap
                            ? `先补「${pathPlan.remediation.prerequisite_name}」，再回到「${pathPlan.remediation.blocked_name}」`
                            : `换一种方式巩固「${pathPlan.remediation.blocked_name}」`}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-[#7A654C]">{pathPlan.remediation.reason}</p>
                      </div>
                    )}
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-[8px] border border-[#E1E4EC] bg-[#F8F9FC] p-4 text-sm text-[#626978]">
                      <span>当前建议优先学习</span>
                      <strong className="text-[#0F6B50]">{pathPlan.nodes.find((node) => node.id === pathPlan.next_kp)?.name || pathPlan.next_kp || "等待生成"}</strong>
                    </div>
                  </div>
                ) : <div className="source-empty min-h-[240px]"><Route size={24} /><strong>还没有学习路线</strong><span>完成一次测验，或点击“重新计算”。</span></div>}
              </div>
            </div>
          )}

          {activePanel === "resources" && (
            <div className="notebook-content-scroll">
              <div className="notebook-content-heading">
                <div><span>LIBRARY</span><h1>资料归档</h1><p>笔记、导图、测验和讲解按主题继续保留。</p></div>
                <span className="rounded-[8px] border border-[#E1E4EC] bg-white px-3 py-2 text-xs font-semibold text-[#626978]">{groupedResources.length} 个主题</span>
              </div>
              <div className="p-5">
                <div className="mb-4 flex gap-1 overflow-x-auto rounded-[8px] bg-[#ECEEF3] p-1" role="tablist">
                  {RESOURCE_FILTERS.map((filter) => (
                    <button key={filter.key} onClick={() => setResourceFilter(filter.key)} className={`min-w-[76px] flex-1 rounded-[7px] px-3 py-2 text-sm font-semibold ${resourceFilter === filter.key ? "bg-white text-[#1D2028] shadow-sm" : "text-[#6F7684]"}`}>
                      {filter.label}
                    </button>
                  ))}
                </div>
                {groupedResources.length ? (
                  <div className="space-y-3">
                    {groupedResources.map((group) => <ResourceCard key={group.key} r={group.representative} versionCount={group.versionCount} onQuizEvaluated={refreshAfterEvaluation} />)}
                  </div>
                ) : <div className="source-empty min-h-[220px]"><FolderOpen size={24} /><strong>这里还没有资料</strong><span>从右侧学习工坊生成一份内容。</span></div>}
              </div>
            </div>
          )}
        </section>

        <aside className="hidden min-h-0 xl:block">{studioPanel}</aside>
      </div>

      {mobilePane && (
        <div className="fixed inset-0 z-40 bg-[#151821]/25 backdrop-blur-[2px] xl:hidden" onClick={() => setMobilePane(null)}>
          <div className={`absolute inset-y-0 w-[min(88vw,360px)] bg-[#F7F8FC] p-3 shadow-2xl ${mobilePane === "sources" ? "left-0" : "right-0"}`} onClick={(event) => event.stopPropagation()}>
            <button onClick={() => setMobilePane(null)} className="absolute right-5 top-5 z-10 grid h-8 w-8 place-items-center rounded-full bg-white text-[#596171] shadow-sm" aria-label="关闭"><X size={17} /></button>
            {mobilePane === "sources" ? sourcePanel : studioPanel}
          </div>
        </div>
      )}

      <section className={`fixed inset-y-0 right-0 z-50 w-[min(92vw,420px)] border-l border-white/10 bg-[#072C3A]/[0.98] text-white shadow-[-22px_0_70px_rgba(0,18,28,0.3)] backdrop-blur-xl transition-transform duration-300 ${evidenceOpen ? "translate-x-0" : "translate-x-full"}`}>
        <div className="flex h-[68px] items-center justify-between border-b border-white/10 px-5">
          <div><div className="text-[10px] tracking-[0.18em] text-white/45">EVIDENCE</div><strong>依据与过程</strong></div>
          <button onClick={() => setEvidenceOpen(false)} className="grid h-9 w-9 place-items-center rounded-full bg-white/5 text-white/70 hover:bg-white/10" aria-label="关闭依据面板"><X size={18} /></button>
        </div>
        <div className="h-[calc(100dvh-68px)] overflow-y-auto p-4">
          <EvidenceSummary trace={trace} quality={qualityEvidence} selectedSourceCount={selectedSourceIds.length} />
          <button onClick={() => setTraceDetailsOpen((open) => !open)} className="mt-3 flex w-full items-center justify-between rounded-[8px] border border-white/10 bg-white/[0.05] px-3 py-2.5 text-left text-sm font-semibold text-white">
            <span>{traceDetailsOpen ? "收起详细过程" : "查看详细过程"}</span><span>⌄</span>
          </button>
          {traceDetailsOpen && <div className="mt-3"><AgentTrace trace={trace} />{sessionId && <div className="mt-3 rounded-[8px] border border-white/10 bg-black/10 px-3 py-2 font-mono text-[11px] text-white/55">运行编号：{sessionId}</div>}</div>}
        </div>
      </section>
    </main>
  );
}
