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

import LearningIntake, { DEFAULT_SURVEY } from "@/components/onboarding/LearningIntake";

const SurveyForm = LearningIntake;

export default function AssessmentPanel({
  onBack,
  onLearn,
  onCourses,
  onUpdated,
  initialSurvey = {},
  notebookId = "",
  onStarted,
}: {
  onBack: () => void;
  onLearn: (prompt: string) => void;
  onCourses: (kp?: string) => void;
  onUpdated: () => void;
  initialSurvey?: Partial<StudySurvey>;
  notebookId?: string;
  onStarted?: (assessment: Assessment) => void | Promise<void>;
}) {
  const [data, setData] = useState<Assessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const [setup, setSetup] = useState(false);
  const [replan, setReplan] = useState(false);
  const [choice, setChoice] = useState("");
  const [choices, setChoices] = useState<string[]>([]);
  const [studyTask, setStudyTask] = useState<StudyTask | null>(null);
  const studyHeading = useRef<HTMLHeadingElement>(null);
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
        `/assessment?notebook_id=${encodeURIComponent(notebookId)}`,
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
  }, [notebookId]);
  useEffect(() => {
    setChoice("");
    setChoices([]);
    setStudyTask(null);
    setConfidence(null);
    started.current = Date.now();
    questionHeading.current?.focus({ preventScroll: true });
    panel.current?.scrollTo({ top: 0 });
  }, [data?.question?.id, data?.status, setup]);
  useEffect(() => {
    const container = panel.current, heading = studyHeading.current;
    if (studyTask && container && heading) {
      heading.focus({ preventScroll: true });
      container.scrollTo({ top: container.scrollTop + heading.getBoundingClientRect().top - container.getBoundingClientRect().top - 76 });
    }
  }, [studyTask]);
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
          choice: status === "answered" && data.question.type !== "multiple" ? choice : null,
          choices: status === "answered" && data.question.type === "multiple" ? choices : [],
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
      const result = await apiPost<Assessment>(
          replan && data
            ? `/assessment/${data.id}/replan`
            : "/assessment/start",
          { survey, mode },
        );
      setData(result);
      setSetup(false);
      setReplan(false);
      if (!replan && onStarted) await onStarted(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
      throw e;
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
  const continueAssessment = async () => {
    if (!data || busy) return;
    setBusy(true); setError("");
    try { setData(await apiPost<Assessment>(`/assessment/${data.id}/extend`, { revision: data.revision })); }
    catch (e) { setError(e instanceof Error ? e.message : "暂时无法继续，请重试。"); }
    finally { setBusy(false); }
  };
  const report = data?.report;
  const plan = data?.plan;
  const allTasks = plan?.days.flatMap((day) => day.tasks) || [];
  const firstTask = allTasks.find(t => !t.done && t.requires.every(dep => allTasks.some(p => p.id === dep && p.done)));
  const studyMaterial = data?.materials.find(m => m.kp === studyTask?.kp);
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
          <p>{data?.course?.title || initialSurvey.course_title || "当前课程"} · 每一步，都有作答依据。</p>
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
      {data?.course && <details className="entry-course-context"><summary>这份计划依据哪些目标与资料？</summary><p>优先：{data.survey.goal}；每个学习日 {data.survey.daily_minutes} 分钟，每周 {data.survey.study_days.length} 天。</p><p>{data.course.coverage_note}</p>{data.course.sources?.map(source => <p key={source.id}>{source.title} · {source.location_kind} {source.locations.join("、")} · 已取样 {source.sampled_chunks}/{source.total_chunks} 个片段</p>)}{!data.course.sources?.length && <p>使用本课程入门内容；尚未绑定上传文件。</p>}<p>{data.course.boundary}</p></details>}
      {loading ? (
        <p className="entry-loading" role="status">
          正在读取你的学习起点…
        </p>
      ) : loadFailed ? null : !data || setup ? (
        <SurveyForm
          key={`${data?.id || "new"}-${replan}`}
          initial={data?.survey || { ...DEFAULT_SURVEY, ...initialSurvey, notebook_id: notebookId }}
          busy={busy}
          isReplan={replan}
          onSubmit={saveSurvey}
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
              {data.question.topic} · 第 {data.answered + 1} 题 · {data.question.type === "multiple" ? "多选题" : "单选题"}
            </p>
            <h2 tabIndex={-1} ref={questionHeading}>
              {data.question.stem}
            </h2>
            <fieldset className="entry-options" disabled={busy}>
              <legend>{data.question.type === "multiple" ? "选择所有正确选项（多选）" : "选择一个答案"}</legend>
              {data.question.options.map((option, index) => {
                const key = String.fromCharCode(65 + index);
                return (
                  <label
                    key={key}
                    className={(data.question?.type === "multiple" ? choices.includes(key) : choice === key) ? "is-selected" : ""}
                  >
                    <input
                      type={data.question?.type === "multiple" ? "checkbox" : "radio"}
                      name="entry-answer"
                      value={key}
                      checked={data.question?.type === "multiple" ? choices.includes(key) : choice === key}
                      onChange={() => data.question?.type === "multiple" ? setChoices(v => v.includes(key) ? v.filter(k => k !== key) : [...v, key].sort()) : setChoice(key)}
                    />
                    <b>{key}</b>
                    <span>{option}</span>
                    {(data.question?.type === "multiple" ? choices.includes(key) : choice === key) && <Check size={18} />}
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
                disabled={busy || (data.question.type === "multiple" ? !choices.length : !choice)}
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
                {data.mode === "screening" ? "这是起点抽样；其余知识点保留待测，可以接着补全。" : data.mode === "foundation"
                  ? "范围为入门基础，其他章节仍需测评。"
                  : "从薄弱环节开始，逐步用新题验证。"}
              </p>
            </div>
          </section>
          <p className="entry-note">{report.boundary}</p>
          {plan.practice_update && <p className="intake-response" role="status">{plan.practice_update}</p>}
          {firstTask && !studyTask && <section className="entry-first-step">
            <p className="entry-eyebrow">把下一步变得具体</p><h3>{firstTask.title}</h3>
            <p>{firstTask.reason}。这一步约 {firstTask.minutes} 分钟，先完成它就好。</p>
            <button className="intake-primary" onClick={() => setStudyTask(firstTask)}>开始第一项学习任务 <ArrowRight size={18} /></button>
          </section>}
          {studyTask && <section className="entry-study">
            <button className="secondary-action" onClick={() => setStudyTask(null)}><ArrowLeft size={15} /> 返回起点报告</button>
            <h2 ref={studyHeading} tabIndex={-1}>{studyTask.title}</h2><p className="entry-note">{studyTask.reason}</p>
            <ol>{(studyTask.steps || [studyTask.criterion]).map((s, i) => <li key={i}>{s}</li>)}</ol>
            <p className="entry-note">完成标准：{studyTask.criterion}</p>
            {studyMaterial ? <><p className="entry-eyebrow">对应学习资料 · 按作答与当前目标整理</p><Markdown text={studyMaterial.markdown} allowCodeBlocks /></> : <p className="intake-response">这一步先补充作答证据。小知会逐题等待你回答，再决定需要哪些讲解。</p>}
            <button className="intake-primary" onClick={() => onLearn(studyTask.goal)}><Play size={16} />请小知带我练习</button>
          </section>}
          {!!plan.adaptations?.length && <details className="entry-adaptations" open><summary>为什么这样安排 · 根据你的选择</summary><ul>{plan.adaptations.map((s, i) => <li key={i}>{s}</li>)}</ul></details>}
          {data.mode !== "comprehensive" && report.coverage < report.total_skills && <div className="entry-result-actions"><button className="intake-secondary" disabled={busy} onClick={() => void continueAssessment()}>继续补全课程摸底 <ArrowRight size={16} /></button><p className="entry-note">已做题目保留，继续检查尚未覆盖的知识点，可随时暂停。</p></div>}
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
                  {skill.after_intro && <small>该主题在引导中已有讲解，不作为未经教学的初始水平。</small>}
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
                              onClick={() => setStudyTask(task)}
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
