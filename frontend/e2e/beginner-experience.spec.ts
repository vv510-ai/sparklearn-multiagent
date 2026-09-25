import { expect, test, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { registerLearner, currentAssessment } from "./intake-helpers";

async function startEnglishIntake(page: Page) {
  await registerLearner(page, "beginner-experience");
  await page.getByRole("checkbox", { name: /从零开始，系统学习/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "大学英语六级（CET-6）", exact: true }).check();
  await page.getByLabel("以前接触过多少？").selectOption("第一次系统学习");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
}

test("课程信息栏出现后，聊天输入与发送仍完整可见", async ({ page }, info) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 800 });
  await startEnglishIntake(page);
  await page.getByRole("button", { name: "返回对话", exact: true }).click();
  await expect(page.locator(".learning-context-strip")).toContainText("大学英语六级");
  const input = page.getByRole("textbox", { name: "学习目标输入", exact: true });
  for (const [width, height] of [[1440, 800], [1280, 650], [390, 844], [640, 420]]) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: info.outputPath(`chat-${width}-${height}.png`), fullPage: true });
    await expect(input).toBeInViewport({ ratio: 1, timeout: 5000 });
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport({ ratio: 1, timeout: 5000 });
    expect(await input.evaluate(element => {
      const rect = element.getBoundingClientRect();
      return document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2) === element;
    })).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 800 });
  const question = "我刚开始学六级，请用一个简单例子解释怎样根据上下文理解单词，先不要出题。";
  await input.fill(question);
  await input.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true });
  await expect(input).toHaveValue(question); // Confirming a Chinese IME word must not send it.
  const request = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  expect((await request).status()).toBe(200);
  await expect(page.locator('[aria-label="小知回答"]').last()).toBeVisible();
  await expect(page.getByRole("button", { name: "停止等待", exact: true })).toHaveCount(0, { timeout: 180_000 });
  expect((await page.locator('[aria-label="小知回答"]').last().innerText()).length).toBeGreaterThan(40);
  await expect(input).toBeInViewport({ ratio: 1, timeout: 5000 });
  await page.screenshot({ path: info.outputPath("chat-reply-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(input).toBeInViewport({ ratio: 1, timeout: 5000 });
  const followup = "我明白了，要把单词放回整句话理解。";
  await input.fill(followup);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(input).toHaveValue("");
  await expect(page.getByRole("button", { name: "停止等待", exact: true })).toHaveCount(0, { timeout: 180_000 });
  const state = await currentAssessment(page);
  const book = await (await page.request.get(`/api/notebooks/${state.notebook_id}?user_id=session_user`)).json();
  expect(book.messages.filter((m: { role: string }) => m.role === "user").map((m: { content: string }) => m.content)).toEqual(expect.arrayContaining([question, followup]));
  await expect(input).toBeInViewport({ ratio: 1, timeout: 5000 });
  expect(await page.locator("main.notebook-app").evaluate(el => el.scrollLeft)).toBe(0);
  await writeFile(info.outputPath("mobile-layout.json"), JSON.stringify(await page.evaluate(() =>
    Array.from(document.querySelectorAll("html, body, main, .notebook-topbar, .notebook-layout, .notebook-main-column, .notebook-chat-shell, .notebook-chat-scroll, .notebook-chat-footer")).map(el => {
      const r = el.getBoundingClientRect();
      return { tag: el.tagName, class: el.className, x: r.x, y: r.y, width: r.width, height: r.height, scrollLeft: el.scrollLeft, scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
    })), null, 2));
  await page.screenshot({ path: info.outputPath("chat-reply-mobile.png"), fullPage: true });
});

test("新手能试答、暂停续答，并清楚区分正式作答和答案复盘", async ({ page }, info) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  await startEnglishIntake(page);
  const initial = await currentAssessment(page);
  expect(initial.maximum).toBe(6);
  await expect(page.locator(".question-instruction")).toContainText("本题选一个答案");
  await page.locator(".answer-guide summary").click();
  await page.getByRole("radio", { name: "B. 我想慢慢来" }).check();
  await page.getByRole("button", { name: "提交演示答案" }).click();
  await expect(page.locator(".answer-guide")).toContainText("不会计入测评");
  expect((await currentAssessment(page)).answered).toBe(0);
  await page.locator(".answer-guide summary").click();
  await page.locator(".assessment-basis summary").click();
  await expect(page.locator(".assessment-basis")).toContainText("不能预测六级分数");
  await page.locator(".assessment-basis summary").click();
  await page.locator(".entry-options label").nth(1).click();
  await expect(page.locator(".entry-answer-status")).toContainText("已选择 B");
  await page.locator(".entry-question-card").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("answer-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "提交，继续下一题" }).click();
  await expect(page.getByText("已提交 1 题 / 最多 6 题", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "暂停，稍后继续" }).click();
  await page.reload();
  await page.getByRole("button", { name: "打开起点测评", exact: true }).click();
  await expect(page.getByText("已提交 1 题 / 最多 6 题", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "暂时跳过此题" }).click();
  await expect(page.getByText("已提交 2 题 / 最多 6 题", { exact: true })).toBeVisible();
  for (let answered = 2; answered < 6; answered++) {
    await page.getByRole("button", { name: "这题还不会", exact: true }).click();
    if (answered < 5) await expect(page.getByText(`已提交 ${answered + 1} 题 / 最多 6 题`, { exact: true })).toBeVisible();
  }
  const review = page.getByRole("region", { name: "已提交答案复盘" });
  await expect(review).toBeVisible();
  await review.scrollIntoViewIfNeeded();
  await expect(review).toContainText("这是复盘区，不需要再答一次");
  await expect(review.locator(".review-options li")).toHaveCount(4);
  await expect(review).toContainText("你当时的回答：B.");
  await expect(review).toContainText("参考答案：");
  await page.screenshot({ path: info.outputPath("review-mobile.png"), fullPage: true });
  await review.getByRole("button", { name: "下一题解析" }).click();
  await expect(review).toContainText("当时跳过 · 不计错");
  await review.getByLabel("选择复盘题目").selectOption("0");
  await expect(review).toContainText("你当时的回答：B.");
  const state = await currentAssessment(page);
  expect(state.report.skills.filter((s: { status: string }) => s.status === "unmeasured")).toHaveLength(5);
  await page.setViewportSize({ width: 1280, height: 800 });
  await review.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("review-desktop.png"), fullPage: true });
  const chatResponse = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await review.getByRole("button", { name: "让小知讲解这一题" }).click();
  const response = await chatResponse;
  expect(response.status()).toBe(200);
  const payload = response.request().postDataJSON();
  expect(payload.notebook_id).toBe(state.notebook_id);
  expect(payload.message).toContain(initial.question.stem);
  expect(payload.message).toContain("我的回答：B.");
  await expect(page.getByRole("button", { name: "停止等待", exact: true })).toHaveCount(0, { timeout: 180_000 });
  await expect(page.locator('[aria-label="小知回答"]').last()).toBeVisible();
  await expect(page.getByRole("textbox", { name: "学习目标输入", exact: true })).toBeInViewport({ ratio: 1, timeout: 5000 });
  expect((await currentAssessment(page)).report).toEqual(state.report);
});
