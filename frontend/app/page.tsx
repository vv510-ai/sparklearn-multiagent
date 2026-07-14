"use client";

import Image from "next/image";
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
import SourcePanel, { type KnowledgeSource } from "@/components/notebook/SourcePanel";
import StudioPanel from "@/components/notebook/StudioPanel";
import PathDag from "@/components/path/PathDag";
import ProfileRadar from "@/components/profile/ProfileRadar";
import ResourceCard from "@/components/resource/ResourceCard";
import CinematicBackground from "@/components/ui/CinematicBackground";
import { useView, type ViewKey } from "@/components/view/ViewContext";
import { apiGet, apiUpload, USER_ID } from "@/lib/api";
import type { PathPlan, ResourceItem, SparkEvent, StudentProfile } from "@/lib/types";

type PanelKey = "chat" | "profile" | "path" | "resources";
type ResourceFilter = "all" | "doc" | "mindmap" | "quiz" | "video";
type ChatRequest = { path: string; body: Record<string, unknown>; display: string };
type EvalReportSummary = { path?: PathPlan; profile_version?: number };
type UploadResult = { source: KnowledgeSource; sample?: { text: string; citation: string }[] };

const ROLE_ORDER: ViewKey[] = ["student", "teacher", "judge"];
const ROLE_PROFILE: Record<ViewKey, { image: string; name: string; who: string; example: string }> = {
  student: {
    image: "/roles/student-v2.png",
    name: "学生",
    who: "个人学习",
    example: "讲透一个知识点，再练到会",
  },
  teacher: {
    image: "/roles/teacher-v2.png",
    name: "老师",
    who: "教学准备",
    example: "把教学目标整理成内容与练习",
  },
  judge: {
    image: "/roles/manager-v2.png",
    name: "教研",
    who: "质量与效果",
    example: "先看学习效果，再追溯依据",
  },
};

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

function RoleAvatar({ role }: { role: ViewKey }) {
  const item = ROLE_PROFILE[role];
  return (
    <span className="relative block h-8 w-8 shrink-0 overflow-hidden rounded-full border border-black/[0.06] bg-[#EEF1EC]">
      <Image src={item.image} alt={`${item.name}角色形象`} fill sizes="32px" className="object-cover object-top" priority={role === "student"} />
    </span>
  );
}

function RoleGate({
  onStart,
  onUpload,
  uploading,
  uploadNote,
  uploadError,
  sourceCount,
}: {
  onStart: (role: ViewKey, goal: string) => void;
  onUpload: (file: File) => void;
  uploading: boolean;
  uploadNote: string;
  uploadError: boolean;
  sourceCount: number;
}) {
  const [role, setRole] = useState<ViewKey>("student");
  const [goal, setGoal] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const start = () => {
    const next = goal.trim();
    if (next) onStart(role, next);
  };

  return (
    <main className="role-gate-shell relative min-h-dvh overflow-hidden text-white">
      <CinematicBackground />
      <div className="relative z-10 mx-auto flex min-h-dvh w-full max-w-7xl flex-col px-4 py-5 sm:px-8 sm:py-6">
        <nav className="liquid-glass glass-readable flex items-center justify-between rounded-full px-5 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <SparkMark light />
            <span className="text-xl text-white" style={{ fontFamily: "var(--font-display)" }}>
              SparkLearn<sup className="ml-0.5 text-[9px]">®</sup>
            </span>
          </div>
          <button onClick={() => document.getElementById("learning-goal")?.focus()} className="liquid-glass flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium text-white transition-transform hover:scale-[1.03]">
            开始学习 <ArrowRight size={16} />
          </button>
        </nav>

        <section className="cinematic-copy flex flex-1 flex-col items-center justify-center px-3 py-10 text-center lg:-translate-y-[2%]">
          <h1 className="animate-fade-rise max-w-6xl text-[43px] font-normal leading-[0.98] text-white sm:text-7xl md:text-[82px]" style={{ fontFamily: "var(--font-display)" }}>
            <span className="block">SparkLearn，</span>
            <em className="mt-1 block whitespace-nowrap text-[37px] not-italic text-white/70 sm:text-7xl md:text-[82px]">学习的左膀右臂。</em>
          </h1>
          <p className="animate-fade-rise-delay mt-7 max-w-2xl text-base leading-relaxed text-white/75 sm:text-lg">
            上传你的资料，问一个问题。星火会把讲解、框架、练习与下一步整理到同一本学习笔记里。
          </p>

          <div className="animate-fade-rise-delay mt-6 flex flex-wrap justify-center gap-2" aria-label="选择身份">
            {ROLE_ORDER.map((key) => (
              <button key={key} onClick={() => setRole(key)} aria-pressed={role === key} className={`role-pill liquid-glass glass-readable flex items-center gap-2 rounded-full py-1.5 pl-1.5 pr-4 text-sm transition ${role === key ? "is-selected" : ""}`}>
                <RoleAvatar role={key} />
                <span>{ROLE_PROFILE[key].name}</span>
              </button>
            ))}
          </div>

          <div className="liquid-glass glass-readable animate-fade-rise-delay-2 mt-5 flex w-full max-w-[760px] items-center gap-2 rounded-full p-2 pl-2.5 shadow-[0_24px_80px_rgba(0,16,27,0.28)]">
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
            <button onClick={() => fileRef.current?.click()} disabled={uploading} className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-white/75 transition hover:bg-white/10 hover:text-white disabled:cursor-wait" aria-label="添加学习资料" title="添加学习资料">
              {uploading ? <Upload size={19} className="animate-pulse" /> : <Plus size={21} />}
            </button>
            <input
              id="learning-goal"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && start()}
              placeholder="你今天想学什么知识？"
              className="min-w-0 flex-1 bg-transparent px-1 text-base text-white outline-none placeholder:text-white/45 sm:text-lg"
            />
            <button onClick={start} disabled={!goal.trim()} className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white text-[#092B38] transition hover:scale-[1.04] disabled:cursor-not-allowed disabled:bg-white/20 disabled:text-white/35" aria-label="开始学习">
              <ArrowRight size={20} />
            </button>
          </div>
          <div className="mt-3 min-h-5 text-xs text-white/60">
            {uploadNote ? (
              <span className={uploadError ? "text-[#FFD0C6]" : "text-[#D7F6E6]"}>{uploadNote}</span>
            ) : sourceCount ? (
              <span>已准备 {sourceCount} 份个人资料，进入后可选择使用范围</span>
            ) : (
              <span>不上传也可以，系统会使用课程知识库</span>
            )}
          </div>
        </section>

        <section className="hidden grid-cols-3 gap-3 pb-2 md:grid">
          {ROLE_ORDER.map((key) => {
            const item = ROLE_PROFILE[key];
            return (
              <button key={key} onClick={() => setRole(key)} aria-pressed={role === key} className={`liquid-glass glass-readable group flex min-h-[80px] items-center gap-3 rounded-[16px] p-3 text-left transition hover:-translate-y-0.5 ${role === key ? "role-entry-active" : ""}`}>
                <RoleAvatar role={key} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2"><strong>{item.name}</strong><small className="text-white/50">{item.who}</small></span>
                  <span className="mt-1 block truncate text-xs text-white/70">{item.example}</span>
                </span>
                <ArrowRight size={15} className="text-white/45" />
              </button>
            );
          })}
        </section>
      </div>
    </main>
  );
}

function EvidenceSummary({ trace }: { trace: TraceState }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {TRACE_FLOW.map((stage, index) => {
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
      })}
    </div>
  );
}

export default function Home() {
  const { view, setView } = useView();
  const [entered, setEntered] = useState(false);
  const [notebookTopic, setNotebookTopic] = useState("");
  const [activePanel, setActivePanel] = useState<PanelKey>("chat");
  const [mobilePane, setMobilePane] = useState<"sources" | "studio" | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [traceDetailsOpen, setTraceDetailsOpen] = useState(false);
  const [trace, setTrace] = useState<TraceState>(emptyTrace());
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

  const role = ROLE_PROFILE[view];
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
      setSources(data.items || []);
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
      setSources((items) => [result.source, ...items.filter((item) => item.id !== result.source.id)]);
      setSelectedSourceIds((ids) => Array.from(new Set([...ids, result.source.id])));
      setUploadNote(`已加入「${result.source.title}」· ${result.source.chunk_count} 个可引用片段`);
    } catch (error) {
      setUploadError(true);
      setUploadNote(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
    }
  };

  const startNotebook = (nextView: ViewKey, goal: string) => {
    setView(nextView);
    setEntered(true);
    setNotebookTopic(goal.trim());
    setActivePanel("chat");
    setTrace(emptyTrace());
    setSeed(goal.trim());
    setRequest(undefined);
  };

  const leave = () => {
    setEntered(false);
    setActivePanel("chat");
    setTrace(emptyTrace());
    setSeed(undefined);
    setRequest(undefined);
    setEvidenceOpen(false);
    setMobilePane(null);
  };

  const startGenerate = (goal: string, kinds: string[], promptTemplate: string) => {
    const scopedGoal = notebookTopic ? `${goal}\n\n当前学习主题：${notebookTopic}` : goal;
    setActivePanel("chat");
    setMobilePane(null);
    setTrace(emptyTrace());
    setSeed(undefined);
    setRequest({
      path: "/resources/generate",
      display: scopedGoal,
      body: {
        user_id: USER_ID,
        goal: scopedGoal,
        knowledge_points: [],
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
      <RoleGate
        onStart={startNotebook}
        onUpload={(file) => void uploadSource(file)}
        uploading={uploading}
        uploadNote={uploadNote}
        uploadError={uploadError}
        sourceCount={sources.filter((source) => source.status === "indexed").length}
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
    <main className="notebook-app flex h-dvh flex-col overflow-hidden text-[#1D2028]">
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
          <button onClick={leave} className="role-switch" title="切换身份">
            <RoleAvatar role={view} />
            <span className="hidden sm:inline">{role.name}</span>
            <span className="text-[#8A909C]">⌄</span>
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
          <EvidenceSummary trace={trace} />
          <button onClick={() => setTraceDetailsOpen((open) => !open)} className="mt-3 flex w-full items-center justify-between rounded-[8px] border border-white/10 bg-white/[0.05] px-3 py-2.5 text-left text-sm font-semibold text-white">
            <span>{traceDetailsOpen ? "收起详细过程" : "查看详细过程"}</span><span>⌄</span>
          </button>
          {traceDetailsOpen && <div className="mt-3"><AgentTrace trace={trace} />{sessionId && <div className="mt-3 rounded-[8px] border border-white/10 bg-black/10 px-3 py-2 font-mono text-[11px] text-white/55">运行编号：{sessionId}</div>}</div>}
        </div>
      </section>
    </main>
  );
}
