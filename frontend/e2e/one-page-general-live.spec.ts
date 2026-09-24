import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

test.use({ viewport: { width: 1440, height: 1000 }, actionTimeout: 20_000 });
// Real provider acceptance, opt-in under the deployment lease. All accounts and
// uploaded notes below are synthetic; never read an existing learner's data.
const grammar = `# 词类
名词用来指称人、事物或概念；动词表达动作或状态；形容词描述名词。
# 句子主干
主语和谓语构成句子主干，宾语通常承接及物动词的动作；修饰语补充信息。
# 时态与语境
时态结合语境表达时间关系。一般现在时可表达习惯；一般过去时常表达过去发生的事情。`;
const cases = [
  { id: "math", old: "大学英语六级", question: "嗯你可以用一图看懂的功能，帮我把高数大学高数的整体框架构画出来吗？", topic: /高数|高等数学/, concepts: [/极限/, /导数|微分/, /积分/] },
  { id: "physics", old: "高等数学", question: "大学物理的整体框架是什么？", topic: /物理/, concepts: [/力学|运动/, /热/, /电磁|电场/], button: true },
  { id: "grammar", old: "英语学习", question: "英语语法中词类、句子主干和时态怎样联系？", topic: /英语|语法/, concepts: [/词类|名词/, /主语|主干/, /时态/], material: grammar, button: true },
  { id: "cs", old: "高等数学", question: "请用一图看懂展示计算机科学的整体框架。", topic: /计算机|CS/, concepts: [/算法/, /系统|硬件/, /网络/] },
];

for (const sample of cases) test(`真实小云雀：${sample.id} 跨课程生成并显示图片`, async ({ page }, info) => {
  test.setTimeout(540_000);
  expect(process.env.PLAYWRIGHT_REAL_MODE).toBe("1");
  const health = await (await page.request.get("/api/health")).json();
  expect(health.demo_mode).toBe(false);
  expect(health.release).toBe(process.env.ACCEPTANCE_EXPECTED_COMMIT);
  const signup = await page.request.post("/api/auth/register", { data: {
    email: `one-page-${sample.id}-${Date.now()}@example.test`, password: "OnePage-Fixture-2026!", name: "一图多学科验收",
  } });
  expect(signup.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBe(true);
  const book = await (await page.request.post("/api/notebooks", { data: { user_id: "session_user", title: sample.old } })).json();
  if (sample.id === "math") {
    const prepared = await page.request.post(`/api/notebooks/${book.id}/learning/prepare`, {
      data: { title: sample.old, course_key: "cet6", source_ids: [] }, timeout: 180_000,
    });
    expect(prepared.ok()).toBe(true);
  }
  let sourceId = "";
  if (sample.material) {
    const upload = await page.request.post("/api/knowledge/upload", { timeout: 180_000, multipart: {
      user_id: "session_user", notebook_id: book.id, title: "课堂分节笔记",
      file: { name: "chapters.md", mimeType: "text/markdown", buffer: Buffer.from(sample.material) },
    } });
    expect(upload.ok()).toBe(true);
    const body = await upload.json();
    expect(body.source.selectable).toBe(true);
    sourceId = body.source.id;
  }
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), async button => { await button.click(); });
  await page.goto("/");
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(book.id);
  await page.getByTitle("对话选项", { exact: true }).click();
  await page.getByRole("combobox", { name: "回答依据" }).selectOption(sample.material ? "strict" : "supplement");
  await page.keyboard.press("Escape");
  await page.getByLabel("学习目标输入", { exact: true }).fill(sample.question);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator('[aria-label="小知回答"]').last()).toBeVisible();
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 360_000 });
  if (sample.button) {
    const response = page.waitForResponse(r => r.url().endsWith("/api/resources/generate") && r.request().method() === "POST", { timeout: 180_000 });
    await page.getByRole("button", { name: /^一图看懂/ }).click();
    expect((await response).status()).toBe(200);
    await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 360_000 });
  }
  const saved = await (await page.request.get(`/api/resources?user_id=session_user&notebook_id=${book.id}`)).json();
  const resource = saved.items.find((r: any) => r.payload.template === "one_page");
  const summary = await page.locator('[aria-label="小知回答"]').last().innerText();
  await writeFile(info.outputPath("evidence.json"), JSON.stringify({ sample, book: book.id, sourceId, resource, summary, health }, null, 2));
  expect(resource).toBeTruthy();
  expect(resource.title).toMatch(sample.topic);
  expect(resource.payload.generation_mode).toBe("model");
  expect(resource.payload.image_attempted).toBe(true);
  expect(resource.payload.topic_verification.status).toBe("matched");
  for (const concept of sample.concepts) expect(resource.payload.markdown).toMatch(concept);
  if (sample.id === "math") expect(resource.payload.markdown).not.toMatch(/听力|六级|CET-6/);
  if (sourceId) {
    expect(resource.payload.source_evidence.length).toBeGreaterThan(0);
    expect(resource.payload.source_evidence.every((c: any) => c.source_id === sourceId)).toBe(true);
  }
  const card = page.getByRole("button", { name: new RegExp(resource.title) }).first();
  if (await card.getAttribute("aria-expanded") === "false") await card.click();
  const pages = resource.payload.one_page_visual.pages;
  expect(pages.length).toBeGreaterThan(0);
  const images = page.getByRole("img", { name: /^一图看懂/ });
  await expect(images).toHaveCount(pages.length);
  for (let i = 0; i < pages.length; i++) {
    expect(pages[i].provider).toBe("xiaoyunque");
    expect(pages[i].image_status).toBe("ready");
    const image = images.nth(i);
    await image.scrollIntoViewIfNeeded();
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(500);
    await image.evaluate(async el => { await (el as HTMLImageElement).decode(); });
    await image.screenshot({ path: info.outputPath(`visible-${i + 1}.png`) });
    const raw = await page.request.get(`/api${pages[i].image_url}`);
    expect(raw.ok()).toBe(true);
    expect(raw.headers()["content-type"]).toMatch(/image\/(png|jpeg|webp)/);
    await writeFile(info.outputPath(`original-${i + 1}.png`), await raw.body());
    if (pages[i].verification.status !== "passed") {
      expect(pages[i].verification.issues.length).toBeGreaterThan(0);
      expect(summary).toContain("未确认");
    }
  }
  await page.screenshot({ path: info.outputPath("result.png"), fullPage: true });
});

for (const source of ["empty", "unrelated"]) test(`严格资料边界：${source} 不调用生图`, async ({ request }, info) => {
  test.setTimeout(300_000);
  expect(process.env.PLAYWRIGHT_REAL_MODE).toBe("1");
  const signup = await request.post("/api/auth/register", { data: {
    email: `one-page-boundary-${source}-${Date.now()}@example.test`, password: "OnePage-Fixture-2026!", name: "一图资料边界验收",
  } });
  expect(signup.status()).toBe(201);
  const book = await (await request.post("/api/notebooks", { data: { user_id: "session_user", title: "课程测试" } })).json();
  let sourceIds: string[] = [];
  if (source === "unrelated") {
    const r = await request.post("/api/knowledge/upload", { multipart: { user_id: "session_user", notebook_id: book.id,
      file: { name: "grammar.md", mimeType: "text/markdown", buffer: Buffer.from(grammar) }, title: "语法课堂" } });
    expect(r.ok()).toBe(true); sourceIds = [(await r.json()).source.id];
  }
  const r = await request.post("/api/resources/generate", { timeout: 240_000, data: {
    user_id: "session_user", notebook_id: book.id, kinds: ["doc"], prompt_template: "one_page",
    goal: "只依据所选资料，用一图看懂讲解有机化学的整体框架", source_ids: sourceIds, source_policy: "strict",
  } });
  expect(r.ok()).toBe(true);
  const events = (await r.text()).split("\n").filter(line => line.startsWith("data: ")).map(line => JSON.parse(line.slice(6)));
  expect(events.some(e => e.type === "done")).toBe(true);
  const resource = events.find(e => e.type === "resource")?.resource;
  await writeFile(info.outputPath("boundary.json"), JSON.stringify({ source, resource, events }, null, 2));
  expect(resource.payload.generation_mode).toBe("unavailable");
  expect(resource.payload.image_attempted).toBe(false);
  expect(resource.payload.one_page_visual).toBeUndefined();
  expect(["source_scope_empty", "topic_mismatch"]).toContain(resource.payload.blocked_reason);
});
