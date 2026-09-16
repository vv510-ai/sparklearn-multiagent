import { expect, test } from "@playwright/test";
import { registerLearner, currentAssessment } from "./intake-helpers";

test("注册直接多选引导，Python 计划与高数课程独立，并自动续答", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 980 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await registerLearner(page, "multicourse");
  await page.getByRole("checkbox", { name: /听懂了，但自己不会做/ }).check();
  await page.getByRole("checkbox", { name: /制定计划，安排复习/ }).check();
  await page.screenshot({ path: testInfo.outputPath("01-intent.png"), fullPage: true });
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "Python 入门", exact: true }).check();
  await page.getByLabel("以前接触过多少？").selectOption("第一次系统学习");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("checkbox", { name: /思路懂，代码写不出/ }).check();
  await page.getByRole("checkbox", { name: /符号与步骤讲细些/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByLabel("每个学习日可用时间（分钟）").fill("15");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "生成并核对学习范围" }).click();
  await expect(page.getByRole("region", { name: "本次学习范围" })).toContainText("变量与表达式");
  await page.screenshot({ path: testInfo.outputPath("02-outline.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("03-outline-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "确认范围，开始独立作答" }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  let state = await currentAssessment(page);
  const pythonId = state.notebook_id;
  for (let i = 0; i < 12; i++) {
    await expect(page.getByText(`已提交 ${i} 题 / 最多 12 题`, { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "这题还不会", exact: true }).click();
    if (i === 1) {
      await expect(page.getByText("已提交 2 题 / 最多 12 题", { exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByText("已提交 2 题 / 最多 12 题", { exact: true })).toBeVisible();
    }
  }
  await expect(page.getByRole("heading", { name: "你的学习起点，已经清楚了一些" })).toBeVisible();
  state = await currentAssessment(page);
  expect(state.course.title).toBe("Python 入门");
  expect(state.plan.adaptations.join(" ")).toContain("符号");
  expect(state.plan.days.every((d: { minutes: number; capacity: number }) => d.minutes <= d.capacity)).toBe(true);
  await page.getByRole("button", { name: "开始第一项学习任务" }).click();
  await expect(page.locator(".entry-study")).toContainText("变量");
  await expect(page.locator(".entry-study")).not.toContainText("数据结构");
  await page.screenshot({ path: testInfo.outputPath("04-learning-material.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 980 });
  const bookResponse = await page.request.post("/api/notebooks", { data: { user_id: "session_user", title: "高等数学入门" } });
  expect(bookResponse.ok()).toBe(true);
  const maths = await bookResponse.json();
  await page.reload();
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(maths.id);
  await page.getByRole("button", { name: "打开起点测评", exact: true }).click();
  await expect(page.getByRole("heading", { name: "你希望小知先帮你完成什么？" })).toBeVisible();
  expect((await (await page.request.get(`/api/assessment?notebook_id=${maths.id}`)).json()).assessment).toBeNull();
  await page.route(`**/api/notebooks/${pythonId}?*`, async route => {
    await new Promise(resolve => setTimeout(resolve, 750));
    await route.continue();
  });
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(pythonId);
  await page.getByRole("button", { name: "打开起点测评", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "切换科目书本" })).toBeEnabled();
  await expect(page.getByRole("heading", { name: "你的学习起点，已经清楚了一些" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("05-separated-plan.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("引导状态读取失败提供重试，不把用户静默放行", async ({ page }) => {
  await page.route("**/api/onboarding", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary failure" }) }));
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("状态恢复测试");
  await page.getByPlaceholder("you@example.com").fill(`retry-${Date.now()}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Retry-Check-Password!");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await expect(page.getByRole("button", { name: "重试读取学习进度" })).toBeVisible();
  await expect(page.locator("main.notebook-app")).toHaveCount(0);
  await page.unroute("**/api/onboarding");
  await page.getByRole("button", { name: "重试读取学习进度" }).click();
  await expect(page.getByRole("heading", { name: "你希望小知先帮你完成什么？" })).toBeVisible();
});
