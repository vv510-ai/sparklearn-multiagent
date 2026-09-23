"use client";
/** AgentTrace · 协作链路(项目签名件)。
 *  只做展示层增强:阶段分组 / 并行框 / 耗时 / 降级徽标 / 待开始引导。
 *  事件归约语义(applyTraceEvent)与后端 emitter 契约保持不变。 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Panel, StatusDot } from "@/components/ui";
import type { AgentId, SparkEvent } from "@/lib/types";

export type NodeStatus = "idle" | "running" | "done" | "error";
export interface TraceNode {
  status: NodeStatus;
  label: string;
  detail: string;
  summary: string;
  ts?: string;
  modelRoute?: SparkEvent["model_route"];
}
export type TraceState = Record<string, TraceNode>;

const AGENT_META: Record<string, { name: string; code: string; group: string }> = {
  profile: { name: "读取画像", code: "PRF", group: "理解需求" },
  orchestrator: { name: "理解需求", code: "ORC", group: "判断意图" },
  planner: { name: "整理任务", code: "PLN", group: "拆解任务" },
  path: { name: "生成路线", code: "PTH", group: "推荐顺序" },
  doc: { name: "图文教程", code: "DOC", group: "准备资料" },
  mindmap: { name: "思维导图", code: "MAP", group: "准备资料" },
  quiz: { name: "练习题组", code: "QUZ", group: "准备资料" },
  media: { name: "讲解脚本", code: "MED", group: "准备资料" },
  tutor: { name: "答疑导师", code: "TUT", group: "即时辅导" },
  eval: { name: "结果检查", code: "EVL", group: "结果检查" },
};

export function emptyTrace(): TraceState {
  const t: TraceState = {};
  for (const k of Object.keys(AGENT_META)) {
    t[k] = { status: "idle", label: AGENT_META[k].name, detail: "", summary: "" };
  }
  return t;
}

export function applyTraceEvent(prev: TraceState, ev: SparkEvent): TraceState {
  const a = ev.agent as string | undefined;
  if (!a || !(a in prev)) {
    if (ev.type === "error") {
      const t = { ...prev };
      for (const k of Object.keys(t)) {
        if (t[k].status === "running") t[k] = { ...t[k], status: "error", detail: ev.detail || "" };
      }
      return t;
    }
    return prev;
  }
  const node = prev[a];
  switch (ev.type) {
    case "agent_start":
      return { ...prev, [a]: { ...node, status: "running", detail: ev.detail || "", ts: ev.ts } };
    case "progress":
      return { ...prev, [a]: { ...node, detail: ev.text || ev.detail || node.detail, modelRoute: ev.model_route || node.modelRoute } };
    case "agent_end":
      return { ...prev, [a]: { ...node, status: "done", summary: ev.summary || "", ts: ev.ts } };
    case "safety":
      return { ...prev, [a]: { ...node, detail: `安全检查:${ev.detail || ""}` } };
    default:
      return prev;
  }
}

function statusToDot(status: NodeStatus) {
  if (status === "running") return "running";
  if (status === "done") return "done";
  if (status === "error") return "error";
  return "idle";
}

function statusToBadge(status: NodeStatus) {
  if (status === "running") return "info";
  if (status === "done") return "success";
  if (status === "error") return "danger";
  return "neutral";
}

/** 从节点文案里识别"降级/兜底/安全"提示,展示为预案徽标(不改数据)。 */
function degradeHint(n: TraceNode): string {
  const text = `${n.detail} ${n.summary}`;
  if (/降级|兜底|fallback/i.test(text)) return "备用方案";
  if (/安全检查|敏感|审核/.test(text)) return "安全提示";
  return "";
}

function Node({ id, n, duration }: { id: string; n: TraceNode; duration?: number }) {
  const meta = AGENT_META[id];
  const active = n.status === "running";
  const done = n.status === "done";
  const error = n.status === "error";
  const hint = degradeHint(n);

  return (
    <div
      className={`rounded-lg border px-3 py-2.5 transition ${
        active
          ? "border-[#7ED9A6]/45 bg-[#7ED9A6]/10"
          : done
            ? "border-[#7ED9A6]/25 bg-[#7ED9A6]/[0.07]"
            : error
              ? "border-rose-400/45 bg-rose-400/10"
              : "border-[#26312A] bg-[#151D18]"
      }`}
    >
      <div className="flex items-center gap-2">
        <StatusDot status={statusToDot(n.status)} />
        <Badge variant={statusToBadge(n.status)} mono>{meta.code}</Badge>
        <span className="min-w-0 flex-1 truncate text-sm font-bold text-[#E5EFE8]">{meta.name}</span>
        {hint && <Badge variant="warn" title={n.detail}>{hint}</Badge>}
        {duration != null && <Badge variant="neutral" mono>{duration.toFixed(1)}s</Badge>}
        <span className="hidden shrink-0 text-[11px] text-[#8DA18F] sm:inline">{meta.group}</span>
      </div>
      {(n.status === "running" && n.detail) || (n.status === "done" && n.summary) || error ? (
        <div className="mt-1.5 truncate pl-7 text-xs leading-5 text-[#A9B8AC]">
          {done ? n.summary : n.detail}
        </div>
      ) : null}
      {active && (
        <div className="ml-7 mt-1.5 h-1 overflow-hidden rounded-full bg-[#26312A]">
          <div className="h-1 w-1/3 animate-slide rounded-full bg-[#7ED9A6]" />
        </div>
      )}
      {n.modelRoute && <p className="mt-1 pl-7 text-xs text-[#A9B8AC]">{n.modelRoute.automatic ? "自动选择" : "服务配置"}：{n.modelRoute.model} · {n.modelRoute.reason}</p>}
    </div>
  );
}

function StepLine({ active }: { active: boolean }) {
  return <div className={`mx-4 h-3 border-l-2 ${active ? "border-[#7ED9A6]/45" : "border-[#26312A]"}`} />;
}

/** 阶段小标:把链路读成"理解 → 规划 → 生成 → 质检"的产品化步骤。 */
function StageLabel({ text, active }: { text: string; active: boolean }) {
  return (
    <div className="my-1 flex items-center gap-2 pl-1">
      <span
        className={`font-mono text-[10px] font-bold tracking-[0.2em] ${active ? "text-[#7ED9A6]" : "text-[#6E8072]"}`}
      >
        {text}
      </span>
      <span className={`h-px flex-1 ${active ? "bg-[#7ED9A6]/30" : "bg-[#26312A]"}`} />
    </div>
  );
}

export default function AgentTrace({ trace }: { trace: TraceState }) {
  const gen: AgentId[] = ["doc", "mindmap", "quiz", "media"];
  const startedAtRef = useRef<Record<string, number>>({});
  const runStartRef = useRef<number | null>(null);
  const [durations, setDurations] = useState<Record<string, number>>({});
  const [elapsed, setElapsed] = useState(0);
  const anyGen = useMemo(() => gen.some((g) => trace[g].status !== "idle"), [trace]);
  const tutorMode = trace.tutor.status !== "idle" && !anyGen;
  const running = Object.values(trace).filter((n) => n.status === "running").length;
  const done = Object.values(trace).filter((n) => n.status === "done").length;
  const allIdle = running === 0 && done === 0 && Object.values(trace).every((n) => n.status === "idle");

  useEffect(() => {
    setDurations((prev) => {
      let next = prev;
      let changed = false;

      for (const [id, n] of Object.entries(trace)) {
        if (n.status === "running" && startedAtRef.current[id] == null) {
          startedAtRef.current[id] = Date.now();
        }

        if ((n.status === "done" || n.status === "error") && startedAtRef.current[id] != null && next[id] == null) {
          if (next === prev) next = { ...prev };
          next[id] = Math.max(0.1, (Date.now() - startedAtRef.current[id]) / 1000);
          delete startedAtRef.current[id];
          changed = true;
        }

        if (n.status === "idle") {
          delete startedAtRef.current[id];
          if (next[id] != null) {
            if (next === prev) next = { ...prev };
            delete next[id];
            changed = true;
          }
        }
      }

      return changed ? next : prev;
    });
  }, [trace]);

  /** 本轮总计时:首个 running 起算,全部结束后定格。 */
  useEffect(() => {
    if (allIdle) {
      runStartRef.current = null;
      setElapsed(0);
      return;
    }
    if (runStartRef.current == null) runStartRef.current = Date.now();
    if (running === 0) return; // 定格
    const timer = window.setInterval(() => {
      if (runStartRef.current != null) setElapsed((Date.now() - runStartRef.current) / 1000);
    }, 300);
    return () => window.clearInterval(timer);
  }, [allIdle, running]);

  return (
    <Panel className="border-[#26312A] bg-[#0E1411] p-4 text-[#C7D2C9] shadow-[0_20px_60px_rgba(14,20,17,0.28)]">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-bold tracking-[0.18em] text-[#7ED9A6]">过程</div>
          <h2 className="mt-1 text-lg font-bold tracking-tight text-[#E5EFE8]">依据与过程</h2>
          <p className="mt-1 text-xs leading-5 text-[#8DA18F]">
            默认先看结果;需要确认时,这里保留系统做过哪些事。
          </p>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <div className="flex items-center gap-2">
            {elapsed > 0 && (
              <Badge variant={running ? "info" : "neutral"} mono title="本轮任务耗时">
                {elapsed.toFixed(1)}s
              </Badge>
            )}
              <Badge variant={running ? "info" : done ? "success" : "neutral"}>
              进行中 {running} · 已完成 {done}
            </Badge>
          </div>
        </div>
      </div>

      {allIdle ? (
        <div className="mt-4 rounded-lg border border-dashed border-[#26312A] bg-[#151D18] px-4 py-6 text-center">
          <div className="text-sm font-bold text-[#E5EFE8]">等待开始</div>
          <p className="mx-auto mt-1 max-w-[26ch] text-xs leading-5 text-[#8DA18F]">
            发起对话或点击生成后,这里会保留处理记录。
          </p>
          <div className="mt-3 flex items-center justify-center gap-4 text-[11px] text-[#8DA18F]">
            <span className="inline-flex items-center gap-1.5"><StatusDot status="idle" />待开始</span>
            <span className="inline-flex items-center gap-1.5"><StatusDot status="running" />运行中</span>
            <span className="inline-flex items-center gap-1.5"><StatusDot status="done" />完成</span>
            <span className="inline-flex items-center gap-1.5"><StatusDot status="error" />失败</span>
          </div>
        </div>
      ) : null}

      <div className="mt-3">
        <StageLabel text="STAGE 1 · 理解" active={trace.profile.status !== "idle"} />
        <Node id="profile" n={trace.profile} duration={durations.profile} />
        <StepLine active={trace.profile.status === "done" && trace.orchestrator.status !== "idle"} />
        <Node id="orchestrator" n={trace.orchestrator} duration={durations.orchestrator} />

        {tutorMode ? (
          <>
            <StageLabel text="STAGE 2 · 即时答疑" active={trace.tutor.status !== "idle"} />
            <Node id="tutor" n={trace.tutor} duration={durations.tutor} />
          </>
        ) : (
          <>
            <StepLine active={trace.planner.status !== "idle"} />
            <StageLabel text="STAGE 2 · 规划" active={trace.planner.status !== "idle" || trace.path.status !== "idle"} />
            <Node id="planner" n={trace.planner} duration={durations.planner} />
            <StepLine active={trace.path.status !== "idle"} />
            <Node id="path" n={trace.path} duration={durations.path} />
            <StepLine active={anyGen} />
            <StageLabel text="STAGE 3 · 准备资料" active={anyGen} />
            <div
              className={`grid grid-cols-2 gap-2 rounded-lg border border-dashed p-2 ${
                anyGen ? "border-[#7ED9A6]/35 bg-[#7ED9A6]/[0.05]" : "border-[#26312A]"
              }`}
            >
              {gen.map((g) => (
                <Node key={g} id={g} n={trace[g]} duration={durations[g]} />
              ))}
            </div>
            <StepLine active={trace.eval.status !== "idle"} />
            <StageLabel text="STAGE 4 · 检查结果" active={trace.eval.status !== "idle"} />
            <Node id="eval" n={trace.eval} duration={durations.eval} />
          </>
        )}
      </div>
    </Panel>
  );
}
