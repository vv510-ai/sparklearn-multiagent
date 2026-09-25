import { expect as baseExpect, test, type Page } from "@playwright/test";
const expect = baseExpect.configure({ timeout: 15_000 });
test.use({ actionTimeout: 15_000 });

// Deterministic teaching content for visual comparison, not a model-quality test.
const answer = `先记住：affect 常作动词，effect 常作名词。

> **affect**　动词
>
> 影响某人或某事

> **effect**　名词
>
> 产生的结果

### 例句

1. Lack of sleep **affects** memory.${"  "}
   睡眠不足会影响记忆力。
2. Sleep has an **effect** on memory.${"  "}
   睡眠对记忆力有影响。`;
const evidence = [{ index: 1, citation: "讲义 · 第 2 页", source: "六级词汇讲义", page: "2", excerpt: "affect 常作动词，effect 常作名词。" }];
const events = [{ type: "progress", stage: "learning_focus", text: "affect 和 effect 的区别" }, { type: "token", delta: answer }, { type: "citations", agent: "tutor", evidence }, { type: "done" }];
const sse = events.map(event => `data: ${JSON.stringify(event)}\n\n`).join("");

async function enter(page: Page) {
  const response = await page.request.post("/api/auth/register", { data: {
    email: `conversation-${Date.now()}-${Math.random().toString(36).slice(2, 6)}@example.test`,
    password: "Conversation-Acceptance-2026!", name: "对话界面验收",
  } });
  expect(response.status()).toBe(201);
  await page.request.post("/api/onboarding", { data: { skipped: true } });
  const notebook = await (await page.request.post("/api/notebooks", { data: { title: "英语六级" } })).json();
  await page.route("**/api/knowledge/sources?**", route => route.fulfill({ json: { items: [{
    id: "visual-source", title: "六级词汇讲义", source_type: "text", status: "indexed", chunk_count: 2,
  }] } }));
  await page.route("**/api/chat", route => route.fulfill({ contentType: "text/event-stream", body: sse }));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "跳过引导", exact: true }).click();
  await expect(page.locator(".workspace-course")).toHaveText("英语六级");
  await expect(page.getByRole("button", { name: "查看已选资料" })).toContainText("六级词汇讲义");
  return notebook;
}

async function ask(page: Page) {
  await page.getByLabel("学习目标输入", { exact: true }).fill("affect 和 effect 怎么区分？");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByLabel("小知回答")).toContainText("产生的结果");
  await expect(page.getByRole("button", { name: "停止等待" })).toHaveCount(0);
}

test("融合稿：多尺寸正文、资料状态与输入区，无重复标题或常驻底栏", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await enter(page);
  await ask(page);
  for (const [width, height] of [[320, 740], [360, 800], [390, 844], [430, 932], [768, 1024], [1024, 768], [1440, 900], [1920, 1080], [640, 420]]) {
    await page.setViewportSize({ width, height });
    await page.locator(".notebook-chat-scroll").evaluate(el => { el.scrollTop = 0; });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator(".notebook-mobile-nav, .notebook-chat-header, .learning-context-strip")).toHaveCount(0);
    await expect(page.getByLabel("学习目标输入", { exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport({ ratio: 1 });
    if (width < 900 && height > 540) {
      expect((await page.locator(".notebook-topbar").boundingBox())!.height).toBeLessThanOrEqual(56);
      expect((await page.locator(".notebook-chat-scroll").boundingBox())!.height / height).toBeGreaterThan(.68);
      expect((await page.getByLabel("学习目标输入").boundingBox())!.width).toBeGreaterThan(width - 60);
    }
    await page.screenshot({ path: info.outputPath(`conversation-${width}x${height}.png`) });
  }
  expect(errors).toEqual([]);
});

test("资料按需显示，严格依据状态不隐藏，抽屉可退出并恢复焦点", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  const sourceEntry = page.getByRole("button", { name: "查看已选资料" });
  await sourceEntry.click();
  const drawer = page.getByRole("dialog", { name: "学习来源", exact: true });
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: /六级词汇讲义/ }).click();
  await drawer.getByRole("button", { name: "返回学习" }).click();
  await expect(sourceEntry).toHaveCount(0);
  await page.getByLabel("对话选项", { exact: true }).click();
  await page.getByLabel("回答依据", { exact: true }).selectOption("strict");
  await page.getByLabel("对话选项", { exact: true }).press("Escape");
  await expect(sourceEntry).toContainText("尚未选择资料");
  await expect(sourceEntry).toContainText("仅依据资料");
  const request = page.waitForRequest(value => value.url().endsWith("/api/chat") && value.method() === "POST");
  await ask(page);
  expect((await request).postDataJSON()).toMatchObject({ source_ids: [], source_policy: "strict" });
  await sourceEntry.click();
  await drawer.getByRole("button", { name: /六级词汇讲义/ }).click();
  await drawer.press("Escape");
  await expect(sourceEntry).toBeFocused();
  await expect(sourceEntry).toContainText("六级词汇讲义");
  await page.getByLabel("对话选项", { exact: true }).click();
  await page.locator(".composer-options").getByRole("button", { name: "学习工坊", exact: true }).click();
  const studio = page.getByRole("dialog", { name: "学习工坊", exact: true });
  await expect(studio.locator(".studio-tile")).toHaveCount(11);
  await page.screenshot({ path: info.outputPath("mobile-tools.png") });
  await studio.press("Escape");
  await expect(page.getByLabel("对话选项", { exact: true })).toBeFocused();
});

test("引用可展开、复制可用，练习调用现有生成流程且新对话保留课程", async ({ page, context }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const notebook = await enter(page);
  await ask(page);
  await page.locator(".chat-source-evidence summary").click();
  await expect(page.locator(".chat-source-evidence details")).toHaveAttribute("open", "");
  await expect(page.locator(".chat-source-evidence")).toContainText(evidence[0].excerpt);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "复制回答" }).click();
  expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n")).toBe(answer);
  let generation: Record<string, unknown> | undefined;
  await page.route("**/api/resources/generate", async route => {
    generation = route.request().postDataJSON();
    await route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done" })}\n\n` });
  });
  await page.getByRole("button", { name: "练一题", exact: true }).click();
  await expect.poll(() => generation?.notebook_id).toBe(notebook.id);
  expect(generation?.kinds).toEqual(["quiz"]);
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await expect(page.getByLabel("小知回答")).toHaveCount(0);
  await expect(page.locator(".workspace-course")).toHaveText("英语六级");
  await expect(page.getByRole("button", { name: "查看已选资料" })).toContainText("六级词汇讲义");
  await page.screenshot({ path: info.outputPath("mobile-empty.png") });
});

test("长课程名、长文件名和放大文字不挤走菜单与发送", async ({ page }, info) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await enter(page);
  await ask(page);
  await page.evaluate(() => {
    document.querySelector(".workspace-course span")!.textContent = "大学英语六级词汇与阅读理解综合提升课程".repeat(4);
    document.querySelector(".chat-source-title")!.textContent = "这是一份文件名特别长的复习资料.pdf".repeat(4);
    document.documentElement.style.fontSize = "32px";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByLabel("学习菜单", { exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport({ ratio: 1 });
  await page.getByLabel("对话选项", { exact: true }).click();
  await expect(page.getByLabel("回答依据")).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: info.outputPath("mobile-long-labels-large-root-font.png") });
});
