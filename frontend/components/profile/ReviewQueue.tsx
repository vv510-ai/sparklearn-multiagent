"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Notice, Stat } from "@/components/ui";
import { USER_ID, apiGet, apiPost } from "@/lib/api";
import type { EvaluationReport } from "@/components/resource/QuizRetest";

interface ReviewQuestion {
  id: string;
  type: "single" | "fill" | "judge" | "design" | "complexity";
  stem: string;
  options: string[];
  kp: string;
  difficulty: number;
}

interface ReviewQueueItem {
  id: number;
  quiz_resource_id: string;
  question_id: string;
  kp: string;
  kp_name: string;
  stage: number;
  due_at: string;
  lapse_count: number;
  reason: string;
  question: ReviewQuestion;
}

interface QueueSummary {
  due: number;
  upcoming: number;
  mastered: number;
  next_due_at?: string | null;
  interval_days: number[];
}

interface QueueResponse {
  items: ReviewQueueItem[];
  summary: QueueSummary;
}

interface ReviewSchedule {
  review_item_id: number;
  question_id: string;
  correct: boolean;
  stage: number;
  status: "scheduled" | "mastered";
  due_at: string;
  interval_days?: number | null;
  lapse_count: number;
}

interface ReviewReport extends EvaluationReport {
  review?: {
    completed?: number;
    correct?: number;
    schedule?: ReviewSchedule[];
    summary?: QueueSummary;
  };
}

function formatDue(value?: string | null): string {
  if (!value) return "暂无安排";
  return new Date(value).toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

function normalize(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "").replace(/[()（）]/g, "");
}

function choiceLetter(options: string[], answer: string): string {
  const raw = answer.trim();
  if (/^[A-D](?:[.、：:\s]|$)/i.test(raw)) return raw[0].toUpperCase();
  const expected = normalize(raw.replace(/^[A-D][.、：:\s]*/i, ""));
  const index = options.findIndex((option) => (
    normalize(option.replace(/^[A-D][.、：:\s]*/i, "")) === expected
  ));
  return index >= 0 ? String.fromCharCode(65 + index) : "";
}

function displayAnswer(question: ReviewQuestion, answer: string): string {
  if (question.type !== "single" && !(question.type === "complexity" && question.options.length > 0)) {
    return answer;
  }
  const letter = choiceLetter(question.options, answer);
  const option = question.options[letter.charCodeAt(0) - 65];
  return option ? `${letter}. ${option.replace(/^[A-D][.、：:\s]*/i, "")}` : answer;
}

export default function ReviewQueue({
  onEvaluated,
}: {
  onEvaluated?: (report: EvaluationReport) => void;
}) {
  const [queue, setQueue] = useState<QueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [started, setStarted] = useState(false);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ReviewReport | null>(null);
  const startedAt = useRef<Record<number, number>>({});

  const resultItems = useMemo(() => Object.fromEntries(
    (result?.items || [])
      .filter((item) => item.review_item_id)
      .map((item) => [item.review_item_id as number, item]),
  ), [result]);
  const schedules = useMemo(() => Object.fromEntries(
    (result?.review?.schedule || []).map((item) => [item.review_item_id, item]),
  ), [result]);
  const answered = (queue?.items || []).filter((item) => (answers[item.id] || "").trim()).length;

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiGet<QueueResponse>(`/eval/review-queue?user_id=${USER_ID}&limit=10`);
      setQueue(data);
      setStarted(false);
      setAnswers({});
      setResult(null);
      startedAt.current = {};
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复习队列加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  function setAnswer(itemId: number, value: string) {
    if (busy || result) return;
    if (!startedAt.current[itemId]) startedAt.current[itemId] = Date.now();
    setAnswers((current) => ({ ...current, [itemId]: value }));
  }

  async function submit() {
    if (!queue?.items.length) return;
    setBusy(true);
    setError("");
    try {
      const report = await apiPost<ReviewReport>("/eval/review", {
        user_id: USER_ID,
        items: queue.items.map((item) => ({
          review_item_id: item.id,
          answer: answers[item.id] || "",
          seconds: startedAt.current[item.id]
            ? Math.max(1, Math.round((Date.now() - startedAt.current[item.id]) / 1000))
            : 0,
        })),
      });
      setResult(report);
      onEvaluated?.(report);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "今日复习提交失败");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <div className="insight-panel p-5 text-sm text-[#6F7684]">正在整理今日复习...</div>;
  }

  if (!queue) {
    return <Notice tone="warn" title="复习队列暂时不可用" desc={error || "请稍后刷新。"} />;
  }

  if (!started) {
    return (
      <div className="insight-panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Badge variant="info" mono>SPACED REVIEW</Badge>
              <span className="text-xs font-bold text-[#0F6B50]">今日复习</span>
            </div>
            <h2 className="mt-3 text-xl font-bold text-[#1D2028]">
              {queue.summary.due ? `今天有 ${queue.summary.due} 道题需要回忆` : "今天的复习已经完成"}
            </h2>
            <p className="mt-2 text-sm leading-6 text-[#6F7684]">
              系统按 1、3、7、14、30 天安排独立回忆；答错会回到短间隔。
            </p>
          </div>
          <button onClick={() => void loadQueue()} className="secondary-action">刷新队列</button>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <Stat label="今日到期" value={queue.summary.due} tone={queue.summary.due ? "warn" : "success"} />
          <Stat label="后续已排期" value={queue.summary.upcoming} tone="action" />
          <Stat label="完成周期" value={queue.summary.mastered} tone="success" />
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#E1E4EC] bg-[#F8F9FC] px-4 py-3 text-xs text-[#626978]">
          <span>{queue.summary.next_due_at ? `下一次计划：${formatDue(queue.summary.next_due_at)}` : "完成错题或复测后，这里会自动生成计划。"}</span>
          {queue.items.length > 0 && (
            <button onClick={() => setStarted(true)} className="primary-action">
              开始今日复习（{queue.items.length}）
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="insight-panel space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><Badge variant="info" mono>RECALL</Badge><strong>今日独立回忆</strong></div>
          <p className="mt-2 text-xs leading-5 text-[#6F7684]">不提供提示；提交后才显示答案与下一次复习时间。</p>
        </div>
        {!result && <Badge variant="neutral">已作答 {answered}/{queue.items.length}</Badge>}
      </div>

      {queue.items.map((item, index) => {
        const question = item.question;
        const mine = answers[item.id] || "";
        const graded = resultItems[item.id];
        const schedule = schedules[item.id];
        return (
          <div key={item.id} className="rounded-lg border border-[#E1E4EC] bg-[#F8F9FC] p-4">
            <div className="mb-3 flex items-start gap-2">
              <Badge variant="neutral" mono>D{index + 1}</Badge>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold leading-6 text-[#1D2028]">{question.stem}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <Badge variant="info">{item.kp_name}</Badge>
                  <Badge variant="warn">上次卡点：{item.reason}</Badge>
                  <Badge variant="neutral">阶段 {item.stage}/5</Badge>
                </div>
              </div>
            </div>

            {question.type === "single" || (question.type === "complexity" && question.options.length > 0) ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {question.options.map((option, optionIndex) => {
                  const letter = String.fromCharCode(65 + optionIndex);
                  return (
                    <button
                      type="button"
                      key={letter}
                      disabled={Boolean(result) || busy}
                      onClick={() => setAnswer(item.id, letter)}
                      className={`rounded-md border px-3 py-2 text-left text-xs transition ${
                        mine === letter
                          ? "border-[#7ABFA2] bg-[#E8F4ED] text-[#0F6B50]"
                          : "border-[#DDE0E8] bg-white text-[#4E5563] hover:border-[#A7D6C0]"
                      } disabled:cursor-not-allowed`}
                    >
                      <span className="mr-2 font-mono font-bold text-[#0F6B50]">{letter}</span>
                      {option.replace(/^[A-D][.、：:\s]*/, "")}
                    </button>
                  );
                })}
              </div>
            ) : question.type === "judge" ? (
              <div className="flex gap-2">
                {["对", "错"].map((value) => (
                  <button
                    type="button"
                    key={value}
                    disabled={Boolean(result) || busy}
                    onClick={() => setAnswer(item.id, value)}
                    className={`rounded-md border px-4 py-2 text-xs font-bold ${
                      mine === value ? "border-[#7ABFA2] bg-[#E8F4ED] text-[#0F6B50]" : "border-[#DDE0E8] bg-white text-[#4E5563]"
                    } disabled:cursor-not-allowed`}
                  >{value}</button>
                ))}
              </div>
            ) : (
              <textarea
                value={mine}
                disabled={Boolean(result) || busy}
                onChange={(event) => setAnswer(item.id, event.target.value)}
                rows={question.type === "fill" ? 1 : 3}
                placeholder={question.type === "fill" ? "填写答案" : "独立写下你的思路与答案"}
                className="w-full resize-none rounded-md border border-[#DDE0E8] bg-white px-3 py-2 text-sm outline-none focus:border-[#7ABFA2] disabled:bg-[#ECEEF3]"
              />
            )}

            {graded && (
              <div className={`mt-3 rounded-md border px-3 py-2 text-xs ${
                graded.correct ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-orange-200 bg-orange-50 text-orange-700"
              }`}>
                <div className="font-bold">
                  {graded.correct ? "回忆正确" : `需要继续巩固 · 参考答案：${displayAnswer(question, graded.expected || "")}`}
                </div>
                {graded.explain && <div className="mt-1 leading-5 text-slate-600">{graded.explain}</div>}
                {schedule && (
                  <div className="mt-1 text-slate-600">
                    {schedule.status === "mastered" ? "已完成本轮间隔周期" : `下次复习：${schedule.interval_days} 天后`}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {error && <Notice tone="warn" title="今日复习提交失败" desc={`${error}。答案已保留，可直接重试。`} />}
      {!result ? (
        <button
          type="button"
          onClick={submit}
          disabled={busy || answered !== queue.items.length}
          className="primary-action w-full justify-center disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "正在更新复习计划..." : "提交今日复习"}
        </button>
      ) : (
        <div className="space-y-3">
          <Notice
            tone={result.review?.correct === result.review?.completed ? "success" : "warn"}
            title={`今日完成 ${result.review?.completed || 0} 题，独立答对 ${result.review?.correct || 0} 题`}
            desc="掌握度、错因画像、学习路径和下一次复习时间均已更新。"
          />
          <button onClick={() => void loadQueue()} className="secondary-action w-full justify-center">查看更新后的复习计划</button>
        </div>
      )}
    </div>
  );
}
