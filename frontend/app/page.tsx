"use client";

import {
  ArrowRight,
  BookOpen,
  FolderOpen,
  LogOut,
  PanelLeftOpen,
  PanelRightOpen,
  Plus,
  Route,
  ShieldCheck,
  Contrast,
  Target,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import AgentTrace, { applyTraceEvent, emptyTrace, type TraceState } from "@/components/agent/AgentTrace";
import AuthGate, { type AuthUser } from "@/components/auth/AuthGate";
import Chat from "@/components/chat/Chat";
import SourcePanel, { COURSE_SOURCE_ID, isSourceSelectable, type KnowledgeSource } from "@/components/notebook/SourcePanel";
import StudioPanel from "@/components/notebook/StudioPanel";
import PathDag from "@/components/path/PathDag";
import LearningEvidence from "@/components/profile/LearningEvidence";
import MistakeBook from "@/components/profile/MistakeBook";
import ProfileRadar from "@/components/profile/ProfileRadar";
import ReviewQueue from "@/components/profile/ReviewQueue";
import ResourceCard from "@/components/resource/ResourceCard";
import AssessmentPanel from "@/components/assessment/AssessmentPanel";
import CourseRecommendations from "@/components/courses/CourseRecommendations";
import OnboardingGate from "@/components/onboarding/OnboardingGate";
import type { Assessment, StudySurvey, CourseScope } from "@/lib/assessment";
import CinematicBackground from "@/components/ui/CinematicBackground";
import { apiGet, apiPost, apiUpload, UNAUTHORIZED_EVENT, USER_ID } from "@/lib/api";
import { inferKpFromTopic, kpName } from "@/lib/kp";
import type { LearningNotebook, PathPlan, ResourceItem, SparkEvent, StudentProfile } from "@/lib/types";

type PanelKey = "chat" | "profile" | "path" | "resources" | "mistakes" | "assessment" | "courses";
type ResourceFilter = "all" | "doc" | "study" | "quiz" | "video" | "ppt";
type ChatRequest = { path: string; body: Record<string, unknown>; display: string };
type EvalReportSummary = { path?: PathPlan; profile_version?: number };
type OnboardingResponse = { required: boolean; profile: StudentProfile; path?: PathPlan | null; resume?: { phase: string; notebook_id: string; assessment_id: string }; recommendation?: { title?: string; reason?: string; knowledge_point?: string | null } };
type UploadResult = { source: KnowledgeSource; duplicate?: boolean; sample?: { text: string; citation: string }[] };
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
  { key: "study", label: "学习工件" },
  { key: "quiz", label: "测验" },
  { key: "video", label: "讲解" },
  { key: "ppt", label: "PPT" },
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

function latestUserQuestion(messages: LearningNotebook["messages"] | undefined): string {
  for (let index = (messages || []).length - 1; index >= 0; index -= 1) {
    const message = messages?.[index];
    if (message?.role === "user" && message.content.trim()) return message.content.trim();
  }
  return "";
}

function LearningGate({
  onStart,
  onManageSources,
  onLogout,
  user,
}: {
  onStart: (goal: string) => void;
  onManageSources: () => void;
  onLogout: () => void;
  user: AuthUser;
}) {
  const [goal, setGoal] = useState("");
  const [transitioning, setTransitioning] = useState(false);
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
              知行循证
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="hidden text-right sm:block">
              <div className="max-w-32 truncate text-sm font-semibold text-white">{user.name}</div>
              <div className="max-w-40 truncate text-[10px] text-white/50">{user.email}</div>
            </div>
            <button disabled={transitioning} onClick={onLogout} className="liquid-glass grid h-10 w-10 place-items-center rounded-full text-white/75 transition hover:text-white disabled:pointer-events-none" aria-label="退出登录" title="退出登录">
              <LogOut size={17} />
            </button>
            <button disabled={transitioning} onClick={() => document.getElementById("learning-goal")?.focus()} className="liquid-glass hidden items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium text-white transition-transform hover:scale-[1.03] disabled:pointer-events-none sm:flex">
              开始学习 <ArrowRight size={16} />
            </button>
          </div>
        </nav>

        <section className="learning-gate-hero cinematic-copy flex flex-1 flex-col items-center justify-center px-3 py-10 text-center lg:-translate-y-[2%]">
          <h1 className="animate-fade-rise max-w-6xl text-[35px] font-normal leading-tight text-white sm:text-6xl md:text-[72px]" style={{ fontFamily: "var(--font-display)" }}>
            <span className="block">让学习发生，</span>
            <em className="mt-1 block not-italic text-white/70">有据可循。</em>
          </h1>
          <p className="mt-5 max-w-lg text-sm leading-7 text-white/70">带上你的资料和目标，从理解一个概念、解决一道难题开始，在练习与反馈中找到下一步。</p>
          <Link href="/review" className="mt-4 text-sm text-white/90 underline underline-offset-4">先体验一次练习</Link>

          <div className="liquid-glass glass-readable animate-fade-rise-delay mt-7 flex w-full max-w-[760px] items-center gap-2 rounded-full p-2 pl-2.5 shadow-[0_24px_80px_rgba(0,16,27,0.28)]">
            <button
              type="button"
              onClick={onManageSources}
              disabled={transitioning}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-white/75 transition hover:bg-white/10 hover:text-white disabled:pointer-events-none"
              aria-label="进入工作台管理科目与资料"
              title="管理科目与资料"
            >
              <Plus size={21} />
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
          <p className="glass-readable mt-3 text-xs text-white/55">科目书本与学习资料在进入工作台后统一管理</p>
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

function NotebookCreateDialog({
  open,
  title,
  creating,
  error,
  onTitleChange,
  onClose,
  onCreate,
}: {
  open: boolean;
  title: string;
  creating: boolean;
  error: string;
  onTitleChange: (title: string) => void;
  onClose: () => void;
  onCreate: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70] grid place-items-center bg-[#101812]/35 p-4 backdrop-blur-sm" onMouseDown={() => !creating && onClose()}>
      <form className="w-full max-w-md rounded-3xl border border-white/70 bg-white p-6 shadow-[0_28px_90px_rgba(16,36,25,0.28)]" onSubmit={(event) => { event.preventDefault(); onCreate(); }} onMouseDown={(event) => event.stopPropagation()}>
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-emerald-100 text-2xl text-emerald-700">＋</div>
        <h2 className="mt-4 text-2xl font-black text-slate-950">新建科目书本</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">每本书都有独立的学习资料、对话和生成内容。创建后再向这本书上传讲义或笔记。</p>
        <label className="mt-5 block text-xs font-bold text-slate-700" htmlFor="new-book-title">书本名称或科目</label>
        <input id="new-book-title" autoFocus value={title} disabled={creating} onChange={(event) => onTitleChange(event.target.value)} placeholder="例如：高等数学 / 数据结构 / 英语写作" className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-900 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100 disabled:bg-slate-50" />
        {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
        <div className="mt-5 flex justify-end gap-2"><button type="button" disabled={creating} onClick={onClose} className="secondary-action">取消</button><button type="submit" disabled={creating || !title.trim()} className="primary-action">{creating ? "正在创建…" : "创建并进入"}</button></div>
      </form>
    </div>
  );
}

function EvidenceSummary({
  trace,
  quality,
  selectedSourceIds,
}: {
  trace: TraceState;
  quality: QualityEvidence;
  selectedSourceIds: string[];
}) {
  const personalCount = selectedSourceIds.filter((id) => id !== COURSE_SOURCE_ID).length;
  const courseSelected = selectedSourceIds.includes(COURSE_SOURCE_ID);
  const sourceLabel = [
    courseSelected ? "课程知识库" : "",
    personalCount ? `${personalCount} 份个人资料` : "",
  ].filter(Boolean).join(" + ") || "尚未选择";
  const qualityRows = [
    { label: "资料范围", value: sourceLabel },
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
  const [authStatus, setAuthStatus] = useState<"loading" | "authenticated" | "anonymous">("loading");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [entered, setEntered] = useState(false);
  const [onboardingRequired, setOnboardingRequired] = useState(false);
  const [onboardingLoading, setOnboardingLoading] = useState(true);
  const [onboardingError, setOnboardingError] = useState("");
  const [notebooks, setNotebooks] = useState<LearningNotebook[]>([]);
  const [activeNotebook, setActiveNotebook] = useState<LearningNotebook | null>(null);
  const [initialChatMessages, setInitialChatMessages] = useState<NonNullable<LearningNotebook["messages"]>>([]);
  const [notebookLoading, setNotebookLoading] = useState(false);
  const [openingNotebookId, setOpeningNotebookId] = useState("");
  const [libraryError, setLibraryError] = useState("");
  const [notebookTopic, setNotebookTopic] = useState("");
  const [conversationFocus, setConversationFocus] = useState("");
  const [chatSessionId, setChatSessionId] = useState("");
  const [chatInstance, setChatInstance] = useState(0);
  const [newBookOpen, setNewBookOpen] = useState(false);
  const [newBookTitle, setNewBookTitle] = useState("");
  const [creatingNotebook, setCreatingNotebook] = useState(false);
  const [createNotebookError, setCreateNotebookError] = useState("");
  const [activePanel, setActivePanel] = useState<PanelKey>("chat");
  const [courseKp, setCourseKp] = useState("");
  const [reduceTransparency, setReduceTransparency] = useState(false);
  useEffect(() => { try { setReduceTransparency(localStorage.getItem("sparklearn:reduce-transparency") === "true"); } catch { /* optional preference */ } }, []);
  const toggleTransparency = () => setReduceTransparency((value) => {
    try { localStorage.setItem("sparklearn:reduce-transparency", String(!value)); } catch { /* private browsing */ }
    return !value;
  });
  const [mobilePane, setMobilePane] = useState<"sources" | "studio" | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [traceDetailsOpen, setTraceDetailsOpen] = useState(false);
  const [trace, setTrace] = useState<TraceState>(emptyTrace());
  const [qualityEvidence, setQualityEvidence] = useState<QualityEvidence>(emptyQualityEvidence());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [seed, setSeed] = useState<string | undefined>();
  const [request, setRequest] = useState<ChatRequest | undefined>();
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [activeCourse, setActiveCourse] = useState<CourseScope | null>(null);
  const [pathPlan, setPathPlan] = useState<PathPlan | null>(null);
  const [selectedPathNode, setSelectedPathNode] = useState<string | null>(null);
  const [resources, setResources] = useState<ResourceItem[]>([]);
  const [resourceFilter, setResourceFilter] = useState<ResourceFilter>("all");
  const [panelError, setPanelError] = useState("");
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([COURSE_SOURCE_ID]);
  const [uploading, setUploading] = useState(false);
  const [uploadNote, setUploadNote] = useState("");
  const [uploadError, setUploadError] = useState(false);
  const sourceInputRef = useRef<HTMLInputElement>(null);
  const activeNotebookIdRef = useRef("");
  const notebookSwitchRef = useRef(0);

  useEffect(() => {
    let active = true;
    void apiGet<AuthUser>("/auth/me")
      .then((user) => {
        if (!active) return;
        setAuthUser(user);
        setAuthStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        setAuthUser(null);
        setAuthStatus("anonymous");
        setOnboardingLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const expireSession = () => {
      setAuthUser(null);
      setAuthStatus("anonymous");
      setEntered(false);
      setOnboardingRequired(false);
      setOnboardingLoading(false);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, expireSession);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expireSession);
  }, []);

  const running = useMemo(() => Object.values(trace).some((node) => node.status === "running"), [trace]);
  const finished = useMemo(() => Object.values(trace).some((node) => node.status === "done"), [trace]);
  const currentTopicTitle = useMemo(() => {
    const focus = conversationFocus.trim();
    if (!focus && activeNotebook) return "等待新问题";
    const resolvedFocus = focus || notebookTopic.trim();
    const kp = inferKpFromTopic(resolvedFocus);
    return kp ? kpName(kp) : resolvedFocus || "新的学习笔记";
  }, [activeNotebook, conversationFocus, notebookTopic]);

  const loadProfile = useCallback(async () => {
    setPanelError("");
    const notebookId = activeNotebookIdRef.current;
    try {
      const report = await apiGet<{ profile?: StudentProfile }>(`/eval/report?user_id=${USER_ID}&notebook_id=${encodeURIComponent(notebookId)}`);
      if (activeNotebookIdRef.current !== notebookId) return;
      if (report.profile) setProfile(report.profile);
      else setProfile(await apiGet<StudentProfile>(`/profile/${USER_ID}?notebook_id=${encodeURIComponent(notebookId)}`));
    } catch (error) {
      setPanelError(`学习情况暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const loadOnboarding = useCallback(async () => {
    setOnboardingLoading(true);
    setOnboardingError("");
    try {
      const data = await apiGet<OnboardingResponse>("/onboarding");
      setOnboardingRequired(Boolean(data.required));
      if (data.profile) setProfile(data.profile);
      if (data.path) {
        setPathPlan(data.path);
        setSelectedPathNode(data.path.next_kp || data.path.nodes[0]?.id || null);
      }
      if (!data.required) {
        setEntered(true);
        if (data.resume?.assessment_id && ["assessment", "plan"].includes(data.resume.phase)) {
          if (data.resume.notebook_id) {
            const notebook = await apiGet<LearningNotebook>(`/notebooks/${data.resume.notebook_id}?user_id=${USER_ID}`);
            enterNotebook(notebook);
            await loadSources(notebook.id);
            await loadProfile();
          }
          setActivePanel("assessment");
        }
      }
    } catch {
      setOnboardingError("暂时无法读取你的学习进度。请重试，已保存的选择和作答不会丢失。");
    } finally {
      setOnboardingLoading(false);
    }
  }, []);

  const loadPath = useCallback(async () => {
    setPanelError("");
    const notebookId = activeNotebookIdRef.current;
    try {
      const plan = await apiGet<PathPlan>(`/path?user_id=${USER_ID}&notebook_id=${encodeURIComponent(notebookId)}`);
      if (activeNotebookIdRef.current !== notebookId) return;
      setPathPlan(plan);
      setSelectedPathNode(null);
    } catch (error) {
      setPanelError(`知识关系暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const loadResources = useCallback(async () => {
    if (!activeNotebook) return;
    const notebookId = activeNotebook.id;
    setPanelError("");
    try {
      const data = await apiGet<{ items: ResourceItem[] }>(`/resources?user_id=${USER_ID}&notebook_id=${encodeURIComponent(notebookId)}&limit=30`);
      if (activeNotebookIdRef.current !== notebookId) return;
      setResources(data.items || []);
    } catch (error) {
      if (activeNotebookIdRef.current !== notebookId) return;
      setPanelError(`资料归档暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, [activeNotebook]);

  const loadSources = useCallback(async (notebookId: string) => {
    if (!notebookId) return;
    try {
      const [data, learning] = await Promise.all([
        apiGet<{ items: KnowledgeSource[] }>(`/knowledge/sources?user_id=${USER_ID}&notebook_id=${encodeURIComponent(notebookId)}`),
        apiGet<{ course: CourseScope }>(`/notebooks/${encodeURIComponent(notebookId)}/learning`),
      ]);
      if (activeNotebookIdRef.current !== notebookId) return;
      setActiveCourse(learning.course);
      const items = dedupeSources(data.items || []);
      setSources(items);
      setSelectedSourceIds((ids) => {
        const personal = items.filter(isSourceSelectable).map((item) => item.id);
        const available = new Set([
          ...(learning.course.kind === "ds_algo" ? [COURSE_SOURCE_ID] : []),
          ...items.filter(isSourceSelectable).map((item) => item.id),
        ]);
        const valid = ids.filter((id) => available.has(id));
        if (personal.length && valid.length === 1 && valid[0] === COURSE_SOURCE_ID) {
          return personal;
        }
        const bound = (learning.course.source_ids || []).filter(id => available.has(id));
        return valid.length ? valid : bound.length ? bound : personal.length ? personal : learning.course.kind === "ds_algo" ? [COURSE_SOURCE_ID] : [];
      });
    } catch (error) {
      if (activeNotebookIdRef.current !== notebookId) return;
      setUploadError(true);
      setUploadNote(`学习资料暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const loadNotebooks = useCallback(async () => {
    setNotebookLoading(true);
    setLibraryError("");
    try {
      const data = await apiGet<{ items: LearningNotebook[] }>(`/notebooks?user_id=${USER_ID}`);
      const items = data.items || [];
      setNotebooks(items);
      setActiveNotebook((current) => {
        if (!current) return null;
        const refreshed = items.find((item) => item.id === current.id);
        return refreshed ? { ...current, ...refreshed, messages: current.messages } : null;
      });
    } catch (error) {
      setLibraryError(`书本列表暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setNotebookLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authStatus === "authenticated") void loadNotebooks();
  }, [authStatus, loadNotebooks]);

  useEffect(() => {
    if (authStatus !== "authenticated") return;
    if (authUser?.demo) {
      setOnboardingRequired(false);
      setOnboardingLoading(false);
      setEntered(true);
      return;
    }
    void loadOnboarding();
  }, [authStatus, authUser?.demo, loadOnboarding]);

  const uploadSources = async (files: File[]) => {
    if (!files.length || uploading || !activeNotebook) return;
    const uploadNotebookId = activeNotebook.id;
    setUploading(true);
    setUploadNote("");
    setUploadError(false);
    const completed: { source: KnowledgeSource; duplicate: boolean }[] = [];
    const failures: string[] = [];
    try {
      for (const file of files) {
        setUploadNote(`正在解析「${file.name}」…`);
        try {
          const form = new FormData();
          form.append("file", file);
          form.append("user_id", USER_ID);
          form.append("notebook_id", uploadNotebookId);
          form.append("title", file.name.replace(/\.[^.]+$/, ""));
          const result = await apiUpload<UploadResult>("/knowledge/upload", form);
          completed.push({ source: result.source, duplicate: Boolean(result.duplicate) });
        } catch (error) {
          failures.push(`${file.name}：${error instanceof Error ? error.message : String(error)}`);
        }
      }
      if (completed.length) {
        const completedSources = completed.map((item) => item.source).reverse();
        setSources((items) => dedupeSources([...completedSources, ...items]));
        setSelectedSourceIds((ids) => Array.from(new Set([
          ...ids.filter((id) => id !== COURSE_SOURCE_ID),
          ...completedSources.filter(isSourceSelectable).map((source) => source.id),
        ])));
      }
      const freshCount = completed.filter((item) => !item.duplicate).length;
      const duplicateCount = completed.length - freshCount;
      setUploadError(failures.length > 0);
      setUploadNote([
        freshCount ? `已加入 ${freshCount} 份资料并自动选中` : "",
        duplicateCount ? `${duplicateCount} 份资料已在当前书本中` : "",
        ...failures,
      ].filter(Boolean).join("；"));
      if (activeNotebookIdRef.current !== uploadNotebookId) {
        if (completed.length) void loadNotebooks();
        return;
      }
      if (completed.length) {
        void loadNotebooks();
      }
    } finally {
      setUploading(false);
    }
  };

  const toggleCourseSource = () => setSelectedSourceIds((ids) => (
    ids.includes(COURSE_SOURCE_ID)
      ? ids.length > 1 ? ids.filter((id) => id !== COURSE_SOURCE_ID) : ids
      : [COURSE_SOURCE_ID, ...ids]
  ));

  const togglePersonalSource = (sourceId: string) => setSelectedSourceIds((ids) => (
    ids.includes(sourceId)
      ? ids.length > 1 ? ids.filter((id) => id !== sourceId) : ids
      : [...ids, sourceId]
  ));

  const enterNotebook = (notebook: LearningNotebook, initialGoal = "") => {
    const goal = initialGoal.trim();
    activeNotebookIdRef.current = notebook.id;
    setActiveNotebook(notebook);
    setProfile(null);
    setActiveCourse(null);
    setPathPlan(null);
    setEntered(true);
    setNotebookTopic(notebook.title);
    setConversationFocus(goal || latestUserQuestion(notebook.messages));
    setChatSessionId(notebook.session_id);
    setInitialChatMessages(notebook.messages || []);
    setSources([]);
    setSelectedSourceIds([COURSE_SOURCE_ID]);
    setResources([]);
    setActivePanel("chat");
    setTrace(emptyTrace());
    setQualityEvidence(emptyQualityEvidence());
    setSeed(goal || undefined);
    setRequest(undefined);
    setPanelError("");
    setMobilePane(null);
    setChatInstance((value) => value + 1);
  };

  const openNotebook = async (notebook: LearningNotebook, initialGoal = ""): Promise<boolean> => {
    const switchToken = notebookSwitchRef.current + 1;
    notebookSwitchRef.current = switchToken;
    activeNotebookIdRef.current = notebook.id;
    setOpeningNotebookId(notebook.id);
    setLibraryError("");
    enterNotebook({ ...notebook, messages: [] });
    try {
      const detail = await apiGet<LearningNotebook>(`/notebooks/${encodeURIComponent(notebook.id)}?user_id=${USER_ID}`);
      if (notebookSwitchRef.current !== switchToken || activeNotebookIdRef.current !== notebook.id) return false;
      enterNotebook(detail, initialGoal);
      await loadSources(detail.id);
      await loadProfile();
      return true;
    } catch (error) {
      if (notebookSwitchRef.current !== switchToken) return false;
      setLibraryError(`这本书暂时无法打开：${error instanceof Error ? error.message : String(error)}`);
      return false;
    } finally {
      if (notebookSwitchRef.current === switchToken) setOpeningNotebookId("");
    }
  };

  const enterCourseWorkspace = (goal = "", sendGoal = false) => {
    const next = goal.trim();
    notebookSwitchRef.current += 1;
    activeNotebookIdRef.current = "";
    setActiveNotebook(null);
    setEntered(true);
    setNotebookTopic(next || "课程学习");
    setConversationFocus(next);
    setChatSessionId("");
    setInitialChatMessages([]);
    setSources([]);
    setSelectedSourceIds([COURSE_SOURCE_ID]);
    setResources([]);
    setActivePanel("chat");
    setTrace(emptyTrace());
    setQualityEvidence(emptyQualityEvidence());
    setSeed(sendGoal ? next || undefined : undefined);
    setRequest(undefined);
    setPanelError("");
    setMobilePane(null);
    setChatInstance((value) => value + 1);
  };

  const startLearning = async (goal: string) => {
    if (activeNotebook && await openNotebook(activeNotebook, goal)) return;
    enterCourseWorkspace(goal, true);
  };

  const recommendationTitle = (path: PathPlan | null = pathPlan) => {
    const node = path ? path.nodes.find((item) => item.id === path.next_kp) : undefined;
    return node?.name || activeCourse?.title || activeNotebook?.title || "课程基础";
  };

  const firstTaskPrompt = (path: PathPlan | null = pathPlan) => {
    const title = recommendationTitle(path);
    return `请带我开始“${title}”的第一项学习任务。先用一句话说清今天要学什么，再给我一个可以马上作答的小问题。`;
  };

  const completeIntake = async (survey: StudySurvey, mode: Assessment["mode"]) => {
    const assessment = await apiPost<Assessment>("/assessment/start", { survey, mode });
    setOnboardingRequired(false);
    if (assessment.notebook_id) {
      const notebook = await apiGet<LearningNotebook>(`/notebooks/${assessment.notebook_id}?user_id=${USER_ID}`);
      await openNotebook(notebook);
      await loadNotebooks();
    } else enterCourseWorkspace();
    await loadProfile();
    setActivePanel("assessment");
  };

  const assessmentStarted = async (assessment: Assessment) => {
    if (assessment.notebook_id && assessment.notebook_id !== activeNotebookIdRef.current) {
      const notebook = await apiGet<LearningNotebook>(`/notebooks/${assessment.notebook_id}?user_id=${USER_ID}`);
      await openNotebook(notebook);
      await loadNotebooks();
      setActivePanel("assessment");
    }
    await loadProfile();
  };

  const skipIntake = async (introPracticed: boolean) => {
    const result = await apiPost<OnboardingResponse>("/onboarding", { skipped: true,
      ...(introPracticed ? { survey: { intro_practiced: true, stage: "不方便回答", prior_experience: "不方便回答" } } : {}),
    });
    setOnboardingRequired(false);
    setProfile(result.profile);
    if (result.path) setPathPlan(result.path);
    enterCourseWorkspace();
  };

  const manageSources = async () => {
    if (activeNotebook) await openNotebook(activeNotebook);
    else enterCourseWorkspace();
    setMobilePane("sources");
  };

  const createNotebook = async () => {
    const title = newBookTitle.trim();
    if (!title || creatingNotebook) return;
    setCreatingNotebook(true);
    setCreateNotebookError("");
    try {
      const notebook = await apiPost<LearningNotebook>("/notebooks", { user_id: USER_ID, title });
      setNotebooks((items) => [notebook, ...items]);
      setNewBookTitle("");
      setNewBookOpen(false);
      notebookSwitchRef.current += 1;
      enterNotebook(notebook);
    } catch (error) {
      setCreateNotebookError(`创建失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setCreatingNotebook(false);
    }
  };

  const startNewConversation = async () => {
    if (!activeNotebook || openingNotebookId) return;
    if (running) {
      setPanelError("当前内容仍在生成，请先停止当前任务，再新开对话。");
      return;
    }
    const notebookId = activeNotebook.id;
    const switchToken = notebookSwitchRef.current + 1;
    notebookSwitchRef.current = switchToken;
    activeNotebookIdRef.current = notebookId;
    setOpeningNotebookId(notebookId);
    setPanelError("");
    try {
      const notebook = await apiPost<LearningNotebook>(
        `/notebooks/${encodeURIComponent(notebookId)}/conversations`,
        { user_id: USER_ID },
      );
      if (notebookSwitchRef.current !== switchToken || activeNotebookIdRef.current !== notebookId) return;
      setActiveNotebook(notebook);
      setNotebooks((items) => items.map((item) => item.id === notebook.id ? { ...item, ...notebook } : item));
      setNotebookTopic(notebook.title);
      setConversationFocus("");
      setChatSessionId(notebook.session_id);
      setInitialChatMessages([]);
      setActivePanel("chat");
      setTrace(emptyTrace());
      setQualityEvidence(emptyQualityEvidence());
      setSeed(undefined);
      setRequest(undefined);
      setMobilePane(null);
      setChatInstance((value) => value + 1);
    } catch (error) {
      if (notebookSwitchRef.current === switchToken) {
        setPanelError(`新对话暂时无法创建：${error instanceof Error ? error.message : String(error)}`);
      }
    } finally {
      if (notebookSwitchRef.current === switchToken) setOpeningNotebookId("");
    }
  };

  const leave = () => {
    notebookSwitchRef.current += 1;
    activeNotebookIdRef.current = "";
    setEntered(false);
    setActivePanel("chat");
    setTrace(emptyTrace());
    setQualityEvidence(emptyQualityEvidence());
    setSeed(undefined);
    setRequest(undefined);
    setConversationFocus("");
    setChatSessionId("");
    setInitialChatMessages([]);
    setSources([]);
    setSelectedSourceIds([COURSE_SOURCE_ID]);
    setEvidenceOpen(false);
    setMobilePane(null);
    void loadNotebooks();
  };

  const logout = async () => {
    try {
      await apiPost<{ ok: boolean }>("/auth/logout", {});
    } finally {
      notebookSwitchRef.current += 1;
      activeNotebookIdRef.current = "";
      setAuthUser(null);
      setAuthStatus("anonymous");
      setEntered(false);
      setNotebooks([]);
      setActiveNotebook(null);
      setNotebookTopic("");
      setConversationFocus("");
      setChatSessionId("");
      setSources([]);
      setSelectedSourceIds([COURSE_SOURCE_ID]);
      setResources([]);
      setProfile(null);
      setPathPlan(null);
      setSessionId(null);
    }
  };

  const startGenerate = (label: string, goal: string, kinds: string[], promptTemplate: string) => {
    if (!activeNotebook) {
      setCreateNotebookError("请先在左侧学习来源中新建或选择一个科目书本。");
      setNewBookOpen(true);
      return;
    }
    if (openingNotebookId) {
      setPanelError("正在切换书本，上一书本内容已清空，请稍候再生成。");
      return;
    }
    const conversationWide = promptTemplate === "framework";
    const focus = conversationFocus.trim();
    if (!conversationWide && !focus) {
      setActivePanel("chat");
      setMobilePane(null);
      setPanelError("请先在当前对话里问一个具体问题，再生成笔记、音频、闪卡或视频。这样不会误用旧主题。");
      return;
    }
    const topicKp = inferKpFromTopic(focus);
    const scopedGoal = !conversationWide && focus
      ? `${goal}\n\n请以最近学习对话中的实际问题为准：${focus}`
      : goal;
    setActivePanel("chat");
    setMobilePane(null);
    setTrace(emptyTrace());
    setQualityEvidence(emptyQualityEvidence());
    setSeed(undefined);
    setRequest({
      path: "/resources/generate",
      display: conversationWide
        ? "把本次学习对话整理成框架导图"
        : focus ? `把刚才讨论的内容做成${label}` : `生成${label}`,
      body: {
        user_id: USER_ID,
        session_id: activeNotebook.session_id || chatSessionId,
        notebook_id: activeNotebook.id,
        goal: scopedGoal,
        conversation_focus: focus,
        topic_label: "",
        knowledge_points: topicKp ? [topicKp] : [],
        kinds,
        source_ids: selectedSourceIds,
        prompt_template: promptTemplate,
        artifact_scope: conversationWide ? "conversation" : "current_topic",
      },
    });
  };

  const openPanel = (panel: Exclude<PanelKey, "chat">) => {
    setActivePanel(panel);
    setMobilePane(null);
    if (panel === "profile") void loadProfile();
    if (panel === "path") void loadPath();
    if (panel === "resources") void loadResources();
    if (panel === "courses") setCourseKp("");
  };

  const refreshAfterEvaluation = useCallback((report?: EvalReportSummary) => {
    if (report?.path) {
      setPathPlan(report.path);
      setSelectedPathNode(report.path.next_kp || report.path.nodes[0]?.id || null);
    }
    void loadProfile();
  }, [loadProfile]);

  const onEvent = useCallback((event: SparkEvent, originNotebookId = "") => {
    if (originNotebookId && activeNotebookIdRef.current !== originNotebookId) return;
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
    const learnerResources = resources.filter((item) => !["manim", "python_animation"].includes(item.kind));
    if (resourceFilter === "all") return learnerResources;
    if (resourceFilter === "doc") return learnerResources.filter((item) => ["doc", "code", "reading"].includes(item.kind));
    if (resourceFilter === "study") return learnerResources.filter((item) => ["mindmap", "flashcards", "infographic", "data_table"].includes(item.kind));
    return learnerResources.filter((item) => item.kind === resourceFilter);
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

  if (authStatus === "loading") {
    return (
      <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-[#062B38] text-white">
        <CinematicBackground subdued />
        <div className="relative z-10 flex items-center gap-3 rounded-full border border-white/15 bg-white/10 px-5 py-3 text-sm backdrop-blur-xl">
          <SparkMark light running /> 正在恢复你的学习空间…
        </div>
      </main>
    );
  }

  if (authStatus === "anonymous" || !authUser) {
    return (
      <AuthGate
        onAuthenticated={(user) => {
          setAuthUser(user);
          setAuthStatus("authenticated");
          setOnboardingLoading(true);
          setOnboardingRequired(false);
          setEntered(false);
        }}
      />
    );
  }

  if (onboardingLoading) {
    return (
      <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-[#062B38] text-white">
        <CinematicBackground subdued />
        <div className="relative z-10 flex items-center gap-3 rounded-full border border-white/15 bg-white/10 px-5 py-3 text-sm backdrop-blur-xl">
          <SparkMark light running /> 正在准备你的学习起点…
        </div>
      </main>
    );
  }

  if (onboardingError) {
    return <main className="onboarding-retry"><h1>继续你的学习起点</h1><p role="alert">{onboardingError}</p><button className="primary-action" onClick={() => void loadOnboarding()}>重试读取学习进度</button><button className="secondary-action" onClick={() => void logout()}>退出登录</button></main>;
  }

  if (!entered && onboardingRequired) {
    return <OnboardingGate user={authUser} onComplete={completeIntake} onSkip={skipIntake} onLogout={() => void logout()} />;
  }

  if (!entered) {
    return (
      <LearningGate
        user={authUser}
        onStart={(goal) => void startLearning(goal)}
        onManageSources={() => void manageSources()}
        onLogout={() => void logout()}
      />
    );
  }

  const sourcePanel = (
    <SourcePanel
      includeBuiltin={!activeNotebook || activeCourse?.kind === "ds_algo"}
      notebooks={notebooks}
      activeNotebookId={activeNotebook?.id}
      notebookLoading={notebookLoading || Boolean(openingNotebookId)}
      notebookError={libraryError}
      sources={sources}
      selectedIds={selectedSourceIds}
      uploading={uploading}
      uploadNote={uploadNote}
      uploadError={uploadError}
      onAdd={() => activeNotebook ? sourceInputRef.current?.click() : setNewBookOpen(true)}
      onCreateNotebook={() => { setCreateNotebookError(""); setNewBookOpen(true); }}
      onSelectNotebook={(notebookId) => {
        const notebook = notebooks.find((item) => item.id === notebookId);
        if (notebook) void openNotebook(notebook);
      }}
      onToggleCourse={toggleCourseSource}
      onToggle={togglePersonalSource}
    />
  );
  const studioPanel = <StudioPanel onGenerate={startGenerate} onOpen={openPanel} disabled={Boolean(openingNotebookId)} />;
  const profilePace = asRecord(profile?.pace);

  return (
    <main data-transparency={reduceTransparency ? "reduced" : "standard"} className="notebook-app notebook-app-enter flex h-dvh flex-col overflow-hidden text-[#1D2028]">
      <input
        ref={sourceInputRef}
        type="file"
        multiple
        accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg"
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files || []);
          event.currentTarget.value = "";
          if (files.length) void uploadSources(files);
        }}
      />

      <header className="notebook-topbar relative z-20 flex h-[68px] shrink-0 items-center gap-3 px-4 sm:px-5">
        <button onClick={() => setActivePanel("chat")} className="flex items-center gap-2.5" title="返回学习对话">
          <SparkMark running={running} />
          <strong className="hidden text-lg tracking-tight sm:block">知行循证</strong>
        </button>
        <span className="hidden h-5 w-px bg-[#DDE0E8] sm:block" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-[#343944]">{activeNotebook ? `${activeNotebook.emoji} ${activeNotebook.title}` : "我的学习工作台"}</div>
          <div className="hidden text-[11px] text-[#818795] sm:block">当前主题：{currentTopicTitle} · 已选 {selectedSourceIds.length} 项资料</div>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={() => openPanel("assessment")} className="notebook-home-button" aria-label="打开起点测评"><Target size={16} /><span className="hidden sm:inline">测评与计划</span></button>
          <button onClick={toggleTransparency} className="notebook-icon-button" aria-label="减少透明效果" aria-pressed={reduceTransparency} title="减少透明效果"><Contrast size={17} /></button>
          <button onClick={() => setMobilePane("sources")} className="notebook-icon-button hidden sm:grid xl:hidden" aria-label="打开学习来源"><PanelLeftOpen size={18} /></button>
          <button onClick={() => setMobilePane("studio")} className="notebook-icon-button hidden sm:grid xl:hidden" aria-label="打开学习工坊"><PanelRightOpen size={18} /></button>
          <span className={`hidden rounded-full px-3 py-1.5 text-xs font-semibold sm:inline-flex ${running ? "bg-[#FFF1DD] text-[#9A5B12]" : finished ? "bg-[#E8F4ED] text-[#0F6B50]" : "bg-[#F0F1F5] text-[#626978]"}`}>
            {running ? "正在整理" : finished ? "已经完成" : "准备就绪"}
          </span>
          <button onClick={leave} className="notebook-home-button" title="返回学习首页">
            <BookOpen size={16} />
            <span className="hidden sm:inline">学习首页</span>
          </button>
          <button onClick={() => setEvidenceOpen(true)} className="notebook-evidence-button">
            <ShieldCheck size={16} /><span className="hidden sm:inline">依据</span>
          </button>
          <div className="hidden max-w-28 truncate text-xs font-semibold text-[#626978] lg:block" title={authUser.email}>{authUser.name}</div>
          <button onClick={() => void logout()} className="notebook-icon-button" aria-label="退出登录" title="退出登录">
            <LogOut size={17} />
          </button>
        </div>
      </header>

      <div className="notebook-layout min-h-0 flex-1">
        <aside className="hidden min-h-0 xl:block">{sourcePanel}</aside>

        <section className="notebook-column relative min-h-0 overflow-hidden">
          {activePanel === "chat" && profile?.learning_intake && <div className="learning-context-strip"><div><strong>{profile.course_title || activeNotebook?.title}</strong><span>优先：{profile.learning_intake.goal} · 每次 {profile.learning_intake.daily_minutes} 分钟 · 已绑定 {activeCourse?.source_ids?.length || 0} 份资料</span></div><button onClick={() => openPanel("assessment")}>查看依据与计划 <ArrowRight size={14} /></button></div>}
          {openingNotebookId && (
            <div className="absolute inset-0 z-40 grid place-items-center bg-white/82 px-6 text-center backdrop-blur-sm">
              <div className="rounded-2xl border border-emerald-200 bg-white px-6 py-5 shadow-xl">
                <div className="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" />
                <strong className="mt-3 block text-sm text-slate-900">正在切换到干净的书本上下文</strong>
                <span className="mt-1 block text-xs leading-5 text-slate-500">上一书本的对话、主题和生成状态已经停止回写。</span>
              </div>
            </div>
          )}
          {panelError && <div className="m-3 rounded-[8px] border border-[#F1D6C9] bg-[#FFF6F1] px-4 py-3 text-sm text-[#9E4B2D]">{panelError}</div>}

          <div className={`h-full min-h-0 ${activePanel === "chat" ? "block" : "hidden"}`} aria-hidden={activePanel !== "chat"}>
            <Chat
              key={`${activeNotebook?.id || "course"}-${chatInstance}`}
              onEvent={(event) => onEvent(event, activeNotebook?.id || "")}
              seed={seed}
              request={request}
              notebookId={activeNotebook?.id}
              sessionId={activeNotebook?.session_id || chatSessionId}
              initialMessages={initialChatMessages}
              topic={conversationFocus || notebookTopic}
              sourceIds={selectedSourceIds}
              onUploadClick={() => activeNotebook ? sourceInputRef.current?.click() : setNewBookOpen(true)}
              onCreateNotebook={() => { setCreateNotebookError(""); setNewBookOpen(true); }}
              onNewConversation={activeNotebook ? () => void startNewConversation() : undefined}
              onSeedConsumed={() => { setSeed(undefined); setRequest(undefined); }}
              onLearningTurn={setConversationFocus}
              onSessionReady={setChatSessionId}
              onQuizEvaluated={refreshAfterEvaluation}
              onOpenMistakes={() => openPanel("mistakes")}
              recommendedTask={pathPlan ? {
                title: recommendationTitle(),
                prompt: firstTaskPrompt(),
                reason: pathPlan.nodes.find((node) => node.id === pathPlan.next_kp)?.reason || "根据你的学习画像安排",
              } : undefined}
              onOpenPath={() => openPanel("path")}
              onOpenAssessment={() => openPanel("assessment")}
            />
          </div>

          {activePanel === "assessment" && <AssessmentPanel key={activeNotebook?.id || "initial"} notebookId={activeNotebook?.id || ""} onStarted={assessmentStarted} initialSurvey={{ course_title: activeCourse?.title || activeNotebook?.title || "", course_key: "custom", source_ids: selectedSourceIds.filter(id => id !== COURSE_SOURCE_ID), ...profile?.learning_intake }} onBack={() => setActivePanel("chat")} onLearn={(prompt) => void startLearning(prompt)} onCourses={(kp = "") => { setCourseKp(kp); setActivePanel("courses"); }} onUpdated={() => { void loadProfile(); void loadPath(); }} />}
          {activePanel === "courses" && <CourseRecommendations key={activeNotebook?.id || "global"} notebookId={activeNotebook?.id} initialKp={courseKp} onBack={() => setActivePanel("chat")} onAssess={() => openPanel("assessment")} />}
          {activePanel === "profile" && (
            <div className="notebook-content-scroll">
              <div className="notebook-content-heading">
                <div><span>LEARNING PROFILE</span><h1>我的学习情况</h1><p>每次独立作答积累证据；初始先验不代表实际成绩。</p></div>
                <div className="flex items-center gap-2"><button onClick={() => { setOnboardingRequired(true); setEntered(false); setOnboardingLoading(false); }} className="secondary-action">调整学习起点</button><button onClick={() => void loadProfile()} className="secondary-action">刷新</button></div>
              </div>
              <div className="px-5 pt-5">
                <button className="entry-profile-cta" onClick={() => openPanel("assessment")}><Target size={20} /><span><strong>查看起点测评与两周计划</strong><small>真实题目、逐题解析、按时间安排的学习任务</small></span><ArrowRight size={18} /></button>
                <ReviewQueue key={activeNotebook?.id || "global"} notebookId={activeNotebook?.id} onEvaluated={refreshAfterEvaluation} />
              </div>
              <div className="px-5 pt-4">
                <LearningEvidence key={activeNotebook?.id || "legacy"} notebookId={activeNotebook?.id || ""} refreshToken={profile?._version ?? profile?.version ?? 0} />
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
                    {groupedResources.map((group) => <ResourceCard key={group.key} r={group.representative} versionCount={group.versionCount} onQuizEvaluated={refreshAfterEvaluation} onOpenMistakes={() => openPanel("mistakes")} />)}
                  </div>
                ) : <div className="source-empty min-h-[220px]"><FolderOpen size={24} /><strong>这里还没有资料</strong><span>从右侧学习工坊生成一份内容。</span></div>}
              </div>
            </div>
          )}

          {activePanel === "mistakes" && (
            <div className="notebook-content-scroll">
              <div className="notebook-content-heading">
                <div><span>MISTAKE BOOK</span><h1>我的错题本</h1><p>答错或揭晓的题自动收录；可以收藏、查看错因并随时重做。</p></div>
              </div>
              <div className="p-5"><MistakeBook key={activeNotebook?.id || "global"} notebookId={activeNotebook?.id} onEvaluated={refreshAfterEvaluation} /></div>
            </div>
          )}

        </section>

        <aside className="hidden min-h-0 xl:block">{studioPanel}</aside>
      </div>

      <nav className="notebook-mobile-nav xl:hidden" aria-label="移动端学习工作台导航">
        <button type="button" onClick={() => setMobilePane("sources")}><PanelLeftOpen size={17} /><span>学习来源</span></button>
        <button type="button" className="is-active" onClick={() => { setActivePanel("chat"); setMobilePane(null); }}><BookOpen size={17} /><span>学习对话</span></button>
        <button type="button" onClick={() => setMobilePane("studio")}><PanelRightOpen size={17} /><span>学习工坊</span></button>
      </nav>

      {mobilePane && (
        <div className="notebook-mobile-scrim fixed inset-0 z-40 xl:hidden" onClick={() => setMobilePane(null)}>
          <div className={`notebook-mobile-sheet absolute inset-y-0 w-[min(88vw,360px)] p-3 shadow-2xl ${mobilePane === "sources" ? "left-0" : "right-0"}`} onClick={(event) => event.stopPropagation()}>
            <button onClick={() => setMobilePane(null)} className="notebook-mobile-sheet-close absolute right-5 top-5 z-10 grid h-8 w-8 place-items-center rounded-full text-[#596171] shadow-sm" aria-label="关闭"><X size={17} /></button>
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
          <EvidenceSummary trace={trace} quality={qualityEvidence} selectedSourceIds={selectedSourceIds} />
          <button onClick={() => setTraceDetailsOpen((open) => !open)} className="mt-3 flex w-full items-center justify-between rounded-[8px] border border-white/10 bg-white/[0.05] px-3 py-2.5 text-left text-sm font-semibold text-white">
            <span>{traceDetailsOpen ? "收起详细过程" : "查看详细过程"}</span><span>⌄</span>
          </button>
          {traceDetailsOpen && <div className="mt-3"><AgentTrace trace={trace} />{sessionId && <div className="mt-3 rounded-[8px] border border-white/10 bg-black/10 px-3 py-2 font-mono text-[11px] text-white/55">运行编号：{sessionId}</div>}</div>}
        </div>
      </section>

      <NotebookCreateDialog
        open={newBookOpen}
        title={newBookTitle}
        creating={creatingNotebook}
        error={createNotebookError}
        onTitleChange={setNewBookTitle}
        onClose={() => setNewBookOpen(false)}
        onCreate={() => void createNotebook()}
      />

    </main>
  );
}
