import { expect, test } from "@playwright/test";

test("学生能注册、获得学伴回答并重新登录", async ({ page }) => {
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const learnerName = `E2E 学员 ${runId.slice(-6)}`;
  const email = `sparklearn-e2e-${runId}@example.test`;
  const password = "Playwright-E2E-2026!";
  const question = "请用一句话解释二叉树。";

  await test.step("创建一个隔离的测试账户", async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.getByText("WELCOME TO YOUR LEARNING SPACE", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "创建账户" }).click();
    await page.getByPlaceholder("怎么称呼你").fill(learnerName);
    await page.getByPlaceholder("you@example.com").fill(email);
    await page.getByPlaceholder("至少 8 位").fill(password);
    await page.getByRole("button", { name: "创建账户" }).click();

    await expect(page.getByRole("heading", { name: "你现在最想学什么？" })).toBeVisible();
    await expect(page.getByText("WELCOME TO YOUR LEARNING SPACE", { exact: true })).toBeVisible();
    await expect(page.getByText(learnerName, { exact: true })).toBeVisible();
  });

  await test.step("回答短引导并获得个性化第一步", async () => {
    const choose = async (name: RegExp) => {
      await page.getByRole("button", { name }).click();
      await page.getByRole("button", { name: "下一题" }).click();
    };
    await choose(/树与图.*二叉树/);
    await choose(/能做基础题/);
    await choose(/竞赛 \/ 刷题/);
    await choose(/每周 3 小时/);
    await choose(/先做题再讲解/);
    await page.getByRole("button", { name: /暂时没有/ }).click();
    await page.getByRole("button", { name: "保存并开始学习" }).click();

    await expect(page.getByRole("heading", { name: "学习对话" })).toBeVisible();
    await expect(page.getByPlaceholder("你今天想学什么知识？")).toBeVisible();
  });

  await test.step("从学生看得见的页面发起一次真实学习请求", async () => {
    const input = page.getByPlaceholder("你今天想学什么知识？");
    await expect(input).toBeVisible();
    await input.fill(question);
    await expect(page.getByLabel("发送", { exact: true })).toBeEnabled({ timeout: 120_000 });
    await page.getByLabel("发送", { exact: true }).click();

    await expect(page.getByText(question, { exact: true })).toBeVisible();
    await expect(page.getByLabel("学伴回答").last()).toContainText(/\S/);
  });

  await test.step("刷新后仍保持登录身份", async () => {
    await page.reload();
    await expect(page.getByPlaceholder("你今天想学什么知识？")).toBeVisible();
    await expect(page.getByText(learnerName, { exact: true })).toBeVisible();
  });

  await test.step("退出后可以用同一账户重新登录", async () => {
    await page.getByRole("button", { name: "退出登录" }).click();
    await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();

    await page.getByPlaceholder("you@example.com").fill(email);
    await page.getByPlaceholder("至少 8 位").fill(password);
    await page.getByRole("button", { name: "登录并继续" }).click();

    await expect(page.getByPlaceholder("你今天想学什么知识？")).toBeVisible();
    await expect(page.getByText(learnerName, { exact: true })).toBeVisible();
  });
});
