import { expect, test, type Page, type TestInfo } from "@playwright/test";
import type { QuizQuestion, ResourceItem } from "../lib/types";

test.use({ actionTimeout: 15_000 });

async function enter(page: Page) {
  const email = `responsive-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.test`;
  const password = "Responsive-Acceptance-2026!";
  const response = await page.request.post("/api/auth/register", { data: { email, password, name: "多端体验工程验收" } });
  expect(response.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBe(true);
  const notebook = await (await page.request.post("/api/notebooks", { data: { title: "数据结构多端验收" } })).json();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const skip = page.getByRole("button", { name: "跳过引导", exact: true });
  await expect(skip).toBeVisible();
  await skip.click();
  await expect(page.getByLabel("学习目标输入", { exact: true })).toBeVisible();
  await expect.poll(() => page.locator(".notebook-topbar").innerText()).toContain(notebook.title);
  return { notebook, email, password };
}

async function assertFit(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.getByLabel("学习目标输入", { exact: true })).toBeInViewport({ ratio: 1 });
}

async function archive(page: Page) {
  await expect(page.locator(".notebook-topbar")).toBeVisible();
  if (await page.locator(".workspace-studio").isVisible()) {
    await page.locator(".workspace-studio").getByRole("button", { name: /资料归档/ }).click();
  } else {
    if (await page.getByRole("button", { name: "切换工坊栏", exact: true }).isVisible()) {
      await page.getByRole("button", { name: "切换工坊栏", exact: true }).click();
    } else {
      await page.getByLabel("学习菜单", { exact: true }).click();
      await page.locator(".workspace-actions").getByRole("button", { name: "学习工坊", exact: true }).click();
    }
    await page.locator(".notebook-mobile-sheet").getByRole("button", { name: /资料归档/ }).click();
  }
  await expect(page.getByRole("heading", { name: "资料归档", exact: true })).toBeVisible();
}

async function screenshot(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(`${name}.png`) });
}

test("手机、窄平板、双栏平板和电脑均可阅读输入，侧栏可调节收起", async ({ page }, info) => {
  await enter(page);
  for (const [width, height] of [[360, 800], [390, 844], [430, 932], [768, 1024], [900, 720], [1024, 768], [1280, 800], [1440, 900], [1920, 1080], [640, 420]]) {
    await page.setViewportSize({ width, height });
    await assertFit(page);
    if (width < 900 && height > 540) {
      const ratio = await page.locator(".notebook-chat-scroll").evaluate(el => el.getBoundingClientRect().height / innerHeight);
      expect(ratio).toBeGreaterThan(.58);
    }
    await screenshot(page, info, `workspace-${width}x${height}`);
  }
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect(page.locator(".workspace-sources")).toBeVisible();
  await expect(page.locator(".workspace-studio")).toBeHidden();
  const resizer = page.getByRole("separator", { name: "资料栏宽度" });
  await resizer.focus();
  await resizer.press("End");
  await expect(resizer).toHaveAttribute("aria-valuenow", "380");
  await page.getByLabel("对话选项", { exact: true }).click();
  await expect(page.getByLabel("回答依据")).toBeInViewport({ ratio: 1 });
  await page.getByLabel("对话选项", { exact: true }).press("Escape");
  await page.getByRole("button", { name: "切换资料栏" }).click();
  await expect(page.locator(".workspace-sources")).toBeHidden();
  await assertFit(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "切换工坊栏" }).click();
  await expect(page.locator(".workspace-studio")).toBeHidden();
  await assertFit(page);
});

test("长消息展开、中文输入、刷新恢复、失败重试和课程隔离", async ({ page }, info) => {
  const { notebook } = await enter(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const input = page.getByLabel("学习目标输入", { exact: true });
  const draft = "我想解释一下栈和队列的区别。\n".repeat(15);
  await input.fill(draft);
  expect((await input.boundingBox())!.height).toBeGreaterThan(90);
  await input.dispatchEvent("keydown", { key: "Enter", isComposing: true });
  await expect(input).toHaveValue(draft);
  await page.getByRole("button", { name: "展开编辑" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑消息" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("textbox")).toHaveValue(draft);
  const revised = draft + "请帮我检查推理是否完整。";
  await dialog.getByRole("textbox").fill(revised);
  await screenshot(page, info, "mobile-expanded-composer");
  await dialog.getByRole("textbox").press("Escape");
  await expect(input).toHaveValue(revised);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(input).toHaveValue(revised);
  await page.route("**/api/chat", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "验收用网络中断" }) }));
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText(/验收用网络中断/)).toBeVisible();
  await expect(input).toHaveValue(revised);
  await page.unroute("**/api/chat");
  const other = await (await page.request.post("/api/notebooks", { data: { title: "另一个课程" } })).json();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(input).toHaveValue(revised);
  await page.getByRole("button", { name: "学习来源", exact: true }).click();
  await page.locator(".notebook-mobile-sheet").getByLabel("切换科目书本").selectOption(other.id);
  await expect(input).toHaveValue("");
  await page.getByRole("button", { name: "学习来源", exact: true }).click();
  await page.locator(".notebook-mobile-sheet").getByLabel("切换科目书本").selectOption(notebook.id);
  await expect(input).toHaveValue(revised);
});

test("专注练习单题导航、草稿、提示证据同步、提交和复盘", async ({ page }, info) => {
  test.setTimeout(240_000);
  const { notebook } = await enter(page);
  const generated = await page.request.post("/api/resources/generate", { data: {
    user_id: "session_user", session_id: notebook.session_id, notebook_id: notebook.id,
    goal: "练习栈和队列", knowledge_points: ["stack"], kinds: ["quiz"],
  }, timeout: 120_000 });
  expect(generated.ok()).toBe(true);
  const events = (await generated.text()).split("\n").filter(line => line.startsWith("data: ")).map(line => JSON.parse(line.slice(6)));
  const resource = events.find(event => event.type === "resource" && event.resource.kind === "quiz")?.resource as ResourceItem;
  expect(resource?.payload.questions?.length).toBeGreaterThan(1);
  // Reuse the server-persisted resource in a deterministic chat transport fixture.
  await page.route("**/api/chat", route => route.fulfill({ contentType: "text/event-stream", body: [{ type: "resource", resource }, { type: "done" }].map(event => `data: ${JSON.stringify(event)}\n\n`).join("") }));
  await page.getByLabel("学习目标输入").fill("打开已生成的验收练习");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.locator(".notebook-chat-scroll .learning-resource-card > button").click();
  await page.unroute("**/api/chat");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: /开始专注作答/ }).click();
  const dialog = page.getByRole("dialog", { name: "专注作答", exact: true });
  const questions = resource.payload.questions!;
  async function answer(q: QuizQuestion, i: number) {
    const card = dialog.locator(".quiz-question");
    if (q.type === "single" || q.type === "complexity" && q.options.length) await card.getByRole("button").first().click();
    else if (q.type === "judge") await card.getByRole("button", { name: "对", exact: true }).click();
    else await dialog.getByLabel(`第 ${i + 1} 题答案`).fill(q.type === "design" ? "这里保留一段独立作答的推理和答案。" : q.answer);
    await card.getByRole("button", { name: "有点把握", exact: true }).click();
  }
  await expect(dialog.locator(".quiz-question")).toHaveCount(1);
  await answer(questions[0], 0);
  await screenshot(page, info, "mobile-focused-quiz");
  await dialog.getByRole("button", { name: "下一题", exact: true }).click();
  await expect(dialog.locator(".quiz-question")).toBeFocused();
  await expect.poll(() => dialog.locator(".study-dialog-body").evaluate(el => el.scrollTop)).toBe(0);
  await dialog.getByRole("button", { name: "返回学习" }).click();
  await expect(page.getByRole("button", { name: /继续专注作答/ })).toBeFocused();
  await archive(page);
  await page.locator(".notebook-content-scroll .learning-resource-card > button").first().click();
  await page.getByRole("button", { name: /继续专注作答/ }).filter({ visible: true }).click();
  await dialog.getByLabel("选择题目").selectOption("0");
  await dialog.getByRole("button", { name: "给我一个提示", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "已使用提示", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "返回学习" }).click();
  await page.getByRole("button", { name: "学习对话", exact: true }).click();
  await page.getByRole("button", { name: /继续专注作答/ }).filter({ visible: true }).click();
  await expect(dialog.getByRole("button", { name: "已使用提示", exact: true })).toBeVisible();
  for (let i = 1; i < questions.length; i++) {
    await dialog.getByLabel("选择题目").selectOption(String(i));
    await answer(questions[i], i);
    if (questions[i].type === "design") await screenshot(page, info, "mobile-written-answer");
  }
  const submit = page.waitForResponse(response => response.url().endsWith("/api/eval/submit"));
  await dialog.getByRole("button", { name: "提交并更新掌握度", exact: true }).click();
  const response = await submit;
  expect(response.ok()).toBe(true);
  expect(response.request().postDataJSON().answers[0].hint_used).toBe(true);
  await expect(page.getByRole("dialog", { name: "作答复盘", exact: true })).toBeVisible();
  await screenshot(page, info, "mobile-quiz-report");
  await page.getByRole("button", { name: "返回学习", exact: true }).click();
  await page.reload({ waitUntil: "domcontentloaded" });
  await archive(page);
  await page.locator(".notebook-content-scroll .learning-resource-card > button").first().click();
  await expect(page.getByRole("button", { name: /查看作答复盘/ })).toBeVisible();
});

test("可视视口缩短时发送区可见，恢复后仍无常驻底栏", async ({ page }, info) => {
  await enter(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("学习目标输入").fill("验证软键盘布局");
  // Simulates the VisualViewport API; an actual OS keyboard still needs device acceptance.
  await page.evaluate(() => {
    Object.defineProperty(window.visualViewport, "height", { configurable: true, value: 400 });
    window.visualViewport!.dispatchEvent(new Event("resize"));
  });
  await expect(page.locator("html")).toHaveAttribute("data-study-keyboard", "true");
  await expect(page.locator(".notebook-mobile-nav")).toBeHidden();
  expect((await page.getByRole("button", { name: "发送", exact: true }).boundingBox())!.y).toBeLessThan(400);
  await screenshot(page, info, "simulated-keyboard");
  await page.evaluate(() => {
    Reflect.deleteProperty(window.visualViewport!, "height");
    window.visualViewport!.dispatchEvent(new Event("resize"));
  });
  await expect(page.locator(".notebook-mobile-nav")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "学习来源", exact: true })).toBeVisible();
  await assertFit(page);
});

test("第二个独立浏览器登录后可恢复服务端课程和对话，草稿不冒充跨端同步", async ({ page, browser }) => {
  const { notebook, email, password } = await enter(page);
  await page.getByLabel("学习目标输入").fill("请用一个生活中的例子解释栈，暂时不用出题。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("小知回答").last()).toContainText(/\S/);
  await page.getByLabel("学习目标输入").fill("只在本机的未发送草稿");
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } });
  try {
    const other = await context.newPage();
    const base = new URL(page.url()).origin;
    expect((await context.request.post(`${base}/api/auth/login`, { data: { email, password } })).ok()).toBe(true);
    await other.goto(base, { waitUntil: "domcontentloaded" });
    const skip = other.getByRole("button", { name: "跳过引导", exact: true });
    await expect(skip).toBeVisible();
    await skip.click();
    await expect(other.locator(".notebook-topbar")).toContainText(notebook.title);
    await expect(other.getByLabel("小知回答").last()).toContainText(/\S/);
    await expect(other.getByLabel("学习目标输入")).toHaveValue("");
  } finally { await context.close(); }
});

test("旧测评恢复信息不能覆盖最后主动选择的课程和草稿", async ({ page }) => {
  const { notebook } = await enter(page);
  const other = await (await page.request.post("/api/notebooks", { data: { title: "后来选择的课程" } })).json();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "学习来源", exact: true }).click();
  await page.locator(".notebook-mobile-sheet").getByLabel("切换科目书本").selectOption(other.id);
  await expect(page.locator(".notebook-topbar")).toContainText(other.title);
  await page.getByLabel("学习目标输入").fill("后来这门课的未发送答案");
  // A completed assessment leaves this persistent resume record in the API.
  await page.route("**/api/onboarding", async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), resume: {
      notebook_id: notebook.id, assessment_id: "previous-assessment", phase: "plan",
    } } });
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".notebook-topbar")).toContainText(other.title);
  await expect(page.getByLabel("学习目标输入")).toHaveValue("后来这门课的未发送答案");
});

test("触屏设备回车换行，不误发未写完的答案", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  try {
    const page = await context.newPage();
    const base = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:13000";
    await page.goto(base, { waitUntil: "domcontentloaded" });
    const email = `responsive-touch-${Date.now()}@example.test`;
    await context.request.post(`${base}/api/auth/register`, { data: { email, password: "Responsive-Acceptance-2026!", name: "触屏验收" } });
    await context.request.post(`${base}/api/onboarding`, { data: { skipped: true } });
    await context.request.post(`${base}/api/notebooks`, { data: { title: "触屏课程" } });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "跳过引导", exact: true }).click();
    const input = page.getByLabel("学习目标输入", { exact: true });
    await input.fill("第一步，先明确条件。");
    await input.press("Enter");
    await expect(input).toHaveValue("第一步，先明确条件。\n");
    await expect(page.getByLabel("小知回答")).toHaveCount(0);
    await assertFit(page);
  } finally { await context.close(); }
});

test("会话过期后同页换账号不残留上一账号课程、消息和草稿", async ({ page, browser }) => {
  const { password } = await enter(page);
  await page.getByLabel("学习目标输入").fill("这是一号账号的私有学习消息，请解释栈。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByLabel("小知回答").last()).toContainText(/\S/);
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  const otherContext = await browser.newContext();
  const email = `responsive-switch-${Date.now()}@example.test`;
  const base = new URL(page.url()).origin;
  try {
    expect((await otherContext.request.post(`${base}/api/auth/register`, { data: { email, password, name: "第二账号" } })).status()).toBe(201);
    await otherContext.request.post(`${base}/api/onboarding`, { data: { skipped: true } });
    await otherContext.request.post(`${base}/api/notebooks`, { data: { title: "第二账号独立课程" } });
  } finally { await otherContext.close(); }
  await page.route("**/api/chat", route => route.fulfill({ status: 401, contentType: "application/json", body: "{}" }));
  await page.getByLabel("学习目标输入").fill("触发验收用过期会话");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await page.unroute("**/api/chat");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录并继续", exact: true }).click();
  await page.getByRole("button", { name: "跳过引导", exact: true }).click();
  await expect(page.locator(".notebook-topbar")).toContainText("第二账号独立课程");
  await expect(page.getByLabel("小知回答")).toHaveCount(0);
  await expect(page.getByLabel("学习目标输入")).toHaveValue("");
  await expect(page.getByText("这是一号账号的私有学习消息，请解释栈。", { exact: true })).toHaveCount(0);
});
