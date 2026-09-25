import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { completeIntake, registerLearner } from "./intake-helpers";

async function openAssessment(page: Page) {
  const button = page.getByRole("button", { name: "打开起点测评", exact: true });
  if (!await button.isVisible()) await page.getByLabel("学习菜单", { exact: true }).click();
  await button.click();
}

async function expectCurrentQuestionInView(page: Page, info: TestInfo, step: string) {
  // Read geometry without Playwright scrolling the target into view for us.
  const position = await page.locator(".entry-panel").evaluate((panel) => {
    const card = panel.querySelector(".entry-question-card")!;
    const heading = panel.querySelector(".assessment-stem")!;
    const viewport = panel.getBoundingClientRect();
    const bounds = heading.getBoundingClientRect();
    return {
      scrollTop: panel.scrollTop,
      cardTop: card.getBoundingClientRect().top - viewport.top,
      headingTop: bounds.top - viewport.top,
      headingBottom: bounds.bottom - viewport.top,
      viewportHeight: panel.clientHeight,
      focused: document.activeElement === heading,
      windowScrollY: window.scrollY,
    };
  });
  console.log(`${info.title} / ${step}: ${JSON.stringify(position)}`);
  await info.attach(`${step}-position`, {
    body: JSON.stringify(position, null, 2), contentType: "application/json",
  });
  await page.screenshot({ path: info.outputPath(`${step}.png`) });
  expect(position.scrollTop, "不要返回课程说明的顶部").toBeGreaterThan(0);
  expect(position.headingTop, "下一题题干不能被上边缘遮住").toBeGreaterThanOrEqual(0);
  expect(position.headingBottom, "无需再次滚动即可阅读下一题").toBeLessThanOrEqual(position.viewportHeight);
  expect(position.focused, "键盘焦点随新题移动").toBe(true);
  expect(position.windowScrollY, "仅滚动测评面板，不移动整个页面").toBe(0);
}

for (const viewport of [
  { name: "电脑", width: 1440, height: 900 },
  { name: "手机", width: 390, height: 844 },
]) {
  test(`${viewport.name}：提交、跳过、不会和恢复测评都定位当前题`, async ({ page }, info) => {
    test.setTimeout(180_000);
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await registerLearner(page, "scroll-regression");
    await completeIntake(page);

    for (const [index, action] of ["提交，继续下一题", "暂时跳过此题", "这题还不会"].entries()) {
      if (index === 0) await page.locator(".entry-options input").first().check();
      const previous = await page.locator(".assessment-stem").innerText();
      await page.getByRole("button", { name: action, exact: true }).click();
      await expect(page.locator(".assessment-stem")).not.toHaveText(previous);
      await expect(page.locator(".entry-panel")).toHaveAttribute("aria-busy", "false");
      await expectCurrentQuestionInView(page, info, `answer-${index + 1}`);
      await expect(page.locator(".entry-options input:checked")).toHaveCount(0);
    }

    const current = await page.locator(".assessment-stem").innerText();
    await page.getByRole("button", { name: "暂停，稍后继续", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "学习目标输入", exact: true })).toBeVisible();
    await openAssessment(page);
    await expect(page.locator(".assessment-stem")).toHaveText(current);
    await expect(page.locator(".entry-panel")).toHaveAttribute("aria-busy", "false");
    await expectCurrentQuestionInView(page, info, "resume");

    // Completing the last question should reveal the result, not the course header.
    const activeQuestion = page.locator(".entry-quiz .assessment-stem");
    for (let remaining = 0; remaining < 22 && await activeQuestion.count(); remaining++) {
      const previous = await activeQuestion.innerText();
      await page.getByRole("button", { name: "这题还不会", exact: true }).click();
      await expect.poll(async () => (await activeQuestion.allTextContents()).join("")).not.toBe(previous);
    }
    const result = page.getByRole("heading", { name: /你的学习起点，已经清楚了一些|先学一步，再逐步了解你/, exact: true });
    await expect(result).toBeInViewport({ ratio: 1 });
    await expect(result).toBeFocused();
    await page.screenshot({ path: info.outputPath("completed.png") });
    expect(errors).toEqual([]);
  });
}

test("手机：往返测评保留对话面板的阅读位置", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await registerLearner(page, "scroll-return");
  await completeIntake(page);
  await page.getByRole("button", { name: "暂停，稍后继续", exact: true }).click();
  await page.getByRole("button", { name: "跳过引导", exact: true }).click();
  // A compact welcome screen may fit; use a real message component with long content.
  const answer = "栈遵循后进先出：最后放入的元素最先取出。\n\n".repeat(30);
  await page.route("**/api/chat", route => route.fulfill({ contentType: "text/event-stream",
    body: [{ type: "token", delta: answer }, { type: "done" }].map(event => `data: ${JSON.stringify(event)}\n\n`).join("") }));
  await page.getByLabel("学习目标输入", { exact: true }).fill("阅读位置验收");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByLabel("小知回答").last().locator("p")).toHaveCount(30);
  await expect(page.getByRole("button", { name: "停止等待", exact: true })).toHaveCount(0);
  await page.unroute("**/api/chat");
  const chat = page.locator(".notebook-chat-scroll");
  const before = await chat.evaluate(panel => {
    panel.scrollTop = (panel.scrollHeight - panel.clientHeight) / 2;
    return panel.scrollTop;
  });
  expect(before, "使用实际可滚动的对话面板验证恢复行为").toBeGreaterThan(50);
  await openAssessment(page);
  await expect(page.locator(".entry-quiz .assessment-stem")).toBeVisible();
  await page.getByRole("button", { name: "暂停，稍后继续", exact: true }).click();
  await expect(chat).toBeVisible();
  await expect.poll(async () => Math.abs(await chat.evaluate(panel => panel.scrollTop) - before)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: info.outputPath("chat-return.png") });
});
