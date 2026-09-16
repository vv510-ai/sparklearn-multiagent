"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, DeltaTag, Notice, Stat } from "@/components/ui";
import { USER_ID, apiGet } from "@/lib/api";

type EvidencePhase = "initial" | "retest" | "spaced_review";

interface KnowledgeEvidence {
  kp: string;
  name: string;
  answers: number;
  raw_correct: number;
  mastery_correct: number;
  supported: number;
  confidence_recorded: number;
  confident_wrong: number;
  uncertain_correct: number;
  mastery_before: number;
  mastery_after: number;
  mastery_delta: number;
  level: string;
}

interface EvidenceRound {
  id: number;
  created_at: string;
  phase: EvidencePhase;
  answers: number;
  raw_correct: number;
  mastery_correct: number;
  supported: number;
  independent: number;
  errors: Record<string, number>;
  calibration: {
    recorded: number;
    score: number | null;
    confident_wrong: number;
    uncertain_correct: number;
    metacognition_before: number | null;
    metacognition_after: number | null;
  };
  knowledge_points: KnowledgeEvidence[];
}

interface EvidenceResponse {
  items: EvidenceRound[];
  summary: {
    rounds: number;
    answers: number;
    raw_correct: number;
    mastery_correct: number;
    supported: number;
    independent: number;
    confidence_recorded: number;
    confident_wrong: number;
    uncertain_correct: number;
    calibration_score: number | null;
    by_phase: Record<EvidencePhase, number>;
  };
}

const PHASE: Record<EvidencePhase, { label: string; badge: "info" | "success" | "warn" }> = {
  initial: { label: "首次作答", badge: "info" },
  retest: { label: "无提示复测", badge: "success" },
  spaced_review: { label: "间隔复习", badge: "warn" },
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatTime(value: string): string {
  if (!value) return "时间未记录";
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function LearningEvidence({ refreshToken = 0, notebookId = "" }: { refreshToken?: number; notebookId?: string }) {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);

  const loadEvidence = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiGet<EvidenceResponse>(`/eval/evidence?user_id=${USER_ID}&limit=12&notebook_id=${encodeURIComponent(notebookId)}`);
      setData(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "学习记录读取失败");
    } finally {
      setLoading(false);
    }
  }, [notebookId]);

  useEffect(() => {
    void loadEvidence();
  }, [loadEvidence, refreshToken]);

  const visibleItems = useMemo(
    () => (expanded ? data?.items || [] : (data?.items || []).slice(0, 3)),
    [data, expanded],
  );

  if (loading && !data) {
    return <div className="insight-panel p-5 text-sm text-[#6F7684]">正在读取学习记录...</div>;
  }

  if (!data) {
    return (
      <Notice
        tone="warn"
        title="学习记录暂时无法读取"
        desc={error || "请稍后刷新。"}
        action={<button onClick={() => void loadEvidence()} className="text-xs font-bold">重试</button>}
      />
    );
  }

  return (
    <section className="insight-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <div className="flex items-center gap-2">
            <Badge variant="info" mono>LEARNING RECORDS</Badge>
            <span className="text-xs font-bold text-[#0F6B50]">学习记录</span>
          </div>
          <h2 className="mt-3 text-xl font-bold text-[#1D2028]">查看每次练习与掌握度变化</h2>
          <p className="mt-2 text-sm leading-6 text-[#6F7684]">
            判对表示答案正确；计入掌握表示这次表现真正参与了掌握度计算。揭晓后答对不会被当作已掌握，使用提示也会单独留下记录。
          </p>
        </div>
        <button onClick={() => void loadEvidence()} className="secondary-action">刷新记录</button>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="作答轮次" value={data.summary.rounds} sub="首次、复测与间隔复习" tone="action" />
        <Stat label="独立作答" value={data.summary.independent} sub={`共作答 ${data.summary.answers} 次`} tone="success" />
        <Stat label="计入掌握的答对" value={data.summary.mastery_correct} sub={`原始判对 ${data.summary.raw_correct} 次`} tone="warn" />
        <Stat
          label="信心校准"
          value={data.summary.calibration_score == null ? "待记录" : percent(data.summary.calibration_score)}
          sub={data.summary.confidence_recorded
            ? `自信误判 ${data.summary.confident_wrong} · 答对但不稳 ${data.summary.uncertain_correct}`
            : "下一次作答时开始记录"}
          tone={data.summary.calibration_score == null ? "muted" : data.summary.calibration_score >= 0.7 ? "success" : "warn"}
        />
      </div>

      {error && <Notice tone="warn" className="mt-4" title="刷新失败，当前展示上次结果" desc={error} />}

      {data.items.length === 0 ? (
        <div className="mt-5 rounded-lg border border-dashed border-[#CDD3DE] bg-[#F8F9FC] px-4 py-6 text-center">
          <div className="text-sm font-bold text-[#303641]">还没有练习记录</div>
          <p className="mt-1 text-xs leading-5 text-[#6F7684]">完成一次题组后，这里会展示判分、支持使用和掌握度前后变化。</p>
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {visibleItems.map((item) => {
            const phase = PHASE[item.phase] || PHASE.initial;
            const errors = Object.keys(item.errors || {});
            return (
              <article key={item.id} className="rounded-lg border border-[#E1E4EC] bg-[#F8F9FC] p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={phase.badge}>{phase.label}</Badge>
                    <strong className="text-sm text-[#1D2028]">
                      判对 {item.raw_correct}/{item.answers} · 计入掌握 {item.mastery_correct}/{item.answers}
                    </strong>
                    {item.supported > 0 && <Badge variant="warn">使用支持 {item.supported} 次</Badge>}
                    {item.calibration.recorded > 0 && (
                      <Badge variant={item.calibration.confident_wrong ? "danger" : "info"}>
                        信心校准 {percent(item.calibration.score || 0)}
                      </Badge>
                    )}
                  </div>
                  <time className="text-xs text-[#858B98]">{formatTime(item.created_at)}</time>
                </div>

                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  {item.knowledge_points.map((point) => (
                    <div key={point.kp} className="rounded-md border border-[#E1E4EC] bg-white px-3 py-2.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-bold text-[#4E5563]">{point.name}</span>
                        <span className="flex items-center gap-1.5 font-mono text-xs font-bold text-[#303641]">
                          {percent(point.mastery_before)} → {percent(point.mastery_after)}
                          <DeltaTag delta={Math.round(point.mastery_delta * 100)} unit="%" />
                        </span>
                      </div>
                      <div className="mt-1.5 text-[11px] text-[#7A818E]">
                        本轮 {point.answers} 题 · 判对 {point.raw_correct} · 计入掌握 {point.mastery_correct}
                        {point.supported > 0 ? ` · 支持 ${point.supported}` : ""}
                      </div>
                    </div>
                  ))}
                </div>

                {errors.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs font-bold text-[#8A6546]">本轮错因</span>
                    {errors.map((tag) => <Badge key={tag} variant="warn">{tag}</Badge>)}
                  </div>
                )}
                {item.calibration.recorded > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    {item.calibration.confident_wrong > 0 && <Badge variant="danger">自信误判 {item.calibration.confident_wrong}</Badge>}
                    {item.calibration.uncertain_correct > 0 && <Badge variant="warn">答对但不稳 {item.calibration.uncertain_correct}</Badge>}
                    {item.calibration.metacognition_before != null && item.calibration.metacognition_after != null && (
                      <span className="text-[11px] text-[#7A818E]">
                        元认知 {percent(item.calibration.metacognition_before)} → {percent(item.calibration.metacognition_after)}
                      </span>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      {data.items.length > 3 && (
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className="mt-4 text-xs font-bold text-[#0F6B50] hover:underline"
        >
          {expanded ? "收起历史记录" : `查看最近 ${data.items.length} 轮记录`}
        </button>
      )}
    </section>
  );
}
