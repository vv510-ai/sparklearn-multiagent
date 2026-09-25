"use client";

import { useEffect, useRef, useState } from "react";
import AuthGate, { type AuthUser } from "@/components/auth/AuthGate";
import EnglishSceneLesson, { type EnglishScene } from "@/components/learning/EnglishSceneLesson";
import Markdown from "@/components/chat/Markdown";
import { apiGet, apiPost, UNAUTHORIZED_EVENT } from "@/lib/api";
import "./library.css";

type Outline = { id: string; title: string; objective: string };
type Attempt = { question_id: string; correct: boolean; independent: boolean; assisted: boolean; answer_text?: string; explanation?: string };
type Progress = { listening?: { status: string }; read?: boolean; attempts?: Attempt[]; next_due_at?: string | null; work?: { assisted?: boolean; text: string; self_checked: number[]; notice: string } };
type Study = { kind?: string; id: string; notebook_id: string; release_id: string; revision: number; title?: string; withdrawn: boolean; notice?: string; outline?: Outline[]; review?: { note: string }; progress: { last_lesson: string; lessons: Record<string, Progress> } };
type Catalog = { items: { course_id: string; release_id: string; title: string; description: string; audience: string; prerequisites: string; scope: string; not_covered: string; status_label: string; review: { note: string }; outline: Outline[]; source: { kind?: string; title: string; version: string; section_count: number; license: string } }[]; studies: { id: string; release_id: string; notebook_id: string; last_lesson: string; withdrawn: boolean }[]; other_courses: { title: string; scope: string }[] };
type Lesson = { scene?: EnglishScene; work_reference?: string; id: string; title: string; objective: string; markdown: string; example: { code: string; output: string }; task: string; criteria: string[]; authoring: string; revision: number; release_id: string; progress: Progress; question: { id: string; stem: string; code: string; options: string[] } | null; practice_status: string; sources: { id: string; title: string; text: string; url: string; version: string }[]; license: string; license_notice: string };

const readableError = (e: unknown) => e instanceof Error ? e.message.replace(/^(GET|POST) \S+ → \d+:\s*/, "") : "暂时无法完成，请重试。";

export default function CourseLibrary() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [study, setStudy] = useState<Study | null>(null);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [choice, setChoice] = useState<number | null>(null);
  const [assisted, setAssisted] = useState(false);
  const [workAssisted, setWorkAssisted] = useState(false);
  const [work, setWork] = useState("");
  const [checks, setChecks] = useState<number[]>([]);
  const [issue, setIssue] = useState("");
  const epoch = useRef(0);
  const drafts = useRef<Record<string, { text: string; checks: number[]; assisted: boolean }>>({});
  const draftKey = study && lesson ? `${study.id}:${lesson.id}` : "";
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    let active = true;
    void apiGet<AuthUser>("/auth/me").then(u => { if (active) setUser(u); }).catch(() => {}).finally(() => { if (active) setAuthReady(true); });
    const expired = () => { epoch.current++; setUser(null); setStudy(null); setLesson(null); setCatalog(null); drafts.current = {}; };
    window.addEventListener(UNAUTHORIZED_EVENT, expired);
    return () => { active = false; epoch.current++; window.removeEventListener(UNAUTHORIZED_EVENT, expired); };
  }, []);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (Object.keys(drafts.current).length) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  const openLesson = async (current: Study, id: string, focus = true) => {
    const ticket = ++epoch.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await apiGet<Lesson>(`/library/studies/${current.id}/lessons/${id}`);
      if (ticket !== epoch.current) return;
      setStudy(current); setLesson(data); setChoice(null); setAssisted(false);
      const draft = drafts.current[`${current.id}:${id}`];
      setWork(draft?.text ?? data.progress.work?.text ?? ""); setChecks(draft?.checks ?? data.progress.work?.self_checked ?? []);
      setWorkAssisted(draft?.assisted ?? data.progress.work?.assisted ?? false);
      setIssue("");
      window.history.replaceState(null, "", `/library?study=${encodeURIComponent(current.id)}&lesson=${encodeURIComponent(id)}`);
      if (focus) requestAnimationFrame(() => { heading.current?.focus(); heading.current?.scrollIntoView({ block: "start" }); });
    } catch (e) {
      if (ticket === epoch.current) { setLesson(null); setError(readableError(e)); }
    } finally { if (ticket === epoch.current) setBusy(false); }
  };

  useEffect(() => {
    if (!user) return;
    const ticket = ++epoch.current;
    setBusy(true);
    void apiGet<Catalog>("/library").then(async data => {
      if (ticket !== epoch.current) return;
      setCatalog(data); setError("");
      const query = new URLSearchParams(window.location.search);
      const requested = query.get("study");
      if (requested) {
        const current = await apiGet<Study>(`/library/studies/${encodeURIComponent(requested)}`);
        if (ticket !== epoch.current) return;
        setStudy(current);
        if (!current.withdrawn) await openLesson(current, query.get("lesson") || current.progress.last_lesson, false);
      }
    }).catch(e => { if (ticket === epoch.current) setError(readableError(e)); }).finally(() => { if (ticket === epoch.current) setBusy(false); });
    return () => { epoch.current++; };
  }, [user]);

  const start = async (release: string, existing?: string) => {
    const ticket = ++epoch.current;
    setBusy(true); setError("");
    try {
      const current = existing ? await apiGet<Study>(`/library/studies/${existing}`) : await apiPost<Study>("/library/enroll", { release_id: release });
      if (!user || ticket !== epoch.current) return;
      try { localStorage.setItem(`learnloop:last-notebook:${user.id}`, current.notebook_id); } catch { /* Server progress remains authoritative. */ }
      setStudy(current);
      if (!current.withdrawn) await openLesson(current, current.progress.last_lesson);
    } catch (e) { if (ticket === epoch.current) setError(readableError(e)); } finally { if (ticket === epoch.current) setBusy(false); }
  };

  const save = async (action: "read" | "answer" | "work" | "listen" | "reveal_work") => {
    if (!study || !lesson) return;
    const ticket = epoch.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const current = await apiPost<Study>(`/library/studies/${study.id}/lessons/${lesson.id}`, {
        action, revision: lesson.revision, audio_sha256: action === "listen" ? lesson.scene?.audio.sha256 : undefined, question_id: lesson.question?.id, choice, assisted: action === "work" ? workAssisted : assisted,
        work: action === "work" ? work : "", self_checked: checks,
      });
      if (ticket !== epoch.current) return;
      const fresh = await apiGet<Lesson>(`/library/studies/${current.id}/lessons/${lesson.id}`);
      if (ticket !== epoch.current) return;
      setStudy(current); setLesson(fresh); setChoice(null); setAssisted(false);
      if (action === "reveal_work") setWorkAssisted(true);
      if (action === "work") { delete drafts.current[draftKey]; setWorkAssisted(!!fresh.progress.work?.assisted); }
      setNotice(action === "listen" ? "完整播放记录已保存，不计入能力分数。" : action === "reveal_work" ? "已展开参考示例，后续修改会标为参考后作答。" : action === "answer" ? "作答已保存，请查看下方反馈。" : action === "work" ? (lesson.scene ? "英语回应与自查记录已保存。" : "代码与自查记录已保存，可登录后继续修改。") : "阅读记录已保存，可以继续练习或进入下一课。");
    } catch (e) {
      if (ticket !== epoch.current) return;
      setError(readableError(e));
      // Keep unsaved code on a stale-version error; the refresh control is explicit.
    } finally { if (ticket === epoch.current) setBusy(false); }
  };

  const back = () => {
    const ticket = ++epoch.current; setStudy(null); setLesson(null); setError(""); setNotice(""); setBusy(false);
    window.history.replaceState(null, "", "/library");
    void apiGet<Catalog>("/library").then(data => { if (ticket === epoch.current) setCatalog(data); }).catch(e => { if (ticket === epoch.current) setError(readableError(e)); });
  };

  if (!authReady) return <main id="main" className="course-library"><p role="status">正在打开课程…</p></main>;
  if (!user) return <AuthGate onAuthenticated={setUser} />;
  const outline = study?.outline || [];
  const at = outline.findIndex(x => x.id === lesson?.id);
  const next = outline[at + 1];
  const progressCount = Object.values(study?.progress.lessons || {}).filter(p => p.read).length;

  return <main id="main" className="course-library" aria-busy={busy}>
    <header className="library-header"><a href="/">知行循证 <span>LearnLoop</span></a><nav aria-label="课程导航"><a href="/">学习工作区</a><button onClick={back} disabled={busy}>课程目录</button><span>{user.name}</span></nav></header>
    {error && <div className="library-error" role="alert">{error}{study && !study.withdrawn && <button onClick={() => void openLesson(study, lesson?.id || study.progress.last_lesson, false)} disabled={busy}>刷新本课</button>}</div>}
    {notice && <p className="library-notice" role="status">{notice}</p>}
    {busy && <p role="status" className="library-loading">正在保存或载入，请稍候…</p>}
    {!study ? <>
      <section className="library-intro"><p className="library-eyebrow">教材、讲解与练习已经准备好</p><h1>选一门课，直接开始学。</h1><p>不需要先上传资料。按课程目录阅读、动手和练习，学习进度会保存在你的账号中。</p></section>
      {!catalog && !busy && <button onClick={() => void apiGet<Catalog>("/library").then(setCatalog).catch(e => setError(readableError(e)))}>重新加载课程</button>}
      {catalog?.items.length === 0 && <p role="status">课程正在维护，已有学习记录仍然保留。请稍后重试。</p>}
      <div className="library-cards">{catalog?.items.map(course => {
        const existing = catalog.studies.find(x => x.release_id === course.release_id);
        return <article className="library-course-card" key={course.release_id}>
          <p className="library-eyebrow">{course.status_label}</p><h2>{course.title}</h2><p>{course.description}</p>
          <p><strong>适合谁：</strong>{course.audience}</p><p><strong>开始前：</strong>{course.prerequisites}</p>
          <ol>{course.outline.map(l => <li key={l.id}>{l.title}</li>)}</ol>
          <details><summary>教材来源、范围与版本</summary><p>{course.source.title} {course.source.version}，内置 {course.source.section_count} 个{course.source.kind === "platform_original" ? "原创导学小节。" : "原文小节，配合本站原创导学。"}</p><p>本课范围：{course.scope}</p><p>未覆盖：{course.not_covered}</p><p>{course.review.note}</p><p>来源许可：{course.source.license}</p><small>课程版本：{course.release_id}</small></details>
          <button className="library-primary" disabled={busy} onClick={() => void start(course.release_id, existing?.id)}>{existing ? "继续学习" : "开始第一课"}</button>
          <small>无需上传 · 起点测评不阻断学习</small>
        </article>;
      })}</div>
      {!!catalog?.studies.some(s => !catalog.items.some(c => c.release_id === s.release_id)) && <section className="library-other"><h2>以前开始的课程</h2>{catalog.studies.filter(s => !catalog.items.some(c => c.release_id === s.release_id)).map(s => <p key={s.id}><button disabled={busy} onClick={() => void start(s.release_id, s.id)}>{s.withdrawn ? "查看已停止提供课程的记录" : "继续旧版本课程"}</button></p>)}</section>}
      <section className="library-other"><h2>其他课程目前可以学什么</h2>{catalog?.other_courses.map(c => <p key={c.title}><strong>{c.title}</strong>：{c.scope}</p>)}<a href="/">进入工作区，选择入门训练或自己的资料 →</a></section>
    </> : study.withdrawn ? <section className="library-course-card"><h1>学习记录仍在</h1><p>{study.notice}</p><p>已记录 {Object.keys(study.progress.lessons).length} 课的学习活动。</p>{Object.entries(study.progress.lessons).map(([id, p]) => <p key={id}>{id}：已提交 {p.attempts?.length || 0} 次新题作答{p.work ? "，提交内容已保留" : ""}</p>)}<button onClick={back}>查看其他可学课程</button></section> : <>
      <section className="library-course-heading"><div><p className="library-eyebrow">{study.title}</p><p>已阅读 {progressCount}/{outline.length} 课 · 阅读、作答和任务提交分别记录</p></div><a href="/" onClick={() => { try { localStorage.setItem(`learnloop:last-notebook:${user.id}`, study.notebook_id); } catch {} }}>带着本课教材问小知 →</a></section>
      <label className="library-mobile-nav">课程目录<select aria-label="课程目录" value={lesson?.id || study.progress.last_lesson} disabled={busy} onChange={e => void openLesson(study, e.target.value)}>{outline.map((l, i) => <option key={l.id} value={l.id}>{i + 1}. {l.title}</option>)}</select></label>
      <div className="library-study-layout"><aside aria-label="章节目录">{outline.map((l, i) => <button key={l.id} disabled={busy} aria-current={lesson?.id === l.id ? "step" : undefined} onClick={() => void openLesson(study, l.id)}><span>{String(i + 1).padStart(2, "0")}</span>{l.title}{study.progress.lessons[l.id]?.read && <small>已读</small>}</button>)}</aside>
      {lesson && <article className="library-lesson" key={`${study.id}:${lesson.id}`}>
        <p className="library-eyebrow">第 {at + 1} 课 / {outline.length}</p><h1 ref={heading} tabIndex={-1}>{lesson.title}</h1><p className="library-objective">这课练习：{lesson.objective}</p>
        {lesson.scene && <EnglishSceneLesson scene={lesson.scene} busy={busy} recorded={!!lesson.progress.listening} onRecord={() => void save("listen")} />}
        {lesson.scene ? <details><summary>展开本课讲解</summary><Markdown text={lesson.markdown} /></details> : <Markdown text={lesson.markdown} />}
        {!lesson.scene && <section className="library-example"><h2>运行一个例子</h2><pre><code>{lesson.example.code}</code></pre><details><summary>核对示例输出</summary><pre>{lesson.example.output}</pre></details></section>}
        <details className="library-sources"><summary>{lesson.scene ? "查看原创来源与用法参考" : "查看本课依据：Python 官方教程"}</summary><p>{lesson.scene ? "以下是本站原创对话与导学；用法参考链接不代表机构审定或课程背书。" : "下面是固定版本的官方原文；上方导学和题目由本站编写。"}</p>{lesson.scene?.references.map(ref => <p key={ref.url}><a href={ref.url} target="_blank" rel="noreferrer">{ref.title} ↗</a></p>)}{lesson.sources.map(source => <details key={source.id}><summary>{source.title} · {source.version}</summary><a href={source.url} target="_blank" rel="noreferrer">{lesson.scene ? "打开原创导学全文 ↗" : "打开官方出处 ↗"}</a><Markdown text={source.text} /></details>)}<details><summary>许可声明</summary><p>{lesson.license}</p><pre>{lesson.license_notice}</pre></details></details>
        <button disabled={busy} onClick={() => void save("read")}>{lesson.progress.read ? "已记录阅读，再次确认" : "我已阅读，记录进度"}</button>

        <section className="library-practice" aria-label="本课新题练习"><h2>合上讲解，试一道新题</h2><p>先自己判断；看过提示或参考答案，请如实勾选。</p>
          {lesson.question ? <form onSubmit={e => { e.preventDefault(); void save("answer"); }}>
            <p>{lesson.question.stem}</p>{lesson.question.code && <pre><code>{lesson.question.code}</code></pre>}
            <fieldset disabled={busy}><legend>{lesson.scene ? "选择合适的回应或理解" : "选择程序输出"}</legend>{lesson.question.options.map((o, i) => <label className="library-option" key={i}><input type="radio" name="course-answer" checked={choice === i} onChange={() => setChoice(i)} /><span>{String.fromCharCode(65 + i)}. <code>{o}</code></span></label>)}</fieldset>
            <label className="library-check"><input type="checkbox" checked={assisted} onChange={e => setAssisted(e.target.checked)} />我查看了提示或参考了答案</label>
            <button className="library-primary" type="submit" disabled={busy || choice === null}>提交新题答案</button>
          </form> : <p>{lesson.practice_status === "scheduled" ? `已安排隔日新题：${new Date(lesson.progress.next_due_at!).toLocaleString("zh-CN")}。你可以先完成动手任务或继续下一课。` : "本节两道新题已完成。可以回看错误与动手任务；重复原题不会增加独立作答记录。"}</p>}
          {lesson.progress.attempts?.map((attempt, i) => <div key={attempt.question_id} className="library-feedback" role="status"><strong>第 {i + 1} 次：{attempt.correct ? "这道题答对了" : "这道题还需要复习"} · {attempt.independent ? "自述独立作答" : "参考后作答"}</strong><p>{lesson.scene ? "参考答案：" : "正确输出："}<code>{attempt.answer_text}</code></p><p>{attempt.explanation}</p></div>)}
        </section>

        <section className="library-work"><h2>自己动手完成一个任务</h2><p>{lesson.task}</p><label>{lesson.scene ? "写下你的英语回应" : "记录你的代码、运行结果和解释"}<textarea value={work} disabled={busy} maxLength={8000} rows={9} onChange={e => { setWork(e.target.value); drafts.current[draftKey] = { text: e.target.value, checks, assisted: workAssisted }; }} placeholder={lesson.scene ? "先试着自己表达，再对照检查项修改。保存后可查看参考示例。" : "在自己的 Python 环境运行后，把代码和结果记在这里。"} /></label>
          <fieldset disabled={busy}><legend>对照任务自查</legend>{lesson.criteria.map((c, i) => <label className="library-check" key={c}><input type="checkbox" checked={checks.includes(i)} onChange={e => { const updated = e.target.checked ? [...checks, i] : checks.filter(x => x !== i); setChecks(updated); drafts.current[draftKey] = { text: work, checks: updated, assisted: workAssisted }; }} />{c}</label>)}</fieldset>
          <button disabled={busy || !work.trim()} onClick={() => void save("work")}>{lesson.scene ? "保存英语回应与自查" : "保存代码与自查记录"}</button><p className="library-small">{lesson.progress.work?.notice || (lesson.scene ? "先保存自己的表达；这里不做口语评分，也不会仅凭提交判定掌握。" : "这里保存你的实现与自查，服务器不会执行所提交的代码；提交不等于已经通过代码评测。")}</p>
          {lesson.scene && <><label className="library-check"><input type="checkbox" checked={workAssisted} onChange={e => { setWorkAssisted(e.target.checked); drafts.current[draftKey] = { text: work, checks, assisted: e.target.checked }; }} />这次表达参考了提示或他人帮助</label>{lesson.work_reference ? <div className="library-feedback"><h3>参考回应（示例，不是唯一答案）</h3><p lang="en">{lesson.work_reference}</p><p>对照任务要求找出一个可以改进的地方，再修改自己的回应。</p></div> : <button disabled={busy || !lesson.progress.work?.text || !!drafts.current[draftKey]} onClick={() => void save("reveal_work")}>保存后查看参考回应</button>}</>}
        </section>
        <footer className="library-lesson-footer"><p className="library-small">{lesson.authoring}</p><button className="library-primary" disabled={busy} onClick={() => next ? void openLesson(study, next.id) : back()}>{next ? `下一课：${next.title} →` : "返回目录，查看复习安排"}</button></footer>
        <details className="library-report"><summary>发现内容问题？告诉我们</summary><label>问题描述<textarea value={issue} maxLength={2000} rows={3} onChange={e => setIssue(e.target.value)} /></label><button disabled={busy || issue.trim().length < 3} onClick={async () => {
          const ticket = epoch.current; setBusy(true); setError("");
          try { await apiPost(`/library/studies/${study.id}/lessons/${lesson.id}/issues`, { description: issue }); if (ticket !== epoch.current) return; setNotice("问题已记录，并附上本课版本与章节。"); setIssue(""); }
          catch (e) { if (ticket === epoch.current) setError(readableError(e)); } finally { if (ticket === epoch.current) setBusy(false); }
        }}>提交问题</button></details>
      </article>}
      </div>
    </>}
  </main>;
}
