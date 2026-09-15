"use client";

import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CalendarDays,
  Check,
  Download,
  Play,
  RotateCcw,
  Target,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "@/components/chat/Markdown";
import { apiGet, apiPost } from "@/lib/api";
import {
  downloadMarkdown,
  type Assessment,
  type StudySurvey,
  type StudyTask,
} from "@/lib/assessment";

const DEFAULT_SURVEY: StudySurvey = {
  daily_minutes: 30,
  study_days: [1, 2, 3, 4, 5],
  goal: "掌握课程基础",
  stage: "大学课程",
  prior_experience: "不确定",
  pressure: "skip",
  study_habit: "skip",
  support: "",
  target_date: null,
};
const WEEK = ["一", "二", "三", "四", "五", "六", "日"];

function SurveyForm({
  initial,
  busy,
  isReplan,
  onSubmit,
  onCancel,
}: {
  initial: StudySurvey;
  busy: boolean;
  isReplan: boolean;
  onSubmit: (survey: StudySurvey, mode: Assessment["mode"]) => void;
  onCancel: () => void;
}) {
  const [survey, setSurvey] = useState(initial);
  const [mode, setMode] = useState<Assessment["mode"]>("comprehensive");
  const set = <K extends keyof StudySurvey>(key: K, value: StudySurvey[K]) =>
    setSurvey((s) => ({ ...s, [key]: value }));
  return (
    <form
      className="entry-setup"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(survey, mode);
      }}
    >
      <div className="entry-intro">
        <span className="entry-symbol">
          <Target size={26} />
        </span>
        <p className="entry-eyebrow">YOUR STARTING POINT</p>
        <h2>{isReplan ? "让计划适合现在的你" : "先找到起点，再往前走"}</h2>
        <p>
          当前课程：数据结构与算法。
          {isReplan
            ? "调整时间后，根据已有作答重新安排未来两周。"
            : "先了解你的安排，再用真实题目检查基础、应用和常见混淆。可以分几次完成。"}
        </p>
      </div>
      {!isReplan && (
        <fieldset className="entry-modes">
          <legend>选择摸底范围</legend>
          <label className={mode === "comprehensive" ? "is-selected" : ""}>
            <input
              type="radio"
              name="assessment-mode"
              checked={mode === "comprehensive"}
              onChange={() => setMode("comprehensive")}
            />
            <span>
              <strong>课程全面摸底</strong>
              <small>16 个知识点 · 最多 48 题 · 约 25–40 分钟</small>
            </span>
          </label>
          <label className={mode === "foundation" ? "is-selected" : ""}>
            <input
              type="radio"
              name="assessment-mode"
              checked={mode === "foundation"}
              onChange={() => setMode("foundation")}
            />
            <span>
              <strong>先检查入门基础</strong>
              <small>6 个知识点 · 通常 18 题 · 约 10–15 分钟</small>
            </span>
          </label>
        </fieldset>
      )}
      <div className="entry-fields">
        <label>
          这阶段的目标
          <select
            value={survey.goal}
            onChange={(e) => set("goal", e.target.value)}
          >
            {[
              "掌握课程基础",
              "准备课程考试",
              "考研 408 复习",
              "竞赛与算法练习",
              "编程项目应用",
              "兴趣理解",
            ].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          每天可用时间（分钟）
          <input
            type="number"
            min={8}
            max={180}
            required
            value={survey.daily_minutes}
            onChange={(e) => set("daily_minutes", Number(e.target.value))}
          />
        </label>
        <label>
          学习阶段
          <select
            value={survey.stage}
            onChange={(e) => set("stage", e.target.value)}
          >
            {[
              "大学课程",
              "高中提前学习",
              "考研复习",
              "工作后自学",
              "不方便回答",
            ].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          目标日期（选填）
          <input
            type="date"
            min={new Intl.DateTimeFormat("en-CA", {
              timeZone: "Asia/Shanghai",
            }).format(new Date())}
            value={survey.target_date || ""}
            onChange={(e) => set("target_date", e.target.value || null)}
          />
          <small>日期前安排不下的内容会保留在待安排清单。</small>
        </label>
      </div>
      <fieldset className="entry-week">
        <legend>哪些天可以学习？</legend>
        <div>
          {WEEK.map((name, i) => (
            <label
              key={name}
              className={survey.study_days.includes(i + 1) ? "is-selected" : ""}
            >
              <input
                type="checkbox"
                checked={survey.study_days.includes(i + 1)}
                onChange={(e) =>
                  set(
                    "study_days",
                    e.target.checked
                      ? [...survey.study_days, i + 1].sort()
                      : survey.study_days.filter((day) => day !== i + 1),
                  )
                }
              />
              <span>周{name}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <details className="entry-context" open>
        <summary>
          学习经历与支持需求 <span>选填，不计入成绩</span>
        </summary>
        <div className="entry-fields">
          <label>
            已有学习经历
            <select
              value={survey.prior_experience}
              onChange={(e) => set("prior_experience", e.target.value)}
            >
              {[
                "不确定",
                "第一次系统学习",
                "学过概念但做题困难",
                "能做基础题",
                "做过综合题或项目",
                "不方便回答",
              ].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            平时主要怎样复习？
            <select
              value={survey.study_habit}
              onChange={(e) =>
                set("study_habit", e.target.value as StudySurvey["study_habit"])
              }
            >
              <option value="skip">暂不回答</option>
              <option value="reread">重读、看课、划重点</option>
              <option value="practice">做题后核对答案</option>
              <option value="mixed">讲解、回忆与练习交替</option>
            </select>
          </label>
          <label>
            最近学习的感受
            <select
              value={survey.pressure}
              onChange={(e) =>
                set("pressure", e.target.value as StudySurvey["pressure"])
              }
            >
              <option value="skip">暂不回答</option>
              <option value="normal">可以按自己的节奏推进</option>
              <option value="high">有点吃力，希望任务更小</option>
            </select>
          </label>
          <label>
            希望怎样帮助你？
            <input
              value={survey.support}
              maxLength={120}
              onChange={(e) => set("support", e.target.value)}
              placeholder="例如：步骤写细一些，多解释符号"
            />
          </label>
        </div>
      </details>
      <p className="entry-note">
        自述只调整学习安排与讲解支持。摸底依据独立作答，不限单题用时；这不是智力、性格或心理健康测评。
      </p>
      <div className="entry-actions">
        <button
          type="button"
          className="secondary-action"
          onClick={onCancel}
          disabled={busy}
        >
          稍后再做
        </button>
        <button
          className="primary-action"
          disabled={busy || !survey.study_days.length}
        >
          {busy ? "正在保存…" : isReplan ? "保存并重新安排" : "开始独立作答"}
          <ArrowRight size={16} />
        </button>
      </div>
    </form>
  );
}

export default function AssessmentPanel({
  onBack,
  onLearn,
  onCourses,
  onUpdated,
  initialSurvey = {},
}: {
  onBack: () => void;
  onLearn: (prompt: string) => void;
  onCourses: (kp?: string) => void;
  onUpdated: () => void;
  initialSurvey?: Partial<StudySurvey>;
}) {
  const [data, setData] = useState<Assessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const [setup, setSetup] = useState(false);
  const [replan, setReplan] = useState(false);
  const [choice, setChoice] = useState("");
  const [confidence, setConfidence] = useState<number | null>(null);
  const started = useRef(Date.now());
  const questionHeading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const load = async () => {
    setLoading(true);
    setError("");
    setLoadFailed(false);
    try {
      const response = await apiGet<{ assessment: Assessment | null }>(
        "/assessment",
      );
      setData(response.assessment);
    } catch {
      setLoadFailed(true);
      setError(
        "暂时无法读取测评。请检查连接后重试，已提交的答案仍保存在账户中。",
      );
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    setChoice("");
    setConfidence(null);
    started.current = Date.now();
    questionHeading.current?.focus({ preventScroll: true });
    panel.current?.scrollTo({ top: 0 });
  }, [data?.question?.id, data?.status, setup]);
  const submit = async (status: "answered" | "dont_know" | "skipped") => {
    if (!data?.question || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await apiPost<Assessment>(
        `/assessment/${data.id}/answers`,
        {
          revision: data.revision,
          question_id: data.question.id,
          status,
          choice: status === "answered" ? choice : null,
          confidence: status === "answered" ? confidence : null,
          elapsed_ms: Math.min(86_400_000, Date.now() - started.current),
        },
      );
      setData(response);
      if (response.status === "completed") onUpdated();
    } catch (e) {
      setError(
        `${e instanceof Error ? e.message : "提交失败"}。可重试当前提交，重复请求不会重复计分。`,
      );
    } finally {
      setBusy(false);
    }
  };
  const saveSurvey = async (survey: StudySurvey, mode: Assessment["mode"]) => {
    setBusy(true);
    setError("");
    try {
      setData(
        await apiPost<Assessment>(
          replan && data
            ? `/assessment/${data.id}/replan`
            : "/assessment/start",
          { survey, mode },
        ),
      );
      setSetup(false);
      setReplan(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      setBusy(false);
    }
  };
  const toggle = async (task: StudyTask) => {
    if (!data || busy) return;
    setBusy(true);
    setError("");
    try {
      setData(
        await apiPost<Assessment>(`/assessment/${data.id}/tasks/${task.id}`, {
          done: !task.done,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新失败");
    } finally {
      setBusy(false);
    }
  };
  const report = data?.report;
  const plan = data?.plan;
  const allTasks = plan?.days.flatMap((day) => day.tasks) || [];
  const exportPlan = () => {
    if (!plan) return;
    downloadMarkdown(
      "我的两周学习计划",
      `# ${plan.goal}\n\n${plan.rule}\n\n${plan.support}\n\n${plan.reflection}\n\n${plan.days
        .filter((d) => d.capacity)
        .map(
          (d) =>
            `## ${d.date} · ${d.minutes}/${d.capacity} 分钟\n\n${d.tasks.map((t) => `- [${t.done ? "x" : " "}] ${t.title}（${t.minutes} 分钟）\n  - 依据：${t.reason}\n  - 完成标准：${t.criterion}`).join("\n")}`,
        )
        .join(
          "\n\n",
        )}\n\n## 待安排\n\n${plan.deferred.map((t) => `- ${t.title}：${t.deferred_reason}`).join("\n")}`,
    );
  };
  return (
    <div
      ref={panel}
      className="notebook-content-scroll entry-panel"
      aria-busy={loading || busy}
    >
      <div className="notebook-content-heading">
        <div>
          <span>ASSESS · PLAN · LEARN</span>
          <h1>起点测评与学习计划</h1>
          <p>每一步，都有作答依据。</p>
        </div>
        <button className="secondary-action" onClick={onBack}>
          <ArrowLeft size={15} />
          返回对话
        </button>
      </div>
      {error && (
        <div className="entry-error" role="alert">
          {error}
          <button type="button" onClick={() => void load()} disabled={busy}>
            重新读取
          </button>
        </div>
      )}
      {loading ? (
        <p className="entry-loading" role="status">
          正在读取你的学习起点…
        </p>
      ) : loadFailed ? null : !data || setup ? (
        <SurveyForm
          key={`${data?.id || "new"}-${replan}`}
          initial={data?.survey || { ...DEFAULT_SURVEY, ...initialSurvey }}
          busy={busy}
          isReplan={replan}
          onSubmit={(s, m) => void saveSurvey(s, m)}
          onCancel={() => (data ? setSetup(false) : onBack())}
        />
      ) : data.status === "active" && data.question ? (
        <div className="entry-quiz">
          <div className="entry-progress-label">
            <span>
              已提交 {data.answered} 题 / 最多 {data.maximum} 题
            </span>
            <span>每题提交后自动保存</span>
          </div>
          <progress
            aria-label="摸底进度"
            max={data.maximum}
            value={data.answered}
          />
          <div className="entry-question-card">
            <p className="entry-eyebrow">
              {data.question.topic} · 第 {data.answered + 1} 题
            </p>
            <h2 tabIndex={-1} ref={questionHeading}>
              {data.question.stem}
            </h2>
            <fieldset className="entry-options" disabled={busy}>
              <legend className="sr-only">选择一个答案</legend>
              {data.question.options.map((option, index) => {
                const key = String.fromCharCode(65 + index);
                return (
                  <label
                    key={key}
                    className={choice === key ? "is-selected" : ""}
                  >
                    <input
                      type="radio"
                      name="entry-answer"
                      value={key}
                      checked={choice === key}
                      onChange={() => setChoice(key)}
                    />
                    <b>{key}</b>
                    <span>{option}</span>
                    {choice === key && <Check size={18} />}
                  </label>
                );
              })}
            </fieldset>
            <fieldset className="entry-confidence" disabled={busy}>
              <legend>
                你对这个答案有多大把握？
                <small>选填，用来对照信心与实际表现</small>
              </legend>
              <div>
                {[
                  { v: 0.25, t: "在猜" },
                  { v: 0.6, t: "有些把握" },
                  { v: 0.9, t: "很确定" },
                  { v: null, t: "不记录" },
                ].map(({ v, t }) => (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={confidence === v}
                    onClick={() => setConfidence(v)}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </fieldset>
            <div className="entry-actions">
              <button
                className="secondary-action"
                disabled={busy}
                onClick={() => void submit("dont_know")}
              >
                这题还不会
              </button>
              <button
                className="primary-action"
                disabled={busy || !choice}
                onClick={() => void submit("answered")}
              >
                {busy ? "正在保存…" : "提交，继续下一题"}
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
          <div className="entry-quiz-footer">
            <button disabled={busy} onClick={() => void submit("skipped")}>
              暂时跳过此题
            </button>
            <button disabled={busy} onClick={onBack}>
              暂停，稍后继续
            </button>
          </div>
          <p className="entry-note">
            “还不会”会作为当前学习起点；“暂时跳过”不当作答错，可能需要补测。请独立作答，完成后统一查看解析。
          </p>
        </div>
      ) : report && plan ? (
        <div className="entry-results">
          <section className="entry-result-hero">
            <span className="entry-symbol">
              <Check size={26} />
            </span>
            <div>
              <p className="entry-eyebrow">从这里开始</p>
              <h2>你的学习起点，已经清楚了一些</h2>
              <p>
                本次完成 {report.coverage}/{report.total_skills}{" "}
                个知识点的初步测评。
                {data.mode === "foundation"
                  ? "范围为入门基础，其他章节仍需测评。"
                  : "从薄弱环节开始，逐步用新题验证。"}
              </p>
            </div>
          </section>
          <p className="entry-note">{report.boundary}</p>
          <section>
            <div className="entry-section-heading">
              <h2>
                <Target size={18} />
                知识点表现
              </h2>
              <button
                onClick={() => {
                  setReplan(false);
                  setSetup(true);
                }}
                className="secondary-action"
              >
                <RotateCcw size={14} />
                重新摸底
              </button>
            </div>
            <div className="entry-skill-grid">
              {report.skills.map((skill) => (
                <article
                  key={skill.kp}
                  className={`entry-skill is-${skill.status}`}
                >
                  <div>
                    <h3>{skill.name}</h3>
                    <span>{skill.label}</span>
                  </div>
                  <p>
                    {skill.attempts
                      ? `独立作答 ${skill.correct}/${skill.attempts} 题正确`
                      : "暂无独立作答"}
                  </p>
                  {skill.high_confidence_errors > 0 && (
                    <small>
                      有 {skill.high_confidence_errors}{" "}
                      题很确定但答错，建议解释原因后再复测。
                    </small>
                  )}
                  <button onClick={() => onCourses(skill.kp)}>
                    找对应网课 <ArrowRight size={13} />
                  </button>
                </article>
              ))}
            </div>
          </section>
          {report.calibration_samples > 0 && (
            <p className="entry-note">
              记录了 {report.calibration_samples}{" "}
              次答题信心。对照下面的解析，找出“以为会了”和“已经能独立完成”的差别；不据此给你贴能力标签。
            </p>
          )}
          <section>
            <div className="entry-section-heading">
              <h2>
                <CalendarDays size={18} />
                接下来两周
              </h2>
              <div className="entry-inline-actions">
                <button
                  className="secondary-action"
                  onClick={() => {
                    setReplan(true);
                    setSetup(true);
                  }}
                >
                  调整安排
                </button>
                <button className="secondary-action" onClick={exportPlan}>
                  <Download size={14} />
                  导出计划
                </button>
              </div>
            </div>
            <div className="entry-plan-intro">
              <strong>{plan.goal}</strong>
              <p>{plan.support}</p>
              <p>{plan.reflection}</p>
            </div>
            <p className="entry-note">{plan.rule}</p>
            <div className="entry-calendar">
              {plan.days
                .filter((day) => day.capacity > 0)
                .map((day) => (
                  <article key={day.date} className="entry-day">
                    <header>
                      <h3>
                        {new Intl.DateTimeFormat("zh-CN", {
                          month: "short",
                          day: "numeric",
                          weekday: "short",
                        }).format(new Date(`${day.date}T12:00:00+08:00`))}
                      </h3>
                      <span>
                        {day.minutes} / {day.capacity} 分钟
                      </span>
                    </header>
                    {day.tasks.length ? (
                      day.tasks.map((task) => {
                        const blocked = task.requires.some(
                          (id) => !allTasks.find((t) => t.id === id)?.done,
                        );
                        return (
                          <div
                            key={task.id}
                            className={`entry-task ${task.done ? "is-done" : ""}`}
                          >
                            <input
                              type="checkbox"
                              aria-label={`完成 ${task.title}`}
                              checked={task.done}
                              disabled={busy || (!task.done && blocked)}
                              onChange={() => void toggle(task)}
                            />
                            <div>
                              <strong>{task.title}</strong>
                              <small>
                                {task.reason} · {task.minutes} 分钟
                              </small>
                              <details>
                                <summary>完成标准</summary>
                                <p>{task.criterion}</p>
                              </details>
                              {blocked && !task.done && (
                                <small>先完成前置任务</small>
                              )}
                            </div>
                            <button
                              className="entry-start-task"
                              disabled={blocked}
                              onClick={() => onLearn(task.goal)}
                              aria-label={`开始 ${task.title}`}
                            >
                              <Play size={14} />
                              开始
                            </button>
                          </div>
                        );
                      })
                    ) : (
                      <p className="entry-rest">留作休息或机动调整。</p>
                    )}
                  </article>
                ))}
            </div>
            {plan.deferred.length > 0 && (
              <details className="entry-context">
                <summary>还有 {plan.deferred.length} 项待安排</summary>
                <p className="entry-note">
                  当前日期与时间预算内无法全部安排。可增加学习日、调整目标日期，或下轮继续；待补测内容需要先补充证据。
                </p>
                <ul>
                  {plan.deferred.map((task) => (
                    <li key={task.id}>
                      {task.title} · {task.deferred_reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
          <section>
            <div className="entry-section-heading">
              <h2>
                <BookOpen size={18} />
                为你整理的学习资料
              </h2>
              <button className="secondary-action" onClick={() => onCourses()}>
                查看推荐网课
              </button>
            </div>
            {data.materials.length ? (
              data.materials.map((material) => (
                <details className="entry-material" key={material.id}>
                  <summary>{material.title}</summary>
                  <button
                    className="secondary-action"
                    onClick={() =>
                      downloadMarkdown(material.title, material.markdown)
                    }
                  >
                    <Download size={14} />
                    下载 Markdown
                  </button>
                  <Markdown text={material.markdown} allowCodeBlocks />
                </details>
              ))
            ) : (
              <p className="entry-note">
                目前尚未形成足够的薄弱点证据。先完成补测或迁移验证，再生成针对性资料。
              </p>
            )}
          </section>
          <section>
            <h2 className="entry-section-title">逐题解析与复盘</h2>
            {report.explanations.map((item, i) => (
              <details className="entry-explanation" key={item.id}>
                <summary>
                  <span
                    className={
                      item.status === "skipped"
                        ? ""
                        : item.correct
                          ? "is-correct"
                          : "is-wrong"
                    }
                  >
                    {item.status === "skipped"
                      ? "跳过"
                      : item.correct
                        ? "答对"
                        : "待巩固"}
                  </span>
                  {i + 1}. {item.stem}
                </summary>
                <p>
                  <strong>参考答案：</strong>
                  {item.answer}
                </p>
                <p>{item.explain}</p>
              </details>
            ))}
          </section>
        </div>
      ) : null}
    </div>
  );
}
