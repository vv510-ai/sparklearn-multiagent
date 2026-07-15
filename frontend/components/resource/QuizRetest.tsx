"use client";

import { useMemo, useRef, useState } from "react";
import { Badge, Notice, Stat, masteryTone } from "@/components/ui";
import { USER_ID, apiPost } from "@/lib/api";
import type { LearningDiagnosis, PathPlan, QuizQuestion } from "@/lib/types";
import ConfidencePicker, { calibrationSignalText, type ConfidenceLevel } from "./ConfidencePicker";

export interface EvaluationItem {
  review_item_id?: number;
  quiz_resource_id?: string;
  question_id: string;
  correct: boolean;
  mastery_correct?: boolean;
  expected?: string;
  explain?: string;
  error_tags?: string[];
  hint_used?: boolean;
  revealed?: boolean;
  misconception?: string;
  support_level?: "independent" | "hinted" | "revealed";
  evidence_phase?: "initial" | "retest" | "spaced_review";
  confidence?: ConfidenceLevel;
  calibration_signal?: string;
}

export interface EvaluationReport {
  accuracy: number;
  items?: EvaluationItem[];
  per_kp: { name: string; mastery: number; level: string; right: number; n: number }[];
  suggestions: string[];
  path?: PathPlan;
  profile_version?: number;
  attempt_id?: number;
  retest?: {
    status: "ready" | "not_needed" | "completed";
    eligible_question_ids?: string[];
    eligible?: number;
    recovered?: number;
    remaining?: number;
  };
  behavior?: {
    phase?: "retest" | "spaced_review";
    support?: {
      hinted: number;
      revealed: number;
      independent: number;
      misconceptions: string[];
    };
  };
  calibration?: {
    recorded: number;
    score: number | null;
    confident_wrong: number;
    uncertain_correct: number;
    metacognition_before: number;
    metacognition_after: number;
  };
  diagnosis?: LearningDiagnosis;
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

function displayAnswer(question: QuizQuestion, answer: string): string {
  if (question.type !== "single" && !(question.type === "complexity" && question.options.length > 0)) {
    return answer;
  }
  const letter = choiceLetter(question.options, answer);
  const option = question.options[letter.charCodeAt(0) - 65];
  return option ? `${letter}. ${option.replace(/^[A-D][.、：:\s]*/i, "")}` : answer;
}

export default function QuizRetest({
  resourceId,
  attemptId,
  questions,
  onEvaluated,
}: {
  resourceId: string;
  attemptId: number;
  questions: QuizQuestion[];
  onEvaluated?: (report: EvaluationReport) => void;
}) {
  const [started, setStarted] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [confidences, setConfidences] = useState<Record<string, ConfidenceLevel>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<EvaluationReport | null>(null);
  const startedAt = useRef<Record<string, number>>({});
  const resultItems = useMemo(
    () => Object.fromEntries((result?.items || []).map((item) => [item.question_id, item])),
    [result],
  );
  const answered = questions.filter((question) => (answers[question.id] || "").trim()).length;
  const pendingConfidence = questions.filter((question) => (
    (answers[question.id] || "").trim() && !confidences[question.id]
  )).length;

  if (questions.length === 0) return null;

  function setAnswer(questionId: string, value: string) {
    if (busy || result) return;
    if (!startedAt.current[questionId]) startedAt.current[questionId] = Date.now();
    if (answers[questionId] !== value) {
      setConfidences((saved) => {
        const next = { ...saved };
        delete next[questionId];
        return next;
      });
    }
    setAnswers((current) => ({ ...current, [questionId]: value }));
  }

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const report = await apiPost<EvaluationReport>("/eval/retest", {
        user_id: USER_ID,
        quiz_resource_id: resourceId,
        attempt_id: attemptId,
        answers: questions.map((question) => ({
          question_id: question.id,
          answer: answers[question.id] || "",
          seconds: startedAt.current[question.id]
            ? Math.max(1, Math.round((Date.now() - startedAt.current[question.id]) / 1000))
            : 0,
          confidence: confidences[question.id] || "",
        })),
      });
      setResult(report);
      onEvaluated?.(report);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复测提交失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  if (!started) {
    return (
      <div className="mt-4 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sky-900">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Badge variant="info" mono>RETEST</Badge>
              <span className="text-xs font-bold">无提示恢复测</span>
            </div>
            <p className="mt-1 text-[11px] leading-5 text-slate-600">
              {questions.length} 道题还没有形成独立掌握证据。重新独立答对后，系统才会更新恢复后的掌握度。
            </p>
          </div>
          <button
            type="button"
            onClick={() => setStarted(true)}
            className="rounded-md bg-sky-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-sky-700"
          >
            开始无提示复测
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-3 rounded-xl border border-sky-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <Badge variant="info" mono>RETEST</Badge>
            <span className="text-sm font-black text-slate-900">无提示恢复测</span>
          </div>
          <div className="mt-1 text-[11px] text-slate-500">不提供提示或揭晓；请一次完成全部待恢复题。</div>
        </div>
        {!result && <Badge variant="neutral">已作答 {answered}/{questions.length}</Badge>}
      </div>

      {questions.map((question, index) => {
        const mine = answers[question.id] || "";
        const graded = resultItems[question.id];
        return (
          <div key={question.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex items-start gap-2">
              <Badge variant="neutral" mono>R{index + 1}</Badge>
              <div className="text-xs font-bold leading-5 text-slate-900">{question.stem}</div>
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
                      onClick={() => setAnswer(question.id, letter)}
                      className={`rounded-md border px-3 py-2 text-left text-xs transition ${
                        mine === letter
                          ? "border-sky-300 bg-sky-100 text-sky-800"
                          : "border-slate-200 bg-white text-slate-700 hover:border-sky-200"
                      } disabled:cursor-not-allowed`}
                    >
                      <span className="mr-2 font-mono font-bold text-sky-600">{letter}</span>
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
                    onClick={() => setAnswer(question.id, value)}
                    className={`rounded-md border px-4 py-2 text-xs font-bold ${
                      mine === value
                        ? "border-sky-300 bg-sky-100 text-sky-800"
                        : "border-slate-200 bg-white text-slate-700"
                    } disabled:cursor-not-allowed`}
                  >
                    {value}
                  </button>
                ))}
              </div>
            ) : (
              <textarea
                value={mine}
                disabled={Boolean(result) || busy}
                onChange={(event) => setAnswer(question.id, event.target.value)}
                rows={question.type === "fill" ? 1 : 3}
                placeholder={question.type === "fill" ? "填写答案" : "独立写下你的思路与答案"}
                className="w-full resize-none rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 disabled:bg-slate-100"
              />
            )}
            {mine.trim() && !result && (
              <ConfidencePicker
                value={confidences[question.id]}
                onChange={(value) => setConfidences((current) => ({ ...current, [question.id]: value }))}
                disabled={busy}
              />
            )}
            {graded && (
              <div className={`mt-2 rounded-md border px-3 py-2 text-xs ${
                graded.correct
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-orange-200 bg-orange-50 text-orange-700"
              }`}>
                <div className="font-bold">
                  {graded.correct ? "独立答对，已形成恢复证据" : `仍需巩固 · 参考答案：${displayAnswer(question, graded.expected || "")}`}
                </div>
                {graded.explain && <div className="mt-1 leading-5 text-slate-600">{graded.explain}</div>}
                {calibrationSignalText(graded.calibration_signal) && (
                  <div className="mt-1 font-medium text-violet-700">{calibrationSignalText(graded.calibration_signal)}</div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {error && <Notice tone="warn" title="复测提交失败" desc={`${error}。答案已保留，可直接重试。`} />}
      {!result ? (
        <button
          type="button"
          onClick={submit}
          disabled={busy || answered !== questions.length || pendingConfidence > 0}
          className="w-full rounded-lg bg-sky-600 py-2.5 text-xs font-black text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "正在校准恢复后的掌握度..." : pendingConfidence ? "请先标记作答把握" : "提交无提示复测"}
        </button>
      ) : (
        <div className="space-y-2">
          <Notice
            tone={result.retest?.remaining ? "warn" : "success"}
            title={result.retest?.remaining ? "复测完成，仍有题目需要巩固" : "复测完成，恢复证据已生效"}
            desc="掌握度与后续学习路径已按这次独立作答重新计算。"
          />
          <div className="grid gap-2 sm:grid-cols-3">
            <Stat label="恢复题数" value={result.retest?.recovered ?? 0} tone="success" />
            <Stat label="仍需巩固" value={result.retest?.remaining ?? 0} tone={result.retest?.remaining ? "warn" : "neutral"} />
            <Stat
              label="最新掌握度"
              value={result.per_kp[0] ? `${Math.round(result.per_kp[0].mastery * 100)}%` : "-"}
              tone={result.per_kp[0] ? masteryTone(result.per_kp[0].mastery) : "muted"}
            />
          </div>
        </div>
      )}
    </div>
  );
}
