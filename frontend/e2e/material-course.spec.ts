import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { registerLearner, currentAssessment } from "./intake-helpers";

const NOTES = `生态系统中的生产者、消费者与分解者
绿色植物可以通过光合作用把太阳能转化为储存在有机物中的化学能。消费者通过摄食其他生物获得有机物和能量。分解者通过分解生物遗体、排泄物等，把有机物转化为无机物，使物质回到环境中。
食物链与能量流动
在“草→兔→狐”中，箭头表示从被吃者到捕食者的能量传递方向。草是生产者，兔和狐是消费者。分解者通常不作为这条捕食食物链的一个环节。能量沿食物链单向流动，逐级递减，部分能量以热的形式散失，不能被生产者循环利用。不要把能量流动与物质循环混同。
物质循环
碳等元素可以在生物与无机环境之间反复循环。生产者通过光合作用固定二氧化碳，生物呼吸与分解者分解会把碳以二氧化碳等形式释放回环境。能量单向流动，物质可循环利用。
判读示例
池塘里的藻类可作为生产者，吃藻类的小型动物是消费者，分解枯枝落叶的真菌是分解者。不能仅凭体型大小判断营养角色，要根据获得有机物和能量的方式。`;

test("真实资料经模型生成起点题，目标与来源继续进入学习资料", async ({ page }, testInfo) => {
  test.skip(process.env.PLAYWRIGHT_REAL_MODE !== "1", "显式启用真实模型后执行，会调用配置的模型服务");
  test.setTimeout(420_000);
  const health = await (await page.request.get("/api/health")).json();
  expect(health.demo_mode).toBe(false);
  await registerLearner(page, "material-course");
  await page.getByRole("checkbox", { name: /看懂手头的课件或教材/ }).check();
  await page.getByRole("checkbox", { name: /制定计划，安排复习/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "其他课程或主题", exact: true }).check();
  await page.getByLabel("课程或学习主题", { exact: true }).fill("生态学入门");
  await page.locator('.intake-upload input[type="file"]').setInputFiles({ name: "生态学入门验收资料.txt", mimeType: "text/plain", buffer: Buffer.from(NOTES) });
  await expect(page.getByText("解析完成，已选中的资料将用于准备课程范围与起点题。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("checkbox", { name: /符号与步骤讲细些/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByLabel("每个学习日可用时间（分钟）").fill("15");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: /完成所选范围摸底/ }).check();
  const preparedResponse = page.waitForResponse(r => r.url().includes("/learning/prepare") && r.request().method() === "POST", { timeout: 130_000 });
  await page.getByRole("button", { name: "生成并核对学习范围" }).click();
  const prepared = await preparedResponse;
  expect(prepared.status(), await prepared.text()).toBe(200);
  const course = await prepared.json();
  expect(course.sources).toHaveLength(1);
  expect(course.sources[0].sha256).toHaveLength(64);
  expect(course.outline.length).toBeGreaterThanOrEqual(3);
  await expect(page.getByRole("region", { name: "本次学习范围" })).toContainText("生态学入门验收资料.txt");
  await page.screenshot({ path: testInfo.outputPath("material-outline.png"), fullPage: true });
  await page.getByRole("button", { name: "确认范围，开始独立作答" }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  let state = await currentAssessment(page);
  const shown = [];
  while (state.status === "active") {
    expect(shown.length).toBeLessThan(18);
    shown.push(state.question);
    await expect(page.locator(".entry-question-card h2")).toHaveText(state.question.stem);
    const saved = page.waitForResponse(r => r.url().includes(`/assessment/${state.id}/answers`));
    if (state.question.type === "multiple") {
      const options = page.locator('.entry-options input[type="checkbox"]');
      await options.nth(0).check();
      await options.nth(1).check();
      await page.getByRole("button", { name: "提交，继续下一题" }).click();
    } else {
      await page.getByRole("button", { name: "这题还不会", exact: true }).click();
    }
    const response = await saved;
    expect(response.status()).toBe(200);
    state = await response.json();
  }
  expect(shown.some(q => q.type === "multiple")).toBe(true);
  expect(state.course.title).toBe("生态学入门");
  expect(state.materials.length).toBeGreaterThan(0);
  expect(state.materials.every((m: { markdown: string }) => m.markdown.includes("生态学入门验收资料.txt"))).toBe(true);
  expect(state.plan.days.every((d: { minutes: number; capacity: number }) => d.minutes <= d.capacity)).toBe(true);
  await page.getByRole("button", { name: "开始第一项学习任务" }).click();
  await expect(page.locator(".entry-study")).toContainText("生态学入门验收资料.txt");
  await page.screenshot({ path: testInfo.outputPath("material-first-task.png"), fullPage: true });
  await page.reload();
  await expect(page.getByRole("heading", { name: "你的学习起点，已经清楚了一些" })).toBeVisible();
  const generated = await page.request.post("/api/resources/generate", { timeout: 180_000, data: {
    user_id: "session_user", notebook_id: state.notebook_id, kinds: ["doc"], prompt_template: "complete_notes",
    goal: "根据已选资料，分步骤讲解生态系统的能量流动与物质循环，并留下一个独立思考问题。",
    topic_label: "生态学入门", source_ids: course.source_ids,
  } });
  expect(generated.status()).toBe(200);
  const events = (await generated.text()).split("\n").filter(line => line.startsWith("data: ")).map(line => JSON.parse(line.slice(6)));
  expect(events.filter(e => e.type === "error")).toEqual([]);
  const resources = await (await page.request.get(`/api/resources?user_id=session_user&notebook_id=${state.notebook_id}`)).json();
  const followup = resources.items.find((r: { payload: { learning_context?: unknown } }) => r.payload.learning_context);
  expect(followup).toBeTruthy();
  expect(followup.payload.learning_context.goal).toBe("看懂学习资料");
  expect(followup.payload.learning_context.daily_minutes).toBe(15);
  expect(followup.payload.learning_context.goals).toContain("安排计划与复习");
  expect(followup.payload.learning_context.bound_sources[0].title).toBe("生态学入门验收资料.txt");
  expect(followup.payload.generation_scope.source_ids).toEqual(course.source_ids);
  expect(followup.citations.some((c: { source: string; preview: string }) => c.source === "生态学入门验收资料.txt" && NOTES.replace(/\s+/g, "").includes(c.preview.replace(/…$/, "").replace(/\s+/g, "")))).toBe(true);
  expect(followup.payload.markdown).toMatch(/能量|物质/);
  expect(followup.payload.markdown).not.toMatch(/演示数据|离线示例/);
  await writeFile(testInfo.outputPath("verified-learning-chain.json"), JSON.stringify({ course, questions: shown, report: state.report, plan: state.plan, followup }, null, 2));
});
