"use client";

import {
  ArrowRight,
  ArrowLeft,
  BookOpen,
  ChevronDown,
  FolderOpen,
  LogOut,
  PanelLeftOpen,
  PanelRightOpen,
  Route,
  ShieldCheck,
  SquarePen,
  Target,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AgentTrace, { applyTraceEvent, emptyTrace, type TraceState } from "@/components/agent/AgentTrace";
import AuthGate, { type AuthUser } from "@/components/auth/AuthGate";
import Chat from "@/components/chat/Chat";
import CourseCreateDialog from "@/components/notebook/CourseCreateDialog";
import SourcePanel, { COURSE_SOURCE_ID, isSourceSelectable, type KnowledgeSource } from "@/components/notebook/SourcePanel";
import StudioPanel, { GENERATORS } from "@/components/notebook/StudioPanel";
import type { StudyStage, SuggestedTool } from "@/lib/learning-guidance";
import PathDag from "@/components/path/PathDag";
import LearningEvidence from "@/components/profile/LearningEvidence";
import MistakeBook from "@/components/profile/MistakeBook";
import ProfileRadar from "@/components/profile/ProfileRadar";
import ReviewQueue from "@/components/profile/ReviewQueue";
import ResourceCard from "@/components/resource/ResourceCard";
import AssessmentPanel from "@/components/assessment/AssessmentPanel";
import LearningGuide from "@/components/onboarding/LearningGuide";
import type { CoachAction } from "@/components/onboarding/StudyCoach";
import ResearchPanel from "@/components/learning/ResearchPanel";
import GenerationJobs from "@/components/learning/GenerationJobs";
import EnglishScenes from "@/components/learning/EnglishScenes";
import CourseStudyPanel from "@/components/learning/CourseStudyPanel";
import ReadingProgress from "@/components/learning/ReadingProgress";
import CourseRecommendations from "@/components/courses/CourseRecommendations";
import OnboardingGate from "@/components/onboarding/OnboardingGate";
import type { Assessment, StudySurvey, CourseScope } from "@/lib/assessment";
import CinematicBackground from "@/components/ui/CinematicBackground";
import AdaptiveMenu from "@/components/ui/AdaptiveMenu";
import StudyDialog from "@/components/ui/StudyDialog";
import { LearnerScope, useStudyViewport } from "@/lib/study-workspace";
import { apiGet, apiPost, apiUpload, UNAUTHORIZED_EVENT, USER_ID } from "@/lib/api";
import { inferKpFromTopic, kpName } from "@/lib/kp";
import type { LearningNotebook, PathPlan, ResourceItem, SparkEvent, StudentProfile } from "@/lib/types";

type PanelKey = "study" | "research" | "english" | "chat" | "profile" | "path" | "resources" | "mistakes" | "assessment" | "courses";
type ResourceFilter = "all" | "doc" | "study" | "quiz" | "video" | "ppt";
type ChatRequest = { path: string; body: Record<string, unknown>; display: string };
type EvalReportSummary = { path?: PathPlan; profile_version?: number };
type OnboardingResponse = { required: boolean; profile: StudentProfile; path?: PathPlan | null; resume?: { phase: string; notebook_id: string; assessment_id: string }; recommendation?: { title?: string; reason?: string; knowledge_point?: string | null } };
type UploadResult = { source: KnowledgeSource; duplicate?: boolean; sample?: { text: string; citation: string }[] };
type QualityEvidence = {
  retrievalCount: number | null;
  knowledgePoint: string;
  grounded: boolean | null;
  verification: string;
  verdict: string;
  citationCount: number | null;
  degradedReason: string;
  promptCapability: string;
};

const emptyQualityEvidence = (): QualityEvidence => ({
  retrievalCount: null,
  knowledgePoint: "",
  grounded: null,
  verification: "",
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
    { label: "回答溯源", value: quality.grounded == null ? "等待检查" : quality.verification === "citation_only" ? "仅编号有效，待核对" : quality.verification === "lexical_overlap" ? "仅关键词关联，待核对" : quality.grounded ? "已完成来源检查" : "需要复核" },
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
  useStudyViewport();
  const [readingFocus, setReadingFocus] = useState(false);
  const [sourcesCollapsed, setSourcesCollapsed] = useState(false);
  const [studioCollapsed, setStudioCollapsed] = useState(false);
  const [sourceWidth, setSourceWidth] = useState(280);
  const [authStatus, setAuthStatus] = useState<"loading" | "authenticated" | "anonymous">("loading");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [entered, setEntered] = useState(false);
  const [onboardingRequired, setOnboardingRequired] = useState(false);
  const [onboardingLoading, setOnboardingLoading] = useState(true);
  const [onboardingError, setOnboardingError] = useState("");
  const [notebooks, setNotebooks] = useState<LearningNotebook[]>([]);
  const [activeNotebook, setActiveNotebook] = useState<LearningNotebook | null>(null);
  const [initialChatMessages, setInitialChatMessages] = useState<NonNullable<LearningNotebook["messages"]>>([]);
  const [sourcePolicies, setSourcePolicies] = useState<Record<string, "auto" | "strict" | "supplement">>({});
  const [notebookLoading, setNotebookLoading] = useState(false);
  const [openingNotebookId, setOpeningNotebookId] = useState("");
  const [libraryError, setLibraryError] = useState("");
  const [notebookTopic, setNotebookTopic] = useState("");
  const [conversationFocus, setConversationFocus] = useState("");
  const [chatSessionId, setChatSessionId] = useState("");
  const [chatInstance, setChatInstance] = useState(0);
  const [chatBusy, setChatBusy] = useState(false);
  const [studyStage, setStudyStage] = useState<StudyStage>("start");
  const [newBookOpen, setNewBookOpen] = useState(false);
  const [activePanel, setActivePanel] = useState<PanelKey>("chat");
  const [courseKp, setCourseKp] = useState("");
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
  const [studyUnit, setStudyUnit] = useState({ id: "", request: 0 });
  const pendingStudyNotebook = useRef("");
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
  const activeNotebookIdRef = useRef("");
  const notebookSwitchRef = useRef(0);
  const accountEpochRef = useRef(0);

  const clearSession = useCallback(() => {
    accountEpochRef.current += 1;
    notebookSwitchRef.current += 1;
    activeNotebookIdRef.current = "";
    setAuthUser(null); setAuthStatus("anonymous"); setEntered(false);
    setOnboardingRequired(false); setOnboardingLoading(false); setOnboardingError("");
    setNotebooks([]); setActiveNotebook(null); setInitialChatMessages([]);
    setNotebookTopic(""); setConversationFocus(""); setChatSessionId(""); setSessionId(null);
    setSources([]); setSelectedSourceIds([]); setResources([]); setSourcePolicies({});
    setProfile(null); setPathPlan(null); setActiveCourse(null); setSelectedPathNode(null);
    setSeed(undefined); setRequest(undefined); setTrace(emptyTrace()); setQualityEvidence(emptyQualityEvidence());
    setOpeningNotebookId(""); setNewBookOpen(false); setMobilePane(null); setEvidenceOpen(false);
    setPanelError(""); setLibraryError(""); setUploadNote(""); setUploadError(false);
    setActivePanel("chat"); setChatInstance(value => value + 1);
  }, []);

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
    window.addEventListener(UNAUTHORIZED_EVENT, clearSession);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, clearSession);
  }, [clearSession]);

  // Preferences are local to this account and course, including after reload.
  useEffect(() => {
    if (!authUser?.id) { setSourcePolicies({}); return; }
    try {
      const saved = JSON.parse(localStorage.getItem(`learnloop:source-policies:${authUser.id}`) || "{}");
      setSourcePolicies(Object.fromEntries(Object.entries(saved).filter(([, value]) =>
        value === "auto" || value === "strict" || value === "supplement")) as Record<string, "auto" | "strict" | "supplement">);
    } catch { setSourcePolicies({}); }
  }, [authUser?.id]);

  const changeSourcePolicy = (value: "auto" | "strict" | "supplement") => {
    if (!authUser?.id || !activeNotebook) return;
    const next = { ...sourcePolicies, [activeNotebook.id]: value };
    setSourcePolicies(next);
    try { localStorage.setItem(`learnloop:source-policies:${authUser.id}`, JSON.stringify(next)); }
    catch { setPanelError("回答依据已用于本次对话，但浏览器未能保存，刷新后请重新选择。"); }
  };

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
    const epoch = accountEpochRef.current;
    setOnboardingLoading(true);
    setOnboardingError("");
    try {
      const data = await apiGet<OnboardingResponse>("/onboarding");
      if (epoch !== accountEpochRef.current) return;
      setOnboardingRequired(Boolean(data.required));
      if (data.profile) setProfile(data.profile);
      if (data.path) {
        setPathPlan(data.path);
        setSelectedPathNode(data.path.next_kp || data.path.nodes[0]?.id || null);
      }
      if (!data.required) {
        setEntered(true);
        const books = await apiGet<{ items: LearningNotebook[] }>(`/notebooks?user_id=${USER_ID}`);
        if (epoch !== accountEpochRef.current) return;
        let remembered = "";
        try { remembered = localStorage.getItem(`learnloop:last-notebook:${authUser?.id}`) || ""; } catch { /* Optional local resume. */ }
        const linked = new URLSearchParams(window.location.search).get("notebook");
        const recent = books.items.find(book => book.id === linked) || books.items.find(book => book.id === remembered) || books.items[0];
        if (recent && !activeNotebookIdRef.current) {
          const notebook = await apiGet<LearningNotebook>(`/notebooks/${recent.id}?user_id=${USER_ID}`);
          if (epoch !== accountEpochRef.current) return;
          if (!activeNotebookIdRef.current) {
            enterNotebook(notebook);
            if (recent.id === data.resume?.notebook_id && data.resume.assessment_id
              && ["assessment", "plan"].includes(data.resume.phase)) setActivePanel("assessment");
            await loadSources(notebook.id);
            if (epoch !== accountEpochRef.current) return;
            await loadProfile();
          }
        } else if (!recent && data.resume?.assessment_id && !data.resume.notebook_id) {
          setActivePanel("assessment");
        }
      }
    } catch {
      if (epoch === accountEpochRef.current) setOnboardingError("暂时无法读取你的学习进度。请重试，已保存的选择和作答不会丢失。");
    } finally {
      if (epoch === accountEpochRef.current) setOnboardingLoading(false);
    }
  }, [authUser?.id]);

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
      if (pendingStudyNotebook.current === notebookId) {
        pendingStudyNotebook.current = "";
        if (learning.course.study_path) setActivePanel(current => current === "chat" || current === "assessment" ? "study" : current);
      }
      const items = dedupeSources(data.items || []);
      setSources(items);
      setSelectedSourceIds((ids) => {
        const personal = items.filter(isSourceSelectable).map((item) => item.id);
        const available = new Set([
          ...(learning.course.kind === "ds_algo" && !learning.course.study_path ? [COURSE_SOURCE_ID] : []),
          ...items.filter(isSourceSelectable).map((item) => item.id),
        ]);
        const valid = ids.filter((id) => available.has(id));
        if (personal.length && valid.length === 1 && valid[0] === COURSE_SOURCE_ID) {
          return personal;
        }
        const bound = (learning.course.source_ids || []).filter(id => available.has(id));
        return valid.length ? valid : bound.length ? bound : personal.length ? personal : learning.course.kind === "ds_algo" && !learning.course.study_path ? [COURSE_SOURCE_ID] : [];
      });
    } catch (error) {
      if (activeNotebookIdRef.current !== notebookId) return;
      setUploadError(true);
      setUploadNote(`学习资料暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const loadNotebooks = useCallback(async () => {
    const epoch = accountEpochRef.current;
    setNotebookLoading(true);
    setLibraryError("");
    try {
      const data = await apiGet<{ items: LearningNotebook[] }>(`/notebooks?user_id=${USER_ID}`);
      if (epoch !== accountEpochRef.current) return;
      const items = data.items || [];
      setNotebooks(items);
      setActiveNotebook((current) => {
        if (!current) return null;
        const refreshed = items.find((item) => item.id === current.id);
        return refreshed ? { ...current, ...refreshed, messages: current.messages } : null;
      });
    } catch (error) {
      if (epoch === accountEpochRef.current) setLibraryError(`书本列表暂时无法读取：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      if (epoch === accountEpochRef.current) setNotebookLoading(false);
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
      ? ids.filter((id) => id !== COURSE_SOURCE_ID)
      : [COURSE_SOURCE_ID, ...ids]
  ));

  const togglePersonalSource = (sourceId: string) => setSelectedSourceIds((ids) => (
    ids.includes(sourceId)
      ? ids.filter((id) => id !== sourceId)
      : [...ids, sourceId]
  ));

  const enterNotebook = (notebook: LearningNotebook, initialGoal = "") => {
    const goal = initialGoal.trim();
    if (authUser?.id) try { localStorage.setItem(`learnloop:last-notebook:${authUser.id}`, notebook.id); } catch { /* Server history remains available. */ }
    const readingURL = new URL(window.location.href);
    if (readingURL.searchParams.get("notebook") !== notebook.id) readingURL.searchParams.delete("reading");
    readingURL.searchParams.set("notebook", notebook.id);
    window.history.replaceState(null, "", `${readingURL.pathname}${readingURL.search}${readingURL.hash}`);
    activeNotebookIdRef.current = notebook.id;
    setActiveNotebook(notebook);
    pendingStudyNotebook.current = notebook.id;
    setStudyUnit({ id: "", request: 0 });
    setProfile(null);
    setActiveCourse(null);
    setPathPlan(null);
    setEntered(true);
    setNotebookTopic(notebook.title);
    setConversationFocus(goal || latestUserQuestion(notebook.messages));
    setChatSessionId(notebook.session_id);
    setInitialChatMessages(notebook.messages || []);
    setSources([]);
    setSelectedSourceIds([]);
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
      // Loading the conversation must not undo a panel the learner just opened.
      setActiveNotebook(detail);
      setChatSessionId(detail.session_id);
      setInitialChatMessages(detail.messages || []);
      setConversationFocus(initialGoal.trim() || latestUserQuestion(detail.messages));
      setSeed(initialGoal.trim() || undefined);
      setChatInstance(value => value + 1);
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
    setSelectedSourceIds([]);
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

  const logout = async () => {
    try {
      await apiPost<{ ok: boolean }>("/auth/logout", {});
    } finally {
      clearSession();
    }
  };

  const startGenerate = (label: string, goal: string, kinds: string[], promptTemplate: string) => {
    if (!activeNotebook) {
      setPanelError("请先在左侧学习来源中新建或选择一个科目书本。");
      setNewBookOpen(true);
      return;
    }
    if (openingNotebookId) {
      setPanelError("正在切换书本，上一书本内容已清空，请稍候再生成。");
      return;
    }
    const conversationWide = ["framework", "conversation_notes"].includes(promptTemplate);
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
        ? `把本次学习对话整理成${label}`
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
        source_policy: sourcePolicies[activeNotebook.id] || "auto",
        prompt_template: promptTemplate,
        artifact_scope: conversationWide ? "conversation" : "current_topic",
      },
    });
  };

  const startSuggestedTool = (template: SuggestedTool) => {
    if (template === "conversation_notes") {
      startGenerate("本次学习笔记", "整理本次学习对话，保留问过的问题、解释、例子和待解决的疑问。参考资料支撑知识事实，不把看过答案当成已经掌握。", ["doc"], template);
      return;
    }
    const tool = GENERATORS.find(item => item.template === template);
    if (tool) startGenerate(tool.title, tool.goal, [...tool.kinds], tool.template);
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
        verification: grounding?.verification ? String(grounding.verification) : current.verification,
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
    if (event.type === "resource" && event.resource) setResources((items) => [event.resource!, ...items.filter(item => item.id !== event.resource!.id)].slice(0, 30));
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
    return <main className="onboarding-shell"><div className="course-welcome"><h1>选一门课，从第一节开始</h1><p>教材、练习和学习进度放在同一门课里。</p><button className="secondary-action" onClick={() => void skipIntake(false)}>先进入学习空间</button></div><CourseCreateDialog onClose={() => void skipIntake(false)} onCreated={async notebook => {
      await apiPost("/onboarding", { skipped: true });
      setOnboardingRequired(false);
      if (!await openNotebook(notebook)) throw new Error("课程已保存，暂时无法打开，请重试。");
      await loadNotebooks();
    }} /></main>;
  }

  const sourcePanel = (
    <SourcePanel
      includeBuiltin={!!activeNotebook && activeCourse?.kind === "ds_algo" && !activeCourse?.study_path}
      onStudy={(id = "") => { const url = new URL(window.location.href); url.searchParams.delete("reading"); window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`); setReadingFocus(false); setStudyUnit(value => ({ id, request: value.request + 1 })); setActivePanel("study"); setMobilePane(null); }}
      course={activeCourse}
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
      onCreateNotebook={() => { setPanelError(""); setNewBookOpen(true); }}
      onSelectNotebook={(notebookId) => {
        const notebook = notebooks.find((item) => item.id === notebookId);
        if (notebook) void openNotebook(notebook);
      }}
      onToggleCourse={toggleCourseSource}
      onToggle={togglePersonalSource}
    />
  );
  const coachAction = (action: CoachAction) => {
    if (action === "sources") { activeNotebook ? sourceInputRef.current?.click() : setNewBookOpen(true); return; }
    if (action === "assessment") { openPanel("assessment"); return; }
    if (action === "quiz" || action === "notes") { startSuggestedTool(action === "quiz" ? "quiz" : "conversation_notes"); return; }
    setActivePanel("chat"); setMobilePane(null);
    requestAnimationFrame(() => document.getElementById("learning-chat-input")?.focus());
  };
  const studioPanel = <StudioPanel courseKind={activeCourse?.kind} courseTitle={activeCourse?.title || activeNotebook?.title} key={activeNotebook?.id || "welcome"} stage={studyStage} sourceCount={selectedSourceIds.length} hasNotebook={!!activeNotebook} coachKey={`learnloop:coach:v1:${authUser.id}:${activeNotebook?.id || "welcome"}`} onCoachAction={coachAction} onGenerate={startGenerate} onOpen={openPanel} disabled={Boolean(openingNotebookId)} />;
  const profilePace = asRecord(profile?.pace);

  return (
    <LearnerScope.Provider value={authUser.id}>
    <main className="notebook-app notebook-app-enter flex h-dvh flex-col overflow-clip text-[#1D2028]">
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
        <button onClick={() => setActivePanel("chat")} className="study-icon workspace-home" aria-label="学习对话" title="返回学习对话">
          {activePanel === "chat" ? <SparkMark running={running} /> : <ArrowLeft size={22} />}
          <strong className="hidden text-lg tracking-tight md:block">知行循证</strong>
        </button>
        <button type="button" className="workspace-course" data-guide="sources-nav" onClick={() => setMobilePane("sources")} aria-label="学习来源" title={activeNotebook?.title || "选择课程与资料"}>
          <span>{activeNotebook?.title || "我的学习工作台"}</span><ChevronDown size={17} />
        </button>
        {activeNotebook && <button type="button" onClick={() => { setActivePanel("chat"); void startNewConversation(); }} disabled={chatBusy || !!openingNotebookId} className="study-icon" aria-label="新对话" title="新对话"><SquarePen size={21} /></button>}

        <div className="workspace-pane-controls">
          <button type="button" onClick={() => window.innerWidth >= 900 ? (setReadingFocus(false), setSourcesCollapsed(value => readingFocus ? false : !value)) : setMobilePane("sources")} className="study-icon" aria-label="切换资料栏" title="切换资料栏" aria-pressed={!(sourcesCollapsed || (readingFocus && activePanel === "study"))}><PanelLeftOpen size={19} /></button>
          <button type="button" onClick={() => window.innerWidth >= 1400 ? (setReadingFocus(false), setStudioCollapsed(value => readingFocus ? false : !value)) : setMobilePane("studio")} className="study-icon" aria-label="切换工坊栏" title="切换工坊栏"><PanelRightOpen size={19} /></button>
        </div>
        <AdaptiveMenu label="学习菜单" className="workspace-actions">
          <button type="button" className="notebook-home-button workspace-tools-entry" onClick={() => setMobilePane("studio")}><PanelRightOpen size={17} /><span>学习工坊</span></button>
          <button onClick={() => openPanel("assessment")} className="notebook-home-button" aria-label="打开起点测评"><Target size={16} /><span className="hidden md:inline">测评与计划</span></button>
          <span className={`hidden rounded-full px-3 py-1.5 text-xs font-semibold md:inline-flex ${running ? "bg-[#FFF1DD] text-[#9A5B12]" : finished ? "bg-[#E8F4ED] text-[#0F6B50]" : "bg-[#F0F1F5] text-[#626978]"}`}>
            {running ? "正在整理" : finished ? "已经完成" : "准备就绪"}
          </span>
          <LearningGuide userId={authUser.id} enabled={activePanel === "chat" && !newBookOpen && !openingNotebookId && !mobilePane} onPrepare={() => { setActivePanel("chat"); setMobilePane(null); }} />
          <button onClick={() => setEvidenceOpen(true)} className="notebook-evidence-button" aria-label="查看学习依据">
            <ShieldCheck size={16} /><span>依据</span>
          </button>
          <div className="hidden max-w-28 truncate text-xs font-semibold text-[#626978] lg:block" title={authUser.email}>{authUser.name}</div>
          <button onClick={() => void logout()} className="notebook-icon-button" aria-label="退出登录" title="退出登录">
            <LogOut size={17} />
          </button>
        </AdaptiveMenu>
      </header>

      <div className="notebook-layout min-h-0 flex-1" data-sources-collapsed={sourcesCollapsed || (readingFocus && activePanel === "study")} data-studio-collapsed={studioCollapsed || (readingFocus && activePanel === "study")}
        style={{ "--study-source-width": `${sourceWidth}px` } as React.CSSProperties}>
        <aside data-guide="sources" className="workspace-sources min-h-0">{sourcePanel}
          <div className="pane-resizer" role="separator" aria-label="资料栏宽度" aria-orientation="vertical" tabIndex={0}
            aria-valuemin={240} aria-valuemax={380} aria-valuenow={sourceWidth}
            onKeyDown={event => {
              if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                setSourceWidth(value => event.key === "Home" ? 240 : event.key === "End" ? 380 : Math.max(240, Math.min(380, value + (event.key === "ArrowRight" ? 16 : -16))));
              }
            }}
            onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); }}
            onPointerMove={event => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                const left = event.currentTarget.parentElement?.getBoundingClientRect().left || 0;
                setSourceWidth(Math.max(240, Math.min(380, event.clientX - left)));
              }
            }} />
        </aside>

        <section className="notebook-column notebook-main-column relative flex min-h-0 flex-col overflow-hidden">
          {openingNotebookId && (
            <div className="absolute inset-0 z-40 grid place-items-center bg-white/82 px-6 text-center backdrop-blur-sm">
              <div className="rounded-2xl border border-emerald-200 bg-white px-6 py-5 shadow-xl">
                <div className="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" />
                <strong className="mt-3 block text-sm text-slate-900">正在打开这门课程</strong>
                <span className="mt-1 block text-xs leading-5 text-slate-500">正在恢复这门课程的对话、资料和学习进度。</span>
              </div>
            </div>
          )}
          {activeNotebook && <GenerationJobs key={activeNotebook.id} notebookId={activeNotebook.id} onView={kind => { if (kind === "chat") { void openNotebook(activeNotebook); } else { void loadResources(); setActivePanel("resources"); } }} />}
          {panelError && <div className="m-3 rounded-[8px] border border-[#F1D6C9] bg-[#FFF6F1] px-4 py-3 text-sm text-[#9E4B2D]">{panelError}</div>}

          <div className={`min-h-0 flex-1 ${activePanel === "chat" ? "block" : "hidden"}`} aria-hidden={activePanel !== "chat"}>
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
              sourceLabel={selectedSourceIds.map(id => id === COURSE_SOURCE_ID ? "课程教材" : sources.find(source => source.id === id)?.title || "已选资料").join("、")}
              onOpenSources={() => setMobilePane("sources")}
              onOpenStudio={() => setMobilePane("studio")}
              onBusyChange={setChatBusy}
              sourcePolicy={sourcePolicies[activeNotebook?.id || ""] || "auto"}
              onSourcePolicyChange={changeSourcePolicy}
              onUploadClick={() => activeNotebook ? sourceInputRef.current?.click() : setNewBookOpen(true)}
              onCreateNotebook={() => { setPanelError(""); setNewBookOpen(true); }}
              onSeedConsumed={() => { setSeed(undefined); setRequest(undefined); }}
              onLearningTurn={setConversationFocus}
              onSessionReady={setChatSessionId}
              learnerId={authUser.id}
              onStudyStage={setStudyStage}
              onSuggestedTool={activeNotebook ? startSuggestedTool : undefined}
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

          {activeNotebook && activeCourse?.study_path && <div className={`min-h-0 flex-1 ${activePanel === "study" ? "block" : "hidden"}`} aria-hidden={activePanel !== "study"}><CourseStudyPanel key={`${authUser.id}:${activeNotebook.id}`} userId={authUser.id} notebookId={activeNotebook.id} requestedUnit={studyUnit} onFocus={setReadingFocus} onReviews={() => openPanel("profile")} onChat={prompt => { if (prompt) void startLearning(prompt); else setActivePanel("chat"); }} onUpload={() => sourceInputRef.current?.click()} /></div>}
          {activePanel === "assessment" && activeCourse?.study_path && <div className="course-study-scroll"><h2>从当前章节的原题开始</h2><p>本课采用教材与机构练习。先完成题目、核对答案，再记录订正；已有测评记录仍保留。</p><button className="primary-action" onClick={() => setActivePanel("study")}>继续课程学习</button><details><summary>查看已有测评记录</summary><AssessmentPanel historyOnly key={activeNotebook?.id || "initial"} notebookId={activeNotebook?.id || ""} onStarted={assessmentStarted} onBack={() => setActivePanel("study")} onLearn={(prompt) => void startLearning(prompt)} onCourses={() => setActivePanel("courses")} onUpdated={() => { void loadProfile(); }} /></details></div>}
          {activePanel === "assessment" && !activeCourse?.study_path && <AssessmentPanel key={activeNotebook?.id || "initial"} notebookId={activeNotebook?.id || ""} onStarted={assessmentStarted} initialSurvey={{ course_title: activeCourse?.title || activeNotebook?.title || "", course_key: "custom", source_ids: selectedSourceIds.filter(id => id !== COURSE_SOURCE_ID), ...profile?.learning_intake }} onBack={() => setActivePanel("chat")} onLearn={(prompt) => void startLearning(prompt)} onCourses={(kp = "") => { setCourseKp(kp); setActivePanel("courses"); }} onUpdated={() => { void loadProfile(); void loadPath(); }} />}
          {activePanel === "research" && <ResearchPanel key={activeNotebook?.id || "research"} notebookId={activeNotebook?.id || ""} initialTopic={conversationFocus || notebookTopic} onBack={() => setActivePanel("chat")} />}
          {activePanel === "english" && <EnglishScenes key={activeNotebook?.id || "english"} notebookId={activeNotebook?.id || ""} onBack={() => setActivePanel("chat")} />}
          {activePanel === "courses" && <CourseRecommendations key={activeNotebook?.id || "global"} notebookId={activeNotebook?.id} initialTopic={activeCourse?.title || notebookTopic || conversationFocus} initialKp={courseKp} onBack={() => setActivePanel("chat")} onAssess={() => openPanel("assessment")} />}
          {activePanel === "profile" && (
            <div className="notebook-content-scroll">
              <div className="notebook-content-heading">
                <div><span>LEARNING PROFILE</span><h1>我的学习情况</h1><p>每次独立作答积累证据；初始先验不代表实际成绩。</p></div>
                <div className="flex items-center gap-2"><button onClick={() => { setOnboardingRequired(true); setEntered(false); setOnboardingLoading(false); }} className="secondary-action">调整学习起点</button><button onClick={() => void loadProfile()} className="secondary-action">刷新</button></div>

              </div>
              <div className="px-5 pt-5">
              {activeNotebook && activeCourse?.kind === "cet6" && <ReadingProgress key={activeNotebook.id} notebookId={activeNotebook.id} onOpen={id => { const url = new URL(window.location.href); url.searchParams.set("notebook", activeNotebook.id); url.searchParams.set("reading", id); window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`); setStudyUnit(value => ({ id: "", request: value.request + 1 })); setActivePanel("study"); }} />}
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
                    {groupedResources.map((group) => <ResourceCard key={group.key} r={group.representative} onRenamed={saved => setResources(items => items.map(item => item.id === saved.id ? saved : item))} versionCount={group.versionCount} onQuizEvaluated={refreshAfterEvaluation} onOpenMistakes={() => openPanel("mistakes")} />)}
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

        <aside data-guide="studio" className="workspace-studio min-h-0">{studioPanel}</aside>
      </div>

      <StudyDialog open={!!mobilePane} title={mobilePane === "sources" ? "学习来源" : "学习工坊"} onClose={() => setMobilePane(null)} className="workspace-drawer">
        <div className="notebook-mobile-sheet">{mobilePane === "sources" ? sourcePanel : studioPanel}</div>
      </StudyDialog>

      <section aria-hidden={!evidenceOpen} inert={!evidenceOpen} style={{ visibility: evidenceOpen ? "visible" : "hidden" }} className={`fixed inset-y-0 right-0 z-50 w-[min(92vw,420px)] border-l border-white/10 bg-[#072C3A]/[0.98] text-white shadow-[-22px_0_70px_rgba(0,18,28,0.3)] backdrop-blur-xl transition-transform duration-300 ${evidenceOpen ? "translate-x-0" : "translate-x-full"}`}>
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

      {newBookOpen && <CourseCreateDialog
        onClose={() => { setNewBookOpen(false); void loadNotebooks(); }}
        onCreated={async (notebook) => {
          if (!await openNotebook(notebook)) throw new Error("课程已保存，暂时无法打开。请重试。");
          await loadNotebooks();
          setNewBookOpen(false);
          setMobilePane(null);
          // loadSources selects the new course learning panel when available.
        }}
      />}

    </main>
    </LearnerScope.Provider>
  );
}
