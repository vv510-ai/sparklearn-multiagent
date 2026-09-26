import { expect, test } from "@playwright/test";
import { openEnglish } from "./english-helpers";

test("真实模型：默认三个词、字幕来源、刷新恢复和现成课程入口", async ({ page }, info) => {
  test.setTimeout(480_000);
  expect(process.env.PLAYWRIGHT_REAL_MODE).toBe("1");
  expect(process.env.ACCEPTANCE_EXPECTED_COMMIT).toMatch(/^[a-f0-9]{40}$/);
  const health = await (await page.request.get("/api/health")).json();
  expect(health.status).toBe("ok");
  expect(health.demo_mode).toBe(false);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const notebookId = await openEnglish(page, "english-live");
  const start = Date.now();
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/learning/english/scene") && r.request().method() === "POST", { timeout: 170000 }),
    page.getByRole("button", { name: "生成场景笔记", exact: true }).click(),
  ]);
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(data.mode).toBe("live");
  expect(data.provenance).toBe("原创教学场景，非真实影视台词");
  expect(data.lines.length).toBeGreaterThanOrEqual(4);
  expect(data.lines.length).toBeLessThanOrEqual(8);
  for (const word of ["hesitate", "awkward", "figure out"]) {
    expect(data.vocabulary.map((item: { word: string }) => item.word.toLowerCase())).toContain(word);
  }
  expect(data.lines.every((line: { timestamp: string }) => line.timestamp === "")).toBe(true);
  await expect(page.getByRole("region", { name: "场景原句" })).toContainText(data.lines[0].text);
  if (!data.question) {
    await page.getByRole("button", { name: "只补生成练习", exact: true }).click();
    await expect(page.getByRole("group", { name: "英语练习选项" })).toBeVisible({ timeout: 170000 });
  }
  const restored = await (await page.request.get("/api/learning/english/scene/latest?notebook_id=" + notebookId)).json();
  expect(restored.resource_id).toBe(data.resource_id);
  expect(restored.question.options).toHaveLength(4);
  await page.getByRole("group", { name: "英语练习选项" }).getByRole("button").nth(restored.question.answer.charCodeAt(0) - 65).click();
  await page.getByRole("button", { name: "确认答案", exact: true }).click();
  await expect(page.getByText("回答正确 · 答案 " + restored.question.answer, { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /英语场景学习.*影视字幕/ }).click();
  await expect(page.getByText("已恢复本课程最近保存的场景。", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "场景原句" })).toContainText(data.lines[0].text);
  await page.getByRole("button", { name: "显示中文", exact: true }).click();
  await page.getByText("展开用法笔记", { exact: true }).click();
  for (const width of [1512, 390]) {
    await page.setViewportSize({ width, height: 950 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("heading", { name: data.title, exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath("english-live-" + width + ".png"), fullPage: true });
  }
  const originalLines = ["Don't hesitate to suggest a plan.", "It feels awkward to change plans at the last minute.", "Let's figure out a time that works for both of us."];
  const subtitles = originalLines.map((line, index) => String(index + 1) + "\n00:00:0" + (index * 2 + 1) + ",000 --> 00:00:0" + (index * 2 + 2) + ",900\n" + line).join("\n\n");
  const sourceResponse = await page.request.post("/api/learning/english/scene", { timeout: 170000, data: {
    words: "hesitate, awkward, figure out", scene: "朋友商量安排，严格使用给定原句", level: "中等", goal: "影视理解与日常交流", subtitles, notebook_id: notebookId,
  } });
  expect(sourceResponse.status()).toBe(200);
  const source = await sourceResponse.json();
  expect(source.provenance).toContain("用户字幕整理");
  expect(source.source_text).toBe(subtitles);
  expect(source.lines.every((line: { text: string; timestamp: string }) => originalLines.includes(line.text) && /^00:00:0[135],000$/.test(line.timestamp))).toBe(true);
  const latest = await (await page.request.get("/api/learning/english/scene/latest?notebook_id=" + notebookId)).json();
  expect(latest.resource_id).toBe(source.resource_id);
  await test.info().attach("english-live-content", { contentType: "application/json", body: JSON.stringify({ health, default_scene: restored, source_scene: source, elapsed_ms: Date.now() - start }) });
  await page.getByRole("link", { name: "进入场景课程", exact: true }).click();
  await expect(page.locator("#course-english-scenes")).toContainText("英语生活场景");
  expect(errors).toEqual([]);
});
