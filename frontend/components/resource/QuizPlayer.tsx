"use client";

import { useMemo, useState } from "react";
import { Badge, Notice, Stat, masteryTone } from "@/components/ui";
import { USER_ID, apiPost } from "@/lib/api";
import type { PathPlan, QuizQuestion } from "@/lib/types";

interface Report {
  accuracy: number;
  items?: {
    question_id: string;
    correct: boolean;
    expected?: string;
    explain?: string;
    error_tags?: string[];
  }[];
  per_kp: { name: string; mastery: number; level: string; right: number; n: number }[];
  suggestions: string[];
  path?: PathPlan;
  profile_version?: number;
}

const TYPE_LABEL: Record<string, string> = {
  single: "单选",
  fill: "填空",
  judge: "判断",
  design: "简答",
  complexity: "复杂度",
};

function normalize(s: string) {
  return s.trim().toLowerCase().replace(/\s+/g, "").replace(/[()（）]/g, "");
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

function displayAnswer(q: QuizQuestion, answer: string): string {
  if (q.type !== "single" && !(q.type === "complexity" && q.options.length > 0)) return answer;
  const letter = choiceLetter(q.options, answer);
  if (!letter) return answer;
  const option = q.options[letter.charCodeAt(0) - 65];
  return option ? `${letter}. ${option.replace(/^[A-D][.、：:\s]*/i, "")}` : letter;
}

function isCorrect(q: QuizQuestion, ans: string): boolean {
  if (!ans) return false;
  if (q.type === "single" || (q.type === "complexity" && q.options.length > 0)) {
    return choiceLetter(q.options, ans) === choiceLetter(q.options, q.answer);
  }
  if (q.type === "judge") {
    const yes = ["对", "true", "t", "yes", "y", "正确"];
    return yes.includes(normalize(ans)) === yes.includes(normalize(q.answer));
  }
  if (q.type === "fill" || q.type === "complexity") return normalize(ans) === normalize(q.answer);
  return ans.trim().length >= 8;
}

export default function QuizPlayer({
  resourceId,
  questions,
  onEvaluated,
}: {
  resourceId: string;
  questions: QuizQuestion[];
  onEvaluated?: (report: Report) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const results = useMemo(
    () => Object.fromEntries(questions.map((q) => [q.id, isCorrect(q, answers[q.id] || "")])),
    [questions, answers],
  );
  const graded = useMemo(
    () => Object.fromEntries((report?.items || []).map((item) => [item.question_id, item])),
    [report],
  );
  const wrongTags = useMemo(() => {
    return Array.from(
      new Set(
        (report?.items || [])
          .filter((item) => !item.correct)
          .flatMap((item) => item.error_tags || []),
      ),
    );
  }, [report]);
  const answered = Object.keys(answers).filter((id) => answers[id]).length;
  const set = (id: string, v: string) => !submitted && !busy && setAnswers((a) => ({ ...a, [id]: v }));

  if (questions.length === 0) {
    return <Notice tone="warn" title="题组为空" desc="当前资源没有可作答的问题。" />;
  }

  async function submit() {
    setBusy(true);
    setSubmitError("");
    try {
      const rep = await apiPost<Report>("/eval/submit", {
        user_id: USER_ID,
        quiz_resource_id: resourceId,
        kp: questions[0]?.kp || "",
        answers: questions.map((q) => ({
          question_id: q.id,
          answer: answers[q.id] || "",
          correct: results[q.id],
          seconds: 0,
        })),
        behavior: {},
      });
      setReport(rep);
      setSubmitted(true);
      onEvaluated?.(rep);
    } catch (error) {
      setReport(null);
      setSubmitError(error instanceof Error ? error.message : "报告生成失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-[11px] leading-4 text-slate-500">
        <Badge variant="info">练习会校准画像</Badge>
        <span>提交后会自动判分、更新掌握度、记录错因,并调整后续学习安排。</span>
      </div>

      <div className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:grid-cols-3">
        <Stat label="题目数" value={questions.length} tone="neutral" />
        <Stat label="已作答" value={answered} tone={answered === questions.length ? "success" : "action"} />
        <Stat label="状态" value={submitted ? "已提交" : "待提交"} tone={submitted ? "success" : "muted"} />
      </div>

      {questions.map((q, i) => {
        const mine = answers[q.id] || "";
        const gradedItem = graded[q.id];
        const ok = gradedItem ? Boolean(gradedItem.correct) : results[q.id];
        const expected = gradedItem?.expected || q.answer;
        const expectedLetter = choiceLetter(q.options, expected);
        return (
          <div key={q.id} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-start gap-2">
              <Badge variant="info" mono>Q{i + 1}</Badge>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold leading-6 text-slate-950">{q.stem}</div>
                <div className="mt-1 flex flex-wrap gap-2">
                  <Badge variant="neutral">{TYPE_LABEL[q.type] || q.type}</Badge>
                  <Badge variant="neutral" mono>D{q.difficulty}</Badge>
                  {q.error_tags?.slice(0, 2).map((tag) => <Badge key={tag} variant="warn">{tag}</Badge>)}
                </div>
              </div>
            </div>

            {q.type === "single" || (q.type === "complexity" && q.options.length > 0) ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {q.options.map((op, j) => {
                  const tag = String.fromCharCode(65 + j);
                  const chosen = mine === tag;
                  const isAns = submitted && expectedLetter === tag;
                  return (
                    <button
                      key={j}
                      onClick={() => set(q.id, tag)}
                      className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
                        isAns
                          ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                          : chosen
                            ? submitted
                              ? "border-rose-300 bg-rose-50 text-rose-700"
                              : "border-emerald-300 bg-emerald-50 text-emerald-700"
                            : "border-slate-200 bg-slate-50 text-slate-700 hover:border-emerald-200 hover:bg-emerald-50"
                      }`}
                    >
                      <span className="mr-2 font-mono text-[11px] font-bold text-emerald-600">{tag}</span>
                      {op.replace(/^[A-D][.、：:\s]*/, "")}
                    </button>
                  );
                })}
              </div>
            ) : q.type === "judge" ? (
              <div className="flex gap-2">
                {["对", "错"].map((v) => {
                  const chosen = mine === v;
                  const isAns = submitted && normalize(expected) === normalize(v);
                  return (
                    <button
                      key={v}
                      onClick={() => set(q.id, v)}
                      className={`rounded-lg border px-4 py-2 text-xs font-bold ${
                        isAns
                          ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                          : chosen
                            ? submitted
                              ? "border-rose-300 bg-rose-50 text-rose-700"
                              : "border-emerald-300 bg-emerald-50 text-emerald-700"
                            : "border-slate-200 bg-slate-50 text-slate-700 hover:border-emerald-200"
                      }`}
                    >
                      {v}
                    </button>
                  );
                })}
              </div>
            ) : (
              <textarea
                value={mine}
                onChange={(e) => set(q.id, e.target.value)}
                rows={q.type === "fill" ? 1 : 3}
                placeholder={q.type === "fill" ? "填写答案" : "写下你的思路与答案"}
                className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100"
              />
            )}

            {submitted && (
              <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-orange-200 bg-orange-50 text-orange-700"}`}>
                <div className="font-bold">{ok ? "回答正确" : `参考答案：${displayAnswer(q, expected)}`}</div>
                {(gradedItem?.explain || q.explain) && <div className="mt-1 text-slate-600">{gradedItem?.explain || q.explain}</div>}
                {!ok && (gradedItem?.error_tags || q.error_tags)?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(gradedItem?.error_tags || q.error_tags).map((tag) => <Badge key={tag} variant="warn">{tag}</Badge>)}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {!submitted ? (
        <div className="space-y-2">
          {submitError && <Notice tone="warn" title="报告生成失败" desc={`${submitError}。答案已保留，可直接重试。`} />}
          <button
            onClick={submit}
            disabled={busy || Object.keys(answers).length === 0}
            className="w-full rounded-lg bg-emerald-600 py-3 text-sm font-black text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "正在判分并更新掌握度..." : submitError ? "重新提交" : "提交并更新掌握度"}
          </button>
        </div>
      ) : busy ? (
        <div className="text-center font-mono text-xs text-slate-500">正在判分并更新掌握度...</div>
      ) : report ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs">
          <div className="mb-3 font-mono text-[11px] tracking-[0.18em] text-emerald-600">EVAL REPORT</div>
          <div className="grid gap-2 sm:grid-cols-3">
            <Stat label="正确率" value={`${Math.round(report.accuracy * 100)}%`} tone={report.accuracy >= 0.7 ? "success" : "warn"} />
            <Stat label="知识点" value={report.per_kp[0]?.name || "-"} tone="neutral" />
            <Stat
              label="掌握度"
              value={report.per_kp[0] ? `${Math.round(report.per_kp[0].mastery * 100)}%` : "-"}
              tone={report.per_kp[0] ? masteryTone(report.per_kp[0].mastery) : "muted"}
            />
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-4">
            <div className="rounded-lg border border-emerald-200 bg-white p-3">
              <Badge variant="success" mono>01</Badge>
              <div className="mt-2 text-xs font-bold text-slate-900">判分完成</div>
              <div className="mt-1 text-[11px] leading-5 text-slate-500">
                {report.items?.filter((item) => item.correct).length ?? Math.round(report.accuracy * questions.length)} / {questions.length} 题正确
              </div>
            </div>
            <div className="rounded-lg border border-emerald-200 bg-white p-3">
              <Badge variant="info" mono>02</Badge>
              <div className="mt-2 text-xs font-bold text-slate-900">掌握度回写</div>
              <div className="mt-1 text-[11px] leading-5 text-slate-500">
                {report.per_kp[0] ? `${report.per_kp[0].name} ${Math.round(report.per_kp[0].mastery * 100)}%` : "等待评估"}
              </div>
            </div>
            <div className="rounded-lg border border-orange-200 bg-white p-3">
              <Badge variant={wrongTags.length ? "warn" : "neutral"} mono>03</Badge>
              <div className="mt-2 text-xs font-bold text-slate-900">错因标签</div>
              <div className="mt-1 text-[11px] leading-5 text-slate-500">
                {wrongTags.length ? wrongTags.slice(0, 3).join(" / ") : "暂无错因"}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <Badge variant="info" mono>04</Badge>
              <div className="mt-2 text-xs font-bold text-slate-900">后续安排</div>
              <div className="mt-1 text-[11px] leading-5 text-slate-500">
                {report.path?.next_kp ? `下一步：${report.path.next_kp}` : "系统会按新掌握度调整下一步"}
              </div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {report.suggestions.map((s, i) => <Badge key={i} variant="info">{s}</Badge>)}
          </div>
          {report.profile_version != null && (
            <div className="mt-3 rounded-md border border-emerald-200 bg-white px-3 py-2 font-mono text-[11px] text-emerald-700">
              学习档案已更新到 v{report.profile_version}
            </div>
          )}
          <div className="mt-2 font-mono text-[11px] text-slate-500">后续学习安排已按新掌握度更新</div>
        </div>
      ) : null}
    </div>
  );
}
