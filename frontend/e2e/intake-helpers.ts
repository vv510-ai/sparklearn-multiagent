import { expect, type Page } from "@playwright/test";

export async function completeIntake(page: Page, mode: "screening" | "foundation" | "comprehensive" = "screening") {
  await expect(page.getByRole("heading", { name: "你希望小知先帮你完成什么？" })).toBeVisible();
  await page.getByRole("checkbox", { name: /准备课程考试/ }).check();
  await page.getByRole("checkbox", { name: /完成项目或实际任务/ }).check();
  await page.getByLabel("当前优先解决").selectOption("准备课程考试");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "数据结构与算法", exact: true }).check();
  await page.getByLabel("以前接触过多少？").selectOption("学过概念但做题困难");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("checkbox", { name: /看懂答案，自己不会做/ }).check();
  await page.getByRole("checkbox", { name: /学过很快就忘/ }).check();
  await page.getByRole("checkbox", { name: /符号与步骤讲细些/ }).check();
  await page.getByRole("checkbox", { name: /任务短一些/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByLabel("每个学习日可用时间（分钟）").fill("20");
  await page.getByLabel("什么时机会比较容易开始？").fill("晚饭后坐到书桌前");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  if (mode === "foundation") await page.getByRole("radio", { name: /检查入门基础/ }).check();
  if (mode === "comprehensive") await page.getByRole("radio", { name: /完成所选范围摸底/ }).check();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await expect(page.getByRole("region", { name: "本次学习范围" })).toBeVisible();
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  await expect(page.locator(".learning-intake")).toHaveCount(0);
}

export async function registerLearner(page: Page, prefix: string) {
  const marker = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("起点引导验收");
  await page.getByPlaceholder("you@example.com").fill(`${prefix}-${marker}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Intake-E2E-2026!pass");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await expect(page.getByRole("heading", { name: "你希望小知先帮你完成什么？" })).toBeVisible();
}

export async function currentAssessment(page: Page) {
  const onboarding = await (await page.request.get("/api/onboarding")).json();
  return (await (await page.request.get(`/api/assessment?notebook_id=${onboarding.resume?.notebook_id || ""}`)).json()).assessment;
}
