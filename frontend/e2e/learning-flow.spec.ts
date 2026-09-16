import { expect, test } from "@playwright/test";
import { completeIntake } from "./intake-helpers";

test("学生能注册、获得小知回答并重新登录", async ({ page }) => {
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const learnerName = `E2E 学员 ${runId.slice(-6)}`;
  const email = `sparklearn-e2e-${runId}@example.test`;
  const password = "Playwright-E2E-2026!";
  const question = "请用一句话解释二叉树。";

  await test.step("创建一个隔离的测试账户", async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.getByText("WELCOME TO YOUR LEARNING SPACE", { exact: true })).toBeVisible();
    await expect(page.locator('a[href="/evidence"], a[href="/teacher"]')).toHaveCount(0);
    await page.getByRole("tab", { name: "创建账户" }).click();
    await page.getByPlaceholder("怎么称呼你").fill(learnerName);
    await page.getByPlaceholder("you@example.com").fill(email);
    await page.getByPlaceholder("至少 8 位").fill(password);
    await page.getByRole("button", { name: "创建账户" }).click();

    await expect(page.getByRole("heading", { name: "你希望小知先帮你完成什么？" })).toBeVisible();
    await expect(page.getByText(learnerName, { exact: true })).toBeVisible();
  });

  await test.step("回答短引导并获得个性化第一步", async () => {
    await completeIntake(page);

    await expect(page.getByRole("heading", { name: "起点测评与学习计划" })).toBeVisible();
    await page.getByRole("button", { name: "返回对话", exact: true }).click();
    await expect(page.getByRole("heading", { name: "学习对话" })).toBeVisible();
    await expect(page.getByPlaceholder("你今天想学什么知识？")).toBeVisible();
    await expect(page.locator('a[href="/evidence"], a[href="/teacher"]')).toHaveCount(0);
    await expect(page.getByRole("button", { name: "打开起点测评", exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/learning-workspace-desktop.png", fullPage: true });
  });

  await test.step("从学生看得见的页面发起一次真实学习请求", async () => {
    const input = page.getByPlaceholder("你今天想学什么知识？");
    await expect(input).toBeVisible();
    await input.fill(question);
    await expect(page.getByLabel("发送", { exact: true })).toBeEnabled({ timeout: 120_000 });
    await page.getByLabel("发送", { exact: true }).click();

    await expect(page.getByText(question, { exact: true })).toBeVisible();
    await expect(page.getByLabel("小知回答").last()).toContainText(/\S/);
  });

  await test.step("刷新后仍保持登录身份", async () => {
    await page.reload();
    await expect(page.locator(".entry-question-card")).toBeVisible();
    await page.getByRole("button", { name: "返回对话", exact: true }).click();
    await expect(page.getByPlaceholder("你今天想学什么知识？")).toBeVisible();
    await expect(page.getByText(learnerName, { exact: true })).toBeVisible();
  });

  await test.step("工作台保留课程入口并移除重复首页和显示切换", async () => {
    await expect(page.getByRole("button", { name: "学习首页", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "减少透明效果", exact: true })).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/learning-workspace-mobile.png", fullPage: true });
    await page.setViewportSize({ width: 1280, height: 720 });
  });

  await test.step("退出后可以用同一账户重新登录", async () => {
    await page.getByRole("button", { name: "退出登录" }).click();
    await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();

    await page.getByPlaceholder("you@example.com").fill(email);
    await page.getByPlaceholder("至少 8 位").fill(password);
    await page.getByRole("button", { name: "登录并继续" }).click();

    await expect(page.locator(".entry-question-card")).toBeVisible();
    await page.getByRole("button", { name: "返回对话", exact: true }).click();
    await expect(page.getByPlaceholder("你今天想学什么知识？")).toBeVisible();
    await expect(page.getByText(learnerName, { exact: true })).toBeVisible();
  });
});
