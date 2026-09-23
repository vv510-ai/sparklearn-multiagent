"use client";

import MathText from "@/components/chat/MathText";

import { useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Maximize2 } from "lucide-react";
import StudyDialog from "@/components/ui/StudyDialog";
import { LearnerScope, readStudyDraft, STUDY_DRAFT_EVENT, writeStudyDraft } from "@/lib/study-workspace";
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

interface QuizDraft {
  answers: Record<string, string>;
  hints: Record<string, string>;
  reveals: Record<string, SupportResponse>;
  misconceptions: Record<string, string>;
  confidences: Record<string, ConfidenceLevel>;
  current: number;
  report: EvaluationReport | null;
}

function validDraft(value: unknown): value is QuizDraft {
  if (!value || typeof value !== "object") return false;
  const draft = value as QuizDraft;
  const strings = (record: unknown) => record && typeof record === "object" && !Array.isArray(record)
    && Object.values(record).every(item => typeof item === "string");
  return Boolean(strings(draft.answers) && strings(draft.hints) && strings(draft.misconceptions) && strings(draft.confidences)
    && draft.reveals && typeof draft.reveals === "object" && Object.values(draft.reveals).every(item => item?.mode === "reveal")
    && Number.isInteger(draft.current) && (!draft.report || (Array.isArray(draft.report.items) && Array.isArray(draft.report.per_kp)
      && Array.isArray(draft.report.suggestions) && typeof draft.report.accuracy === "number")));
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
  const learnerId = useContext(LearnerScope);
  const [focused, setFocused] = useState(false);
  const [current, setCurrent] = useState(0);
  const [restoredDraft, setRestoredDraft] = useState("");
  const draftKey = `learnloop:quiz-draft:${learnerId}:${resourceId}`;
  const instanceId = useId();
  const importingDraft = useRef(false);
  const savedSnapshot = useRef("");
  const questionRef = useRef<HTMLDivElement>(null);
  const launchRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const restore = () => {
      const saved = learnerId ? readStudyDraft(draftKey, validDraft) : null;
      if (!saved || JSON.stringify(saved) === savedSnapshot.current) return;
      savedSnapshot.current = JSON.stringify(saved);
      importingDraft.current = true;
      setAnswers(saved.answers); setHints(saved.hints); setReveals(saved.reveals);
      setMisconceptions(saved.misconceptions); setConfidences(saved.confidences);
      setCurrent(Math.max(0, Math.min(questions.length - 1, saved.current)));
      setReport(saved.report); setSubmitted(Boolean(saved.report));
    };
    restore();
    setRestoredDraft(draftKey);
    const onDraft = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.key === draftKey && detail.source !== instanceId) restore();
    };
    const onStorage = (event: StorageEvent) => { if (event.key === draftKey) restore(); };
    window.addEventListener(STUDY_DRAFT_EVENT, onDraft);
    window.addEventListener("storage", onStorage);
    return () => { window.removeEventListener(STUDY_DRAFT_EVENT, onDraft); window.removeEventListener("storage", onStorage); };
  }, [draftKey, learnerId, questions.length, instanceId]);
  useEffect(() => {
    if (importingDraft.current) { importingDraft.current = false; return; }
    if (learnerId && restoredDraft === draftKey) {
      const value = { answers, hints, reveals, misconceptions, confidences, current, report };
      savedSnapshot.current = JSON.stringify(value);
      writeStudyDraft(draftKey, value, instanceId);
    }
  }, [answers, hints, reveals, misconceptions, confidences, current, report, draftKey, learnerId, restoredDraft, instanceId]);
  useEffect(() => {
    if (!focused) return;
    const frame = requestAnimationFrame(() => {
      questionRef.current?.closest(".study-dialog-body")?.scrollTo({ top: 0 });
      questionRef.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [current, focused]);
  const closeFocus = () => {
    setFocused(false);
    requestAnimationFrame(() => launchRef.current?.focus({ preventScroll: true }));
  };

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

  const content = (
    <div className={`quiz-player space-y-4 ${focused ? "is-focused" : ""}`}>
      {!focused && <button ref={launchRef} type="button" className="study-primary quiz-focus-launch" onClick={() => setFocused(true)}><Maximize2 size={18} />{submitted ? "查看作答复盘" : answered ? "继续专注作答" : "开始专注作答"}<span>{questions.length} 题</span></button>}
      <div className="quiz-intro flex flex-wrap items-center gap-2 text-[11px] leading-4 text-slate-500">
        <Badge variant="info">练习会校准画像</Badge>
        <span>先尝试，再按需获取提示；揭晓后完成错因复盘，系统会按真实学习证据更新掌握度。</span>
      </div>

      <div className="quiz-summary grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:grid-cols-3">
        <Stat label="题目数" value={questions.length} tone="neutral" />
        <Stat label="已作答" value={answered} tone={answered === questions.length ? "success" : "action"} />
        <Stat label="状态" value={submitted ? "已提交" : "待提交"} tone={submitted ? "success" : "muted"} />
      </div>

      {questions.map((q, i) => {
        if (focused && i !== current) return null;
        const mine = answers[q.id] || "";
        const gradedItem = graded[q.id];
        const ok = gradedItem ? Boolean(gradedItem.correct) : results[q.id];
        const expected = gradedItem?.expected || q.answer;
        const expectedLetter = choiceLetter(q.options, expected);
        const revealed = reveals[q.id];
        const supportError = supportErrors[q.id];
        return (
          <div key={q.id} ref={focused ? questionRef : undefined} tabIndex={-1} className="quiz-question rounded-xl border border-slate-200 bg-white p-4" aria-label={`第 ${i + 1} 题`}>
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
                      aria-pressed={chosen}
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
                      aria-pressed={chosen}
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
                aria-label={`第 ${i + 1} 题答案`}
                onChange={(e) => set(q.id, e.target.value)}
                disabled={Boolean(revealed) || submitted || busy}
                rows={q.type === "fill" ? 2 : focused ? 7 : 4}
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
        <div className="quiz-submit-area space-y-2" hidden={focused && current !== questions.length - 1 && answered !== questions.length}>
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
        <div className="quiz-report rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs">
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
              {onOpenMistakes && <button type="button" onClick={() => { setFocused(false); onOpenMistakes(); }} className="secondary-action">打开错题本</button>}
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

  return <>
    {!focused && content}
    <StudyDialog open={focused} title={submitted ? "作答复盘" : "专注作答"} onClose={closeFocus} className="quiz-dialog"
      footer={<div className="quiz-paging">
        <button type="button" className="study-icon" disabled={current === 0} aria-label="上一题" title="上一题" onClick={() => setCurrent(index => index - 1)}><ArrowLeft size={20} /></button>
        <label><span className="sr-only">选择题目</span><select aria-label="选择题目" value={current} onChange={event => setCurrent(Number(event.target.value))}>
          {questions.map((question, index) => <option key={question.id} value={index}>第 {index + 1} / {questions.length} 题{answers[question.id]?.trim() ? " · 已作答" : ""}</option>)}
        </select></label>
        <button type="button" className="study-icon" disabled={current === questions.length - 1} aria-label="下一题" title="下一题" onClick={() => setCurrent(index => index + 1)}><ArrowRight size={20} /></button>
      </div>}>
      <progress className="quiz-progress" value={answered} max={questions.length} aria-label="作答进度" />
      {content}
    </StudyDialog>
  </>;
}
