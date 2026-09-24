import { test, expect } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

test.use({ viewport: { width: 1440, height: 1000 }, actionTimeout: 20_000 });

// Opt in only through scripts/acceptance.py live. Uses synthetic fixtures, never user uploads.
test("生产固定样本：上传、问答续接、六级资料生成与归档", async ({ page }, info) => {
  test.setTimeout(1_050_000);
  expect(process.env.PLAYWRIGHT_REAL_MODE).toBe("1");
  const expected = process.env.ACCEPTANCE_EXPECTED_COMMIT;
  expect(expected).toMatch(/^[0-9a-f]{40}$/);
  const evidence: any = { started: new Date().toISOString(), expected, cases: [], resources: [], warnings: [],
    limitations: ["样本为原创测试资料，不是反馈截图的原文件", "不验收静态英语音色自然度或视频成片", "文字正确性仍需阅读保存的正文"] };
  const safe = (e: unknown) => String(e).split("Call log:")[0].slice(0, 900);
  async function protectedCall<T>(action: () => Promise<T>): Promise<T> {
    try { return await action(); } catch (e) { throw Error(safe(e)); }
  }
  const request = {
    get: (...args: Parameters<typeof page.request.get>) => protectedCall(() => page.request.get(...args)),
    post: (...args: Parameters<typeof page.request.post>) => protectedCall(() => page.request.post(...args)),
  };
  async function get(url: string) {
    const r = await request.get(url); expect(r.status(), url).toBe(200); return r.json();
  }
  async function post(url: string, data: any) {
    try {
      const r = await request.post(url, { data, timeout: 240_000 });
      if (!r.ok()) throw Error(url + " HTTP " + r.status() + " " + safe(await r.text()));
      return r.json();
    } catch (e) { throw Error(safe(e)); }
  }
  async function stream(url: string, data: any) {
    const start = Date.now();
    try {
      const r = await request.post(url, { data, timeout: 240_000 });
      expect(r.ok(), url + " " + r.status()).toBe(true);
      const events = (await r.text()).split("\n").filter(s => s.startsWith("data: ")).map(s => JSON.parse(s.slice(6)));
      expect(events.filter(e => e.type === "error")).toEqual([]);
      expect(events.some(e => e.type === "done")).toBe(true);
      return { events, seconds: (Date.now() - start) / 1000 };
    } catch (e) { throw Error(safe(e)); }
  }
  async function check(name: string, fn: () => Promise<void>) {
    const start = Date.now();
    console.log("[LIVE START]", name);
    try { await fn(); evidence.cases.push({ name, passed: true, seconds: (Date.now()-start)/1000 }); }
    catch (e) { evidence.cases.push({ name, passed: false, error: safe(e) }); }
    await writeFile(info.outputPath("live-evidence.json"), JSON.stringify(evidence, null, 2));
    console.log("[LIVE RESULT]", name, evidence.cases.at(-1).passed);
  }
  async function book(title: string, kind?: string) {
    const b = await post("/api/notebooks", { user_id: "session_user", title });
    if (kind) await post(`/api/notebooks/${b.id}/learning/prepare`, { title, course_key: kind, source_ids: [] });
    return b;
  }
  async function upload(b: any, filename: string, expectedText: RegExp) {
    const buffer = await readFile(path.join(__dirname, "fixtures", filename));
    const r = await request.post("/api/knowledge/upload", { timeout: 180_000, multipart: {
      user_id: "session_user", notebook_id: b.id, title: filename,
      file: { name: filename, mimeType: filename.endsWith(".pdf") ? "application/pdf" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer },
    } });
    expect(r.ok(), filename + " HTTP " + r.status()).toBe(true);
    const value = await r.json();
    expect(value.source.selectable).toBe(true);
    expect(value.source.chunk_count).toBeGreaterThan(0);
    expect(value.sample.map((x: any) => x.text).join("\n")).toMatch(expectedText);
    evidence.uploads = [...(evidence.uploads || []), { filename, ...value }];
    return value.source.id as string;
  }
  async function generate(b: any, kind: string, template: string, focus: string, sources: string[] = []) {
    const prior = new Set((await get(`/api/resources?user_id=session_user&notebook_id=${b.id}`)).items.map((r: any) => r.id));
    const flow = await stream("/api/resources/generate", { user_id: "session_user", notebook_id: b.id,
      session_id: b.session_id, kinds: [kind], prompt_template: template, goal: focus,
      conversation_focus: focus, source_ids: sources, source_policy: "strict" });
    const r = (await get(`/api/resources?user_id=session_user&notebook_id=${b.id}`)).items.find((r: any) => !prior.has(r.id) && r.kind === kind);
    expect(r).toBeTruthy(); evidence.resources.push(r);
    evidence.timings = [...(evidence.timings || []), { template, seconds: flow.seconds }];
    if (r.payload.generation_details?.status === "degraded") evidence.warnings.push({ id: r.id, details: r.payload.generation_details });
    expect(r.payload.generation_mode).not.toBe("unavailable");
    expect(r.title).not.toMatch(/请带我开始|请根据/);
    return r;
  }
  try {
    evidence.healthBefore = await get("/api/health");
    expect(evidence.healthBefore.release).toBe(expected);
    expect(evidence.healthBefore.demo_mode).toBe(false);
    const signup = await request.post("/api/auth/register", { data: {
      email: `feedback-audit-${Date.now()}@example.test`, password: "Audit-Fixture-Only-2026!", name: "用户反馈验收",
    } });
    expect(signup.status()).toBe(201);
    await post("/api/onboarding", { skipped: true });
    const cet = await book("六级反馈复核", "cet6"); evidence.cetNotebook = cet.id;
    await check("六级学习指令保留真实主题", async () => {
      const flow = await stream("/api/chat", { user_id: "session_user", notebook_id: cet.id, session_id: cet.session_id,
        message: "请带我开始“词汇与语境”的第一项学习任务。给我一个可以马上作答的小问题。",
        source_ids: [], source_policy: "strict" });
      evidence.cetChat = flow;
      const saved = await get(`/api/notebooks/${cet.id}?user_id=session_user`);
      const text = saved.messages.filter((m: any) => m.role === "assistant").at(-1)?.content || "";
      expect(text.length).toBeGreaterThan(80); expect(text).not.toMatch(/二叉树|高级排序|Failed to fetch/);
    });
    await check("六级巩固测验有真实学科题目", async () => {
      const r = await generate(cet, "quiz", "quiz", "词汇与语境");
      expect(r.payload.questions.length).toBeGreaterThanOrEqual(4);
      expect(r.payload.questions.some((q: any) => /概括「|二叉树|高级排序/.test(q.stem))).toBe(false);
      expect(r.payload.questions.every((q: any) => q.stem?.trim() && q.answer?.trim())).toBe(true);
      expect(r.payload.questions.filter((q: any) => ["single", "multi"].includes(q.type))
        .every((q: any) => q.options?.length >= 2)).toBe(true);
    });
    await check("六级闪卡有实际内容", async () => {
      const r = await generate(cet, "flashcards", "flashcards", "词汇与语境");
      expect(r.payload.flashcards.cards.length).toBeGreaterThanOrEqual(3);
      expect(r.payload.generation_mode).toBe("model");
    });
    await check("对话笔记保持章节范围且改名后可读", async () => {
      const r = await generate(cet, "doc", "conversation_notes", "词汇与语境");
      await post(`/api/resources/${r.id}/rename`, { user_id: "session_user", title: "词汇学习笔记：固定流程复核" });
      const reread = (await get(`/api/resources?user_id=session_user&notebook_id=${cet.id}`)).items.find((x: any) => x.id === r.id);
      expect(reread.title).toBe("词汇学习笔记：固定流程复核");
      // Save/rename is independently observable even if the model degraded.
      expect(r.payload.generation_mode).toBe("model");
      expect(r.payload.markdown.length).toBeGreaterThan(400);
      expect(r.payload.source_evidence.length).toBeGreaterThan(0);
      expect(r.payload.source_evidence.every((x: any) => x.section_id === "vocabulary")).toBe(true);
    });
    await check("六级一图看懂生成且实际图像可读取", async () => {
      const r = await generate(cet, "doc", "one_page", "词汇与语境的记忆方法");
      const pages = r.payload.one_page_visual?.pages || [];
      expect(pages.length).toBeGreaterThan(0);
      for (const [i, image] of pages.entries()) {
        const response = await request.get("/api" + image.image_url);
        expect(response.status()).toBe(200);
        expect(response.headers()["content-type"]).toContain("image/svg+xml");
        const svg = await response.text();
        expect(svg).toContain("<svg");
        await writeFile(info.outputPath(`live-one-page-${i + 1}.svg`), svg);
      }
    });
    let eco: any;
    let ids: string[] = [];
    await check("原创 Word/PDF 上传并索引", async () => {
      eco = await book("生态学资料验收"); evidence.materialNotebook = eco.id;
      ids = [await upload(eco, "ecology.docx", /生产者/), await upload(eco, "ecology.pdf", /生产者/)];
    });
    await check("上传资料可生成独立课程", async () => {
      expect(ids).toHaveLength(2);
      evidence.materialCourse = await post(`/api/notebooks/${eco.id}/learning/prepare`, { title: "生态系统基础", course_key: "custom", source_ids: ids });
      expect(evidence.materialCourse.source_ids).toEqual(expect.arrayContaining(ids));
      expect(evidence.materialCourse.source_ids).toHaveLength(ids.length);
    });
    await check("上传资料问答可接续 B 并整理笔记", async () => {
      expect(ids).toHaveLength(2);
      await stream("/api/chat", { user_id: "session_user", notebook_id: eco.id, session_id: eco.session_id, source_ids: ids, source_policy: "strict",
        message: "根据资料解释生产者、消费者、分解者。最后问我一道选择题：分解枯叶的真菌属于什么角色？A 生产者；B 分解者；C 消费者。先不要揭晓答案。" });
      evidence.materialReply = await stream("/api/chat", { user_id: "session_user", notebook_id: eco.id, session_id: eco.session_id,
        source_ids: ids, source_policy: "strict", message: "B" });
      const saved = await get(`/api/notebooks/${eco.id}?user_id=session_user`);
      evidence.materialMessages = saved.messages;
      const text = saved.messages.filter((m: any) => m.role === "assistant").at(-1)?.content || "";
      expect(text.length).toBeGreaterThan(80); expect(text).toMatch(/分解者/);
      expect(text).not.toMatch(/未生成可用内容|Failed to fetch|离线示例/);
      await generate(eco, "doc", "conversation_notes", "生产者、消费者与分解者", ids);
    });
    await check("金融词汇、雅思 PDF、动画脚本分别解析为自身内容", async () => {
      const b = await book("格式与资料范围验收");
      await upload(b, "cfa-vocabulary.docx", /asset|资产/);
      await upload(b, "ielts-vocabulary.pdf", /accommodation|住宿/);
      await upload(b, "animation-script.docx", /五秒|徽章/);
    });
    await check("线上归档页面显示保存的新笔记", async () => {
      await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), b => b.click());
      await page.goto("/");
      await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(cet.id);
      await page.getByRole("button", { name: /^资料归档/ }).click();
      const card = page.locator("button[aria-expanded]").filter({ hasText: "词汇学习笔记：固定流程复核" });
      if (await card.getAttribute("aria-expanded") === "false") await card.click();
      await expect(card).toBeVisible();
      const body = card.locator("..").locator(".prose-spark").first();
      await expect(body).toBeVisible();
      expect(await body.evaluate(el => getComputedStyle(el).userSelect)).not.toBe("none");
      const selected = await body.evaluate(el => {
        const range = document.createRange(); range.selectNodeContents(el);
        const selection = getSelection(); selection?.removeAllRanges(); selection?.addRange(range);
        return selection?.toString() || "";
      });
      expect(selected.length).toBeGreaterThan(400);
      await page.evaluate(() => getSelection()?.removeAllRanges());
      await page.screenshot({ path: info.outputPath("live-notes.png"), fullPage: true });
    });
    evidence.healthAfter = await get("/api/health");
    expect(evidence.healthAfter.release).toBe(expected);
    expect(evidence.cases.filter((c: any) => !c.passed), "Read live-evidence.json; failures are not silently skipped").toEqual([]);
  } finally {
    evidence.finished = new Date().toISOString();
    await writeFile(info.outputPath("live-evidence.json"), JSON.stringify(evidence, null, 2));
  }
});
