import { expect, test, type Page } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { registerLearner } from "./intake-helpers";

async function preparePython(page: Page, strong = false) {
  const created = await page.request.post("/api/notebooks", { data: { user_id: "session_user", title: "Python 教材试点" } });
  expect(created.status()).toBe(201);
  const book = await created.json();
  const survey = { notebook_id: book.id, course_key: "python", course_title: "Python 入门", daily_minutes: 20,
    study_days: [1, 2, 3, 4, 5, 6, 7], goal: "从零系统学习", goals: ["从零系统学习"] };
  const response = await page.request.post(`/api/notebooks/${book.id}/learning/prepare`, { data: { title: "Python 入门", course_key: "python", survey } });
  expect(response.status(), await response.text()).toBe(200);
  const course = await response.json();
  expect(course.textbook.sections).toHaveLength(10);
  let state = await (await page.request.post("/api/assessment/start", { data: { mode: "comprehensive", survey: { ...survey, course_revision: course.revision } } })).json();
  const answers: Record<string, string | string[]> = {
    "py_values-1": "A", "py_values-2": "B", "py_values-3": ["A", "C", "D"],
    "py_branches-1": "A", "py_branches-2": "C", "py_branches-3": ["A", "C"],
    "py_loops-1": "B", "py_loops-2": "C", "py_loops-3": ["A", "B", "D"],
    "py_functions-1": "B", "py_functions-2": "C", "py_functions-3": ["A", "B", "D"],
  };
  let count = 0;
  while (state.question) {
    expect(count++).toBeLessThan(16);
    const answer = answers[state.question.id];
    const saved = await page.request.post(`/api/assessment/${state.id}/answers`, { data: {
      revision: state.revision, question_id: state.question.id, status: strong ? "answered" : "dont_know",
      choice: strong && typeof answer === "string" ? answer : null, choices: strong && Array.isArray(answer) ? answer : [],
    } });
    expect(saved.status(), await saved.text()).toBe(200);
    state = await saved.json();
  }
  return { book, course, state };
}

test("Python 教材、个性化计划、新题与延迟复测在同一学习流程内", async ({ page }, testInfo) => {
  test.setTimeout(360_000);
  await registerLearner(page, "textbook-pilot");
  const weak = await preparePython(page);
  expect(weak.state.plan.days.flatMap((d: { tasks: { kind: string }[] }) => d.tasks).some((t: { kind: string }) => t.kind === "study")).toBe(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: /你的学习起点，已经清楚了一些|先学一步，再逐步了解你/ })).toBeVisible();
  await page.locator(".entry-reference-details > summary").click();
  await expect(page.getByRole("region", { name: "教材依据与范围" })).toContainText("Python 官方教程");
  await page.getByRole("button", { name: "开始第一项学习任务" }).click();
  await expect(page.locator(".textbook-readings")).toContainText("数字");
  await page.getByRole("button", { name: "开始无提示新题" }).click();
  for (const option of ["28", "17", "4 3"]) {
    const card = page.getByRole("region", { name: "教材新题练习" });
    await card.getByRole("radio", { name: new RegExp(`^[A-D]\\s*${option.replace(/ /g, "\\s*")}$`) }).check();
    const response = page.waitForResponse(r => r.url().includes("/practice/answers"));
    await page.getByRole("button", { name: "提交新题答案" }).click();
    const saved = await response;
    expect(saved.status()).toBe(200);
    await expect(card.getByRole("status")).toContainText("这道题答对了");
    if (option !== "4 3") await page.getByRole("button", { name: "继续下一道新题" }).click();
  }
  await page.getByRole("button", { name: "查看下次复测" }).click();
  await expect(page.getByRole("region", { name: "教材新题练习" })).toContainText("本轮已完成");
  const updated = await (await page.request.get(`/api/assessment?notebook_id=${weak.book.id}`)).json();
  expect(updated.assessment.learning_progress.py_values.independent).toBe(3);
  expect(updated.assessment.report).toEqual(weak.state.report);
  expect(updated.assessment.plan.practice_update).toContain("变量与表达式");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("region", { name: "教材新题练习" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("textbook-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await page.locator(".entry-report-details > summary").click();
  await expect(page.getByRole("region", { name: "新题与复测记录" })).toContainText("独立答对 3/3 道新题");
  await page.getByRole("region", { name: "新题与复测记录" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("textbook-desktop.png"), fullPage: true });
  const strong = await preparePython(page, true);
  expect(strong.state.plan.days.flatMap((d: { tasks: { kind: string }[] }) => d.tasks).every((t: { kind: string }) => t.kind === "transfer" || t.kind === "review")).toBe(true);
  await writeFile(testInfo.outputPath("textbook-verification.json"), JSON.stringify({ textbook: weak.course.textbook, weakPlan: weak.state.plan, updatedPlan: updated.assessment.plan,
    newEvidence: updated.assessment.learning_progress, strongPlan: strong.state.plan }, null, 2));
  if (process.env.PLAYWRIGHT_REAL_MODE === "1") {
    const health = await (await page.request.get("/api/health")).json();
    expect(health.demo_mode).toBe(false);
    const generated = await page.request.post("/api/resources/generate", { timeout: 180_000, data: {
      user_id: "session_user", notebook_id: weak.book.id, kinds: ["doc"], knowledge_points: ["py_functions"],
      prompt_template: "complete_notes", source_ids: [], topic_label: "函数与返回值",
      goal: "根据 Python 官方教程，分步骤解释函数没有 return 时返回什么，并区分 print 和 return。",
    } });
    expect(generated.status()).toBe(200);
    const events = (await generated.text()).split("\n").filter(line => line.startsWith("data: ")).map(line => JSON.parse(line.slice(6)));
    expect(events.filter(e => e.type === "error")).toEqual([]);
    const resources = await (await page.request.get(`/api/resources?user_id=session_user&notebook_id=${weak.book.id}`)).json();
    const resource = resources.items.find((r: { payload: { learning_context?: unknown } }) => r.payload.learning_context);
    expect(resource).toBeTruthy();
    await writeFile(testInfo.outputPath("textbook-real-generation.json"), JSON.stringify({ health, resource }, null, 2));
    expect(resource.payload.generation_mode).toBe("model");
    expect(resource.payload.learning_context.goal).toBe("从零系统学习");
    expect(resource.payload.learning_context.daily_minutes).toBe(20);
    expect(resource.payload.learning_context.textbook.version).toBe(weak.course.textbook.version);
    expect(resource.citations.some((c: string) => c.includes("docs.python.org"))).toBe(true);
    const source = JSON.parse(await readFile(path.resolve(__dirname, "../../backend/app/data/textbooks/python_tutorial.json"), "utf8"));
    const evidence = resource.payload.source_evidence;
    expect(evidence.length).toBeGreaterThan(0);
    for (const citation of evidence) {
      const section = source.sections.find((s: { id: string }) => s.id === citation.section_id);
      expect(section).toBeTruthy();
      expect(citation.url).toBe(section.url);
      expect(citation.version).toBe(source.version);
      expect(section.text.replace(/\s+/g, "")).toContain(citation.preview.replace(/…$/, "").replace(/\s+/g, ""));
    }
    expect(resource.payload.markdown).toContain("None");
    expect(resource.payload.markdown).toContain("print");
    expect(resource.payload.markdown).toContain("return");
    expect(resource.payload.markdown).not.toMatch(/演示数据|离线示例|资料不足/);
  }
});
