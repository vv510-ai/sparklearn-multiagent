import { expect, test, type Locator } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { registerLearner, currentAssessment } from "./intake-helpers";

async function playClip(audio: Locator) {
  await expect(audio).toBeVisible();
  await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.readyState)).toBeGreaterThanOrEqual(2);
  const duration = await audio.evaluate(async (element: HTMLAudioElement) => {
    element.muted = true; // Isolated automated run; don't play sounds on the user's desktop.
    element.playbackRate = 4;
    await element.play();
    return element.duration;
  });
  expect(duration).toBeGreaterThan(8);
  await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.ended), { timeout: 30_000 }).toBe(true);
  return duration;
}

test("六级选课、音频摸底、新题复测与实际输出沿用同一课程和资料", async ({ page }, info) => {
  test.setTimeout(600_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await registerLearner(page, "cet6-course");
  const guide = await page.request.get("/courses/cet6-guide-v1.html");
  expect(guide.status()).toBe(200);
  expect(await guide.text()).toContain('id="listening"');
  await page.getByRole("button", { name: "先进入，稍后继续", exact: true }).click();
  await page.getByRole("button", { name: "新建课程", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程", exact: true });
  await dialog.getByRole("radio", { name: "大学英语六级（CET-6）", exact: true }).check();
  await expect(dialog).toContainText("18 道起点题");
  await page.screenshot({ path: info.outputPath("cet6-picker.png"), fullPage: true });
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("checkbox", { name: /准备课程考试/ }).check();
  const priority = page.getByLabel("当前优先解决");
  if (await priority.isVisible()) await priority.selectOption("准备课程考试");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "大学英语六级（CET-6）", exact: true }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("checkbox", { name: /看文字能懂，听音频跟不上/ }).check();
  await page.getByRole("checkbox", { name: /有想法，英文写不出来/ }).check();
  await expect(page.getByRole("checkbox", { name: /思路懂，代码写不出/ })).toHaveCount(0);
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByLabel("每个学习日可用时间（分钟）").fill("30");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: /完成所选范围摸底/ }).check();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await expect(page.getByRole("region", { name: "本次学习范围" })).toContainText("不预测六级分数");
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  let state = await currentAssessment(page);
  const audioDurations: number[] = [];
  const baselineAnswers: Record<string, string> = { "cet6_listening-baseline-1": "A", "cet6_listening-baseline-2": "D", "cet6_listening-baseline-3": "C" };
  while (state.question) {
    expect(state.answered).toBeLessThan(18);
    if (state.question.audio_url) {
      expect(state.question.transcript).toBeUndefined();
      await page.reload();
      const card = page.locator(".entry-question-card");
      await expect(card).toContainText(state.question.stem);
      await card.locator(`input[value="${baselineAnswers[state.question.id]}"]`).check();
      await expect(card.getByRole("button", { name: "提交，继续下一题" })).toBeDisabled();
      audioDurations.push(await playClip(card.locator("audio")));
      const response = page.waitForResponse(r => r.url().includes(`/assessment/${state.id}/answers`));
      await card.getByRole("button", { name: "提交，继续下一题" }).click();
      state = await (await response).json();
    } else {
      const saved = await page.request.post(`/api/assessment/${state.id}/answers`, { data: {
        revision: state.revision, question_id: state.question.id, status: "dont_know",
      } });
      expect(saved.status(), await saved.text()).toBe(200);
      state = await saved.json();
    }
  }
  expect(state.report.coverage).toBe(6);
  expect(state.survey.barriers).toEqual(["listening", "expression"]);
  expect(state.survey.daily_minutes).toBe(30);
  expect(state.report.skills.find((s: { kp: string }) => s.kp === "cet6_listening").correct).toBe(3);
  await page.reload();
  await expect(page.getByRole("heading", { name: "起点测评记录", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^开始 听力信息提取/ }).first().click();
  await page.getByRole("button", { name: "开始无提示新题" }).click();
  const practice = page.getByRole("region", { name: "教材新题练习" });
  for (const key of ["B", "A", "D"]) {
    await expect(practice.getByText("选择程序输出")).toHaveCount(0);
    await expect(practice.getByText("查看听力文字稿，复听核对")).toHaveCount(0);
    await practice.locator(`input[name="textbook-answer"][value="${key}"]`).check();
    await expect(practice.getByRole("button", { name: "提交新题答案" })).toBeDisabled();
    audioDurations.push(await playClip(practice.locator("audio")));
    await practice.getByRole("button", { name: "提交新题答案" }).click();
    await expect(practice.getByRole("status")).toContainText("这道题答对了");
    await practice.getByText("查看听力文字稿，复听核对").click();
    if (key !== "D") await practice.getByRole("button", { name: "继续下一道新题" }).click();
  }
  await practice.getByRole("button", { name: "查看下次复测" }).click();
  await expect(practice).toContainText("本轮已完成");
  const updated = await currentAssessment(page);
  expect(updated.report).toEqual(state.report);
  expect(updated.learning_progress.cet6_listening.independent).toBe(3);
  expect(updated.learning_progress.cet6_listening.next_due_at).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await practice.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("cet6-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "返回起点报告", exact: true }).click();
  await page.getByRole("button", { name: /^开始 写作结构辨析/ }).first().click();
  const output = page.getByRole("region", { name: "六级实际输出训练" });
  const draft = "Universities should offer quiet rooms for collaborative learning. A student who shares a crowded home may need a suitable place for group work. However, booking rules are necessary to keep the rooms available to different groups.";
  await output.getByLabel("你的英文原稿").fill(draft);
  await page.reload();
  await page.getByRole("button", { name: /^开始 写作结构辨析/ }).first().click();
  await expect(output.getByLabel("你的英文原稿")).toHaveValue(draft);
  await output.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("cet6-writing.png"), fullPage: true });
  const chatResponse = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST", { timeout: 180_000 });
  await output.getByRole("button", { name: "提交给小知，逐句反馈" }).click();
  const response = await chatResponse;
  expect(response.status()).toBe(200);
  expect(JSON.stringify(response.request().postDataJSON())).toContain(draft);
  // Long browser SSE bodies can be evicted by Chromium. Verify the user's
  // persisted reply and visible content, rather than the network body's cache.
  let feedback = "";
  await expect.poll(async () => {
    const book = await (await page.request.get(`/api/notebooks/${state.notebook_id}?user_id=session_user`)).json();
    feedback = book.messages.filter((m: { role: string }) => m.role === "assistant").at(-1)?.content || "";
    return feedback.length;
  }, { timeout: 240_000, intervals: [1000, 2000, 5000] }).toBeGreaterThan(100);
  const afterFeedback = (await (await page.request.get(`/api/resources?user_id=session_user&notebook_id=${state.notebook_id}`)).json()).items;
  expect(afterFeedback.filter((r: { kind: string }) => r.kind === "quiz")).toHaveLength(0);
  await expect(page.locator('[aria-label="小知回答"]').last()).not.toContainText("学习内容已经准备好了");
  if (process.env.PLAYWRIGHT_REAL_MODE === "1") {
    expect(feedback).toMatch(/Universities|booking|collaborative/);
    expect(feedback).not.toMatch(/资料不足|离线示例|演示数据/);
  }
  await writeFile(info.outputPath("cet6-chat.json"), JSON.stringify({ feedback }, null, 2));
  await writeFile(info.outputPath("cet6-verification.json"), JSON.stringify({ course: state.course, report: state.report, plan: updated.plan, learning: updated.learning_progress, audioDurations }, null, 2));

  if (process.env.PLAYWRIGHT_REAL_MODE === "1") {
    const generated = await page.request.post("/api/resources/generate", { timeout: 180_000, data: {
      user_id: "session_user", notebook_id: state.notebook_id, kinds: ["doc"], knowledge_points: ["cet6_reading"],
      prompt_template: "complete_notes", source_ids: [], topic_label: "仔细阅读与推断",
      goal: "请根据小知六级指南解释阅读中为什么不能把相关当因果，给一个英文短例子和中文分步说明。",
    } });
    expect(generated.status()).toBe(200);
    const result = (await generated.text()).split("\n").filter(l => l.startsWith("data: ")).map(l => JSON.parse(l.slice(6)));
    expect(result.filter(e => e.type === "error")).toEqual([]);
    const resources = (await (await page.request.get(`/api/resources?user_id=session_user&notebook_id=${state.notebook_id}`)).json()).items;
    const resource = resources.find((r: { payload: { learning_context?: unknown; goal?: string } }) => r.payload.learning_context && r.payload.goal?.includes("相关")) || resources.find((r: { payload: { learning_context?: unknown } }) => r.payload.learning_context);
    await writeFile(info.outputPath("cet6-real-generation.json"), JSON.stringify(resource, null, 2));
    expect(resource.payload.generation_mode).toBe("model");
    expect(resource.payload.learning_context.course).toContain("大学英语六级");
    expect(resource.payload.learning_context.daily_minutes).toBe(30);
    expect(resource.payload.source_evidence.length).toBeGreaterThan(0);
    expect(resource.citations.some((c: string) => c.includes("cet6-guide-v1"))).toBe(true);
    expect(resource.payload.markdown).not.toMatch(/演示数据|离线示例|资料不足/);
  }
});
