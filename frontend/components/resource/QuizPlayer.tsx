"use client";

import MathText from "@/components/chat/MathText";

import { useMemo, useRef, useState } from "react";
import { Badge, Notice, Stat, masteryTone } from "@/components/ui";
import { USER_ID, apiPost } from "@/lib/api";
import type { QuizQuestion } from "@/lib/types";
import QuizRetest from "./QuizRetest";
import type { EvaluationReport } from "./QuizRetest";
import ConfidencePicker, { calibrationSignalText, type ConfidenceLevel } from "./ConfidencePicker";
import RemediationPanel from "./RemediationPanel";

interface SupportResponse {
  mode: "hint" | "reveal";
  question_id: string;
  hint?: string;
  expected?: string;
  explain?: string;
  error_tags?: string[];
}

const MISCONCEPTIONS = [
  "概念没记牢",
  "条件看漏了",
  "步骤顺序混乱",
  "选项辨析错误",
  "计算或推导失误",
  "会做但不熟练",
  "还不确定",
];

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
  onOpenMistakes,
}: {
  resourceId: string;
  questions: QuizQuestion[];
  onEvaluated?: (report: EvaluationReport) => void;
  onOpenMistakes?: () => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [hints, setHints] = useState<Record<string, string>>({});
  const [reveals, setReveals] = useState<Record<string, SupportResponse>>({});
  const [misconceptions, setMisconceptions] = useState<Record<string, string>>({});
  const [confidences, setConfidences] = useState<Record<string, ConfidenceLevel>>({});
  const [supportBusy, setSupportBusy] = useState("");
  const [supportErrors, setSupportErrors] = useState<Record<string, string>>({});
  const startedAt = useRef<Record<string, number>>({});

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
          .filter((item) => item.mastery_correct === false || !item.correct)
          .flatMap((item) => item.error_tags || []),
      ),
    );
  }, [report]);
  const answered = questions.filter((question) => (answers[question.id] || "").trim()).length;
  const pendingConfidence = questions.filter((question) => (
    (answers[question.id] || "").trim() && !confidences[question.id]
  )).length;
  const pendingReflections = Object.keys(reveals).filter((id) => !misconceptions[id]).length;
  const set = (id: string, v: string) => {
    if (submitted || busy || reveals[id]) return;
    if (!startedAt.current[id]) startedAt.current[id] = Date.now();
    // Once a hint is requested, preserve the confidence captured for the
    // original attempt even if the learner revises the answer afterward.
    if (answers[id] !== v && !hints[id]) {
      setConfidences((saved) => {
        const next = { ...saved };
        delete next[id];
        return next;
      });
    }
    setAnswers((current) => ({ ...current, [id]: v }));
    setSupportErrors((errors) => ({ ...errors, [id]: "" }));
  };

  if (questions.length === 0) {
    return <Notice tone="warn" title="题组为空" desc="当前资源没有可作答的问题。" />;
  }

  async function requestSupport(question: QuizQuestion, mode: "hint" | "reveal") {
    const attempt = (answers[question.id] || "").trim();
    if (!attempt) {
      setSupportErrors((errors) => ({ ...errors, [question.id]: "请先写下你的尝试" }));
      return;
    }
    if (!confidences[question.id]) {
      setSupportErrors((errors) => ({ ...errors, [question.id]: "请先记录作答时的把握，再获取学习支持" }));
      return;
    }
    setSupportBusy(`${question.id}:${mode}`);
    setSupportErrors((errors) => ({ ...errors, [question.id]: "" }));
    try {
      const result = await apiPost<SupportResponse>("/eval/support", {
        user_id: USER_ID,
        quiz_resource_id: resourceId,
        question_id: question.id,
        mode,
        attempt,
      });
      if (mode === "hint" && result.hint) {
        setHints((current) => ({ ...current, [question.id]: result.hint || "" }));
      }
      if (mode === "reveal") {
        setReveals((current) => ({ ...current, [question.id]: result }));
      }
    } catch (error) {
      setSupportErrors((errors) => ({
        ...errors,
        [question.id]: error instanceof Error ? error.message : "学习支持暂时不可用",
      }));
    } finally {
      setSupportBusy("");
    }
  }

  async function submit() {
    setBusy(true);
    setSubmitError("");
    try {
      const rep = await apiPost<EvaluationReport>("/eval/submit", {
        user_id: USER_ID,
        quiz_resource_id: resourceId,
        kp: questions[0]?.kp || "",
        answers: questions.map((q) => ({
          question_id: q.id,
          answer: answers[q.id] || "",
          correct: results[q.id],
          seconds: startedAt.current[q.id]
            ? Math.max(1, Math.round((Date.now() - startedAt.current[q.id]) / 1000))
            : 0,
          hint_used: Boolean(hints[q.id]),
          revealed: Boolean(reveals[q.id]),
          misconception: misconceptions[q.id] || "",
          confidence: confidences[q.id] || "",
        })),
        behavior: {
          hinted_question_ids: Object.keys(hints),
          revealed_question_ids: Object.keys(reveals),
          misconceptions,
          confidences,
        },
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
        <span>先尝试，再按需获取提示；揭晓后完成错因复盘，系统会按真实学习证据更新掌握度。</span>
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
        const revealed = reveals[q.id];
        const supportError = supportErrors[q.id];
        return (
          <div key={q.id} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-start gap-2">
              <Badge variant="info" mono>Q{i + 1}</Badge>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold leading-6 text-slate-950"><MathText text={q.stem} /></div>
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
                      disabled={Boolean(revealed) || submitted || busy}
                      className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
                        isAns
                          ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                          : chosen
                            ? submitted
                              ? "border-rose-300 bg-rose-50 text-rose-700"
                              : "border-emerald-300 bg-emerald-50 text-emerald-700"
                            : "border-slate-200 bg-slate-50 text-slate-700 hover:border-emerald-200 hover:bg-emerald-50"
                      } disabled:cursor-not-allowed disabled:opacity-70`}
                    >
                      <span className="mr-2 font-mono text-[11px] font-bold text-emerald-600">{tag}</span>
                      <MathText text={op.replace(/^[A-D][.、：:\s]*/, "")} />
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
                      disabled={Boolean(revealed) || submitted || busy}
                      className={`rounded-lg border px-4 py-2 text-xs font-bold ${
                        isAns
                          ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                          : chosen
                            ? submitted
                              ? "border-rose-300 bg-rose-50 text-rose-700"
                              : "border-emerald-300 bg-emerald-50 text-emerald-700"
                            : "border-slate-200 bg-slate-50 text-slate-700 hover:border-emerald-200"
                      } disabled:cursor-not-allowed disabled:opacity-70`}
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
                disabled={Boolean(revealed) || submitted || busy}
                rows={q.type === "fill" ? 1 : 3}
                placeholder={q.type === "fill" ? "填写答案" : "写下你的思路与答案"}
                className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100 disabled:cursor-not-allowed disabled:bg-slate-50"
              />
            )}

            {mine.trim() && !submitted && (
              <ConfidencePicker
                value={confidences[q.id]}
                onChange={(value) => {
                  setConfidences((current) => ({ ...current, [q.id]: value }));
                  setSupportErrors((errors) => ({ ...errors, [q.id]: "" }));
                }}
                disabled={Boolean(hints[q.id]) || Boolean(revealed) || busy}
              />
            )}

            {!submitted && (
              <div className="mt-3 space-y-2">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => requestSupport(q, "hint")}
                    disabled={Boolean(revealed) || Boolean(hints[q.id]) || supportBusy.startsWith(`${q.id}:`)}
                    className="rounded-md border border-sky-200 bg-sky-50 px-3 py-1.5 text-[11px] font-bold text-sky-700 transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {supportBusy === `${q.id}:hint` ? "正在生成提示..." : hints[q.id] ? "已使用提示" : "给我一个提示"}
                  </button>
                  <button
                    type="button"
                    onClick={() => requestSupport(q, "reveal")}
                    disabled={Boolean(revealed) || supportBusy.startsWith(`${q.id}:`)}
                    className="rounded-md border border-orange-200 bg-orange-50 px-3 py-1.5 text-[11px] font-bold text-orange-700 transition hover:bg-orange-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {supportBusy === `${q.id}:reveal` ? "正在揭晓..." : revealed ? "已揭晓" : "揭晓并复盘"}
                  </button>
                  <span className="self-center text-[11px] text-slate-400">需要先作答；揭晓后会锁定本次尝试</span>
                </div>
                {supportError && <div className="text-[11px] font-medium text-rose-600">{supportError}</div>}
                {hints[q.id] && (
                  <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs leading-5 text-sky-800">
                    <span className="font-bold">提示：</span><MathText text={hints[q.id]} />
                  </div>
                )}
                {revealed && (
                  <div className="space-y-3 rounded-lg border border-orange-200 bg-orange-50 px-3 py-3 text-xs text-orange-800">
                    <div>
                      <div className="font-bold">参考答案：<MathText text={displayAnswer(q, revealed.expected || q.answer)} /></div>
                      {revealed.explain && <div className="mt-1 leading-5 text-slate-600"><MathText text={revealed.explain} /></div>}
                    </div>
                    <div>
                      <div className="mb-2 font-bold text-slate-800">你觉得这次卡在哪里？</div>
                      <div className="flex flex-wrap gap-1.5">
                        {MISCONCEPTIONS.map((reason) => (
                          <button
                            type="button"
                            key={reason}
                            onClick={() => setMisconceptions((current) => ({ ...current, [q.id]: reason }))}
                            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                              misconceptions[q.id] === reason
                                ? "border-orange-400 bg-orange-500 font-bold text-white"
                                : "border-orange-200 bg-white text-slate-600 hover:border-orange-300"
                            }`}
                          >
                            {reason}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="text-[11px] text-orange-700">本题仍会判分，但不会作为“独立答对”抬高掌握度。</div>
                  </div>
                )}
              </div>
            )}

            {submitted && (
              <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-orange-200 bg-orange-50 text-orange-700"}`}>
                <div className="font-bold"><MathText text={ok ? "回答正确" : `参考答案：${displayAnswer(q, expected)}`} /></div>
                {gradedItem?.support_level && gradedItem.support_level !== "independent" && (
                  <div className="mt-1 font-medium text-slate-600">
                    学习证据：{gradedItem.support_level === "revealed" ? "已揭晓（不计独立掌握）" : "提示后作答"}
                  </div>
                )}
                {(gradedItem?.explain || q.explain) && <div className="mt-1 text-slate-600"><MathText text={(gradedItem?.explain || q.explain || "")} /></div>}
                {calibrationSignalText(gradedItem?.calibration_signal) && (
                  <div className="mt-1 font-medium text-violet-700">{calibrationSignalText(gradedItem?.calibration_signal)}</div>
                )}
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
          {pendingReflections > 0 && (
            <Notice tone="warn" title="还差一步错因复盘" desc={`请为已揭晓的 ${pendingReflections} 道题选择一个最接近的卡点。`} />
          )}
          {pendingConfidence > 0 && (
            <Notice tone="warn" title="还没有记录作答把握" desc={`请为已作答的 ${pendingConfidence} 道题选择“在猜 / 有点把握 / 很确定”。`} />
          )}
          {answered > 0 && answered < questions.length && (
            <Notice tone="warn" title="题组尚未完成" desc={`还剩 ${questions.length - answered} 道题；全部作答后才能正式提交。`} />
          )}
          {submitError && <Notice tone="warn" title="报告生成失败" desc={`${submitError}。答案已保留，可直接重试。`} />}
          <button
            onClick={submit}
            disabled={busy || answered !== questions.length || pendingReflections > 0 || pendingConfidence > 0}
            className="w-full rounded-lg bg-emerald-600 py-3 text-sm font-black text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "正在判分并更新掌握度..." : pendingReflections > 0 ? "请先完成错因复盘" : pendingConfidence > 0 ? "请先标记作答把握" : submitError ? "重新提交" : "提交并更新掌握度"}
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
          {report.behavior?.support && (
            <div className="mt-3 rounded-md border border-emerald-200 bg-white px-3 py-2 text-[11px] leading-5 text-slate-600">
              独立作答 {report.behavior.support.independent} 题 · 使用提示 {report.behavior.support.hinted} 题 · 揭晓复盘 {report.behavior.support.revealed} 题
              {report.behavior.support.misconceptions.length > 0 && ` · 自评错因：${report.behavior.support.misconceptions.join(" / ")}`}
            </div>
          )}
          {report.calibration && report.calibration.recorded > 0 && (
            <div className="mt-3 rounded-md border border-violet-200 bg-violet-50 px-3 py-2 text-[11px] leading-5 text-violet-800">
              信心校准 {Math.round((report.calibration.score || 0) * 100)}%
              {report.calibration.confident_wrong > 0 && ` · 自信误判 ${report.calibration.confident_wrong} 题`}
              {report.calibration.uncertain_correct > 0 && ` · 答对但不稳 ${report.calibration.uncertain_correct} 题`}
              {` · 元认知 ${Math.round(report.calibration.metacognition_before * 100)}% → ${Math.round(report.calibration.metacognition_after * 100)}%`}
            </div>
          )}
          {report.profile_version != null && (
            <div className="mt-3 rounded-md border border-emerald-200 bg-white px-3 py-2 font-mono text-[11px] text-emerald-700">
              学习档案已更新到 v{report.profile_version}
            </div>
          )}
          {wrongTags.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-orange-200 bg-white px-3 py-3">
              <div>
                <div className="text-xs font-black text-orange-800">错题已自动收入错题本</div>
                <div className="mt-1 text-[11px] text-slate-500">{report.review?.scheduled ?? wrongTags.length} 道待巩固题会保留错因、收藏状态与重做记录。</div>
              </div>
              {onOpenMistakes && <button type="button" onClick={onOpenMistakes} className="secondary-action">打开错题本</button>}
            </div>
          )}
          {report.attempt_id && report.diagnosis?.status === "needed" && (
            <RemediationPanel
              attemptId={report.attempt_id}
              diagnosis={report.diagnosis}
              onEvaluated={onEvaluated}
            />
          )}
          {report.attempt_id && report.retest?.status === "ready" && report.diagnosis?.status !== "needed" && (
            <QuizRetest
              resourceId={resourceId}
              attemptId={report.attempt_id}
              questions={questions.filter((question) => (
                report.retest?.eligible_question_ids || []
              ).includes(question.id))}
              onEvaluated={onEvaluated}
            />
          )}
          <div className="mt-2 font-mono text-[11px] text-slate-500">后续学习安排已按新掌握度更新</div>
        </div>
      ) : null}
    </div>
  );
}
