import { expect, test, type Page } from "@playwright/test";
import { dismissGuidance, emptyGuidance, readGuidance, recordLearningTurn, studyStage } from "../lib/learning-guidance";

test.use({ actionTimeout: 20_000 });

test("引导间隔、恢复和关闭不会把轮数当作掌握程度", () => {
  let state = emptyGuidance();
  for (let i = 0; i < 2; i++) state = recordLearningTurn(state, "给我一个例子");
  expect(state.pending).toBeNull();
  state = recordLearningTurn(state, "栈和队列有什么区别");
  expect(state.pending).toBe("framework");
  expect(studyStage(state)).toBe("organize");
  state = dismissGuidance(state);
  for (let i = 0; i < 2; i++) state = recordLearningTurn(state, "再举例");
  expect(state.pending).toBeNull();
  state = recordLearningTurn(state, "想试一试");
  expect(state.pending).toBe("quiz");
  state = readGuidance(JSON.stringify(dismissGuidance(state, true)));
  for (let i = 0; i < 10; i++) state = recordLearningTurn(state, "继续讲解");
  expect(state.pending).toBeNull();
  expect(readGuidance('{"version":1,"turns":-1}')).toEqual(emptyGuidance());
});

async function enter(page: Page, marker: string) {
  await page.setViewportSize({ width: 1512, height: 982 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const response = await page.request.post("/api/auth/register", { data: { email: `guidance-${marker}-${Date.now()}@example.test`, password: "Guidance-e2e-2026!", name: "引导验收" } });
  expect(response.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBeTruthy();
  const notebook = await (await page.request.post("/api/notebooks", { data: { title: "数据结构学习" } })).json();
  await page.goto("/");
  await page.getByRole("button", { name: "跳过引导", exact: true }).click();
  await page.getByLabel("切换科目书本").selectOption(notebook.id);
  await expect(page.getByLabel("切换科目书本")).toBeEnabled();
  await expect(page.getByLabel("学习目标输入")).toBeVisible();
  return notebook;
}

const answer = "栈记录一组等待处理的元素，遵循后进先出。想象依次放上红、蓝、绿三本书，最先取到绿色。入栈是在栈顶加入元素，出栈从栈顶移走元素；空栈不能再出栈。与队列比较时，要同时看进入和离开的规则，不能只根据摆放的外观判断。";
function sse(events: Record<string, unknown>[]) {
  return events.map(event => `data: ${JSON.stringify(event)}\n\n`).join("");
}

async function send(page: Page, question: string) {
  await page.getByLabel("学习目标输入").fill(question);
  const response = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await response;
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
}

test("功能直接展示、成功问答触发建议、明确选择后才生成并保留笔记原文", async ({ page }, info) => {
  const notebook = await enter(page, "tools");
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const studio = page.getByLabel("学习工坊", { exact: true });
  await expect(studio.locator(".studio-tile")).toHaveCount(11);
  await expect(studio.getByRole("button", { name: /全部工具/ })).toHaveCount(0);

  await page.route("**/api/chat", async route => {
    const question = route.request().postDataJSON().message;
    const events = question === "模拟失败" ? [{ type: "error", detail: "测试中断" }, { type: "done" }]
      : [{ type: "progress", stage: "learning_focus", text: question }, { type: "token", delta: answer }, { type: "done" }];
    await route.fulfill({ contentType: "text/event-stream", body: sse(events) });
  });
  const requests: Record<string, unknown>[] = [];
  const teacherPrompt = "用 {topic} 举例，不修改占位符。";
  await page.route("**/api/resources/generate", async route => {
    const body = route.request().postDataJSON();
    requests.push(body);
    const resource = body.prompt_template === "framework"
      ? { id: "guide-map", kind: "mindmap", kp: "stack", title: "本次知识框架", payload: { markmap: "# 栈和队列\n## 后进先出\n## 先进先出" }, citations: [] }
      : { id: "guide-note", kind: "doc", kp: "stack", title: "栈学习笔记", payload: { template: "complete_notes", markdown: `# 老师的模板\n\n\`\`\`text\n${teacherPrompt}\n\`\`\``, notes_scope: "本次依据 1 个相关资料片段和可用对话整理，未对整份课件逐页核验。" }, citations: [] };
    await route.fulfill({ contentType: "text/event-stream", body: sse([{ type: "resource", resource }, { type: "done" }]) });
  });
  await send(page, "栈是什么");
  await send(page, "模拟失败");
  await send(page, "解释入栈和出栈");
  await expect(page.getByRole("region", { name: "学习工具建议" })).toHaveCount(0);
  await send(page, "栈和队列有什么区别");
  const suggestion = page.getByRole("region", { name: "学习工具建议" });
  await expect(suggestion.getByRole("heading", { name: "框架导图", exact: true })).toBeVisible();
  await expect(studio.locator(".studio-tile")).toHaveCount(11);
  await expect(studio.getByRole("heading", {name:"换道题，看看能不能自己做"})).toBeVisible();
  expect(requests).toHaveLength(0);
  await page.screenshot({ path: info.outputPath("guidance-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await suggestion.scrollIntoViewIfNeeded();
  await expect(suggestion).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("guidance-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "学习工坊", exact: true }).click();
  const mobileStudio = page.locator(".notebook-mobile-sheet");
  await expect(mobileStudio.locator(".studio-tile")).toHaveCount(11);
  await mobileStudio.getByRole("button", { name: "关闭", exact: true }).click();
  await suggestion.getByRole("button", { name: "生成框架导图", exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({ prompt_template: "framework", artifact_scope: "conversation", notebook_id: notebook.id, session_id: notebook.session_id, kinds: ["mindmap"] });
  await expect(page.getByRole("region", { name: "学习工具建议" })).toHaveCount(0);
  await page.setViewportSize({ width: 1512, height: 982 });
  await studio.getByRole("button", { name: /学习笔记.*定义/ }).click();
  await page.getByRole("button", { name: /栈学习笔记/ }).click();
  await expect(page.locator("pre").filter({ hasText: teacherPrompt })).toBeVisible();
  await expect(page.getByText(/未对整份课件逐页核验/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("稍后提醒留出间隔，关闭提醒可恢复且不影响新对话", async ({ page }) => {
  const notebook = await enter(page, "dismiss");
  await page.route("**/api/chat", route => route.fulfill({ contentType: "text/event-stream", body: sse([
    { type: "progress", stage: "learning_focus", text: "栈的操作" }, { type: "token", delta: answer }, { type: "done" },
  ]) }));
  for (let i = 0; i < 3; i++) await send(page, `给我解释入栈，第 ${i + 1} 步`);
  const card = page.getByRole("region", { name: "学习工具建议" });
  await expect(card.getByRole("heading", { name: "一图看懂" })).toBeVisible();
  await card.getByRole("button", { name: "继续聊，稍后再说" }).click();
  for (let i = 0; i < 2; i++) await send(page, `再解释一个例子 ${i}`);
  await expect(card).toHaveCount(0);
  await send(page, "现在想独立试一试");
  await expect(card.getByRole("heading", { name: "巩固测验" })).toBeVisible();
  await card.getByRole("button", { name: "本次对话不再提醒" }).click();
  await page.reload();
  await page.getByLabel("切换科目书本").selectOption(notebook.id);
  await expect(page.getByLabel("切换科目书本")).toBeEnabled();
  for (let i = 0; i < 3; i++) await send(page, `继续讨论，例子 ${i}`);
  await expect(card).toHaveCount(0);
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await expect(page.getByRole("heading", { name: "从一个问题开始" })).toBeVisible();
  for (let i = 0; i < 3; i++) await send(page, `新对话的例子 ${i}`);
  await expect(card).toBeVisible();
});
