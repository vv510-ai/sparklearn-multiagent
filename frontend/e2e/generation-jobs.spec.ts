import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

test.use({ viewport: { width: 1440, height: 1000 } });
const live = process.env.PLAYWRIGHT_REAL_MODE === "1";
for (const sample of [
  { topic: "高等数学", goal: "用一图看懂展示高等数学整体框架，包括极限、导数、积分。", kind: "resource" },
  { topic: "大学物理", goal: "用一图看懂展示大学物理整体框架，包括力学、热学、电磁学。", kind: "resource" },
  { topic: "英语学习", goal: "用两句话解释英语一般现在时和一般过去时的区别。", kind: "chat" },
]) test(`${sample.topic}：关闭等待、刷新、幂等与账户隔离`, async ({ page, browser }, info) => {
  test.setTimeout(540_000);
  test.skip(!live && process.env.GENERATION_JOBS_ENABLED !== "true", "Requires the durable worker test mode");
  const signup = await page.request.post("/api/auth/register", { data: {
    email: `durable-${Date.now()}-${sample.kind}@example.test`, password: "Durable-Fixture-2026!", name: "任务恢复验收",
  } });
  expect(signup.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBe(true);
  const book = await (await page.request.post("/api/notebooks", { data: { user_id: "session_user", title: sample.topic } })).json();
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), async b => { await b.click(); });
  await page.goto("/");
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(book.id);
  const requestId = crypto.randomUUID();
  const body = sample.kind === "chat" ? {
    user_id: "session_user", notebook_id: book.id, request_id: requestId, message: sample.goal, source_policy: "supplement",
  } : {
    user_id: "session_user", notebook_id: book.id, request_id: requestId, goal: sample.goal,
    kinds: ["doc"], prompt_template: "one_page", source_policy: "supplement", source_ids: [],
  };
  const path = sample.kind === "chat" ? "/api/chat" : "/api/resources/generate";
  const submitThenDisconnect = () => page.evaluate(async ({ body, path }) => {
    const controller = new AbortController();
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal });
    if (!response.ok) throw new Error(`submit ${response.status}: ${await response.text()}`);
    const reader = response.body!.getReader(); const decoder = new TextDecoder(); let pending = "";
    try {
      for (;;) {
        const r = await reader.read(); if (r.done) throw new Error("stream ended before job acknowledgement");
        pending += decoder.decode(r.value, { stream: true });
        for (const frame of pending.split("\n\n").slice(0, -1)) {
          const line = frame.split("\n").find(x => x.startsWith("data: "));
          if (line) { const ev = JSON.parse(line.slice(6)); if (ev.job_id) return ev.job_id as string; }
        }
      }
    } finally { controller.abort(); }
  }, { body, path });
  const jobId = await submitThenDisconnect();
  expect(await submitThenDisconnect()).toBe(jobId);
  await page.reload();
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(book.id);
  let job: any;
  await expect.poll(async () => {
    job = await (await page.request.get(`/api/jobs/${jobId}`)).json();
    return ["completed", "failed", "needs_review"].includes(job.status);
  }, { timeout: 440_000, intervals: [2000, 4000] }).toBe(true);
  const events = await (await page.request.get(`/api/jobs/${jobId}/events`)).text();
  await writeFile(info.outputPath("job-evidence.json"), JSON.stringify({ sample, job, events }, null, 2));
  expect(job.status, job.detail).toBe("completed");
  const listing = await (await page.request.get(`/api/jobs?notebook_id=${book.id}`)).json();
  expect(listing.items).toHaveLength(1);
  await page.getByText("最近任务", { exact: true }).click();
  await page.getByRole("button", { name: "查看结果", exact: true }).click();
  if (sample.kind === "chat") {
    await expect(page.locator('[aria-label="小知回答"]').last()).toContainText(/现在|过去/);
    const detail = await (await page.request.get(`/api/notebooks/${book.id}?user_id=session_user`)).json();
    expect(detail.messages.filter((m: any) => m.role === "user")).toHaveLength(1);
    expect(detail.messages.filter((m: any) => m.role === "assistant")).toHaveLength(1);
  } else {
    const saved = await (await page.request.get(`/api/resources?user_id=session_user&notebook_id=${book.id}`)).json();
    const resource = saved.items.find((r: any) => r.payload.template === "one_page");
    expect(resource).toBeTruthy();
    await writeFile(info.outputPath("resource.json"), JSON.stringify(resource, null, 2));
    if (live) {
      const pages = resource.payload.one_page_visual.pages;
      expect(pages.length).toBeGreaterThan(0);
      for (const image of pages) { expect(image.provider).toBe("xiaoyunque"); expect(image.image_status).toBe("ready"); }
      const card = page.getByRole("button", { name: new RegExp(resource.title) }).first();
      if (await card.getAttribute("aria-expanded") === "false") await card.click();
      const image = page.getByRole("img", { name: /^一图看懂/ }).first();
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(500);
      await image.screenshot({ path: info.outputPath("visible-image.png") });
    }
  }
  const other = await browser.newContext({ baseURL: info.project.use.baseURL });
  try {
    const r = await other.request.post("/api/auth/register", { data: { email: `other-${Date.now()}@example.test`, password: "Durable-Fixture-2026!", name: "隔离验收" } });
    expect(r.status()).toBe(201);
    expect((await other.request.get(`/api/jobs/${jobId}`)).status()).toBe(404);
    expect((await other.request.get(`/api/jobs/${jobId}/events`)).status()).toBe(404);
  } finally { await other.close(); }
  await page.screenshot({ path: info.outputPath("result.png"), fullPage: true });
});

test("两个账户同时提问：分别完成且答案不串号", async ({ browser }, info) => {
  test.setTimeout(240_000);
  test.skip(!live && process.env.GENERATION_JOBS_ENABLED !== "true", "Requires the durable worker test mode");
  const contexts = await Promise.all([0, 1].map(() => browser.newContext({ baseURL: info.project.use.baseURL })));
  try {
    const books = await Promise.all(contexts.map(async (ctx, i) => {
      const signup = await ctx.request.post("/api/auth/register", { data: { email: `concurrent-${i}-${Date.now()}@example.test`, password: "Durable-Fixture-2026!", name: "并发验收" } });
      expect(signup.status()).toBe(201);
      return (await ctx.request.post("/api/notebooks", { data: { user_id: "session_user", title: i ? "英语学习" : "高等数学" } })).json();
    }));
    const results = await Promise.all(contexts.map(async (ctx, i) => {
      const res = await ctx.request.post("/api/chat", { timeout: 210_000, data: {
        user_id: "session_user", notebook_id: books[i].id, request_id: crypto.randomUUID(), source_policy: "supplement",
        message: i ? "用两句话解释英语一般过去时，并给一句例句。" : "用两句话解释数学中导数的含义。",
      } });
      expect(res.ok()).toBe(true);
      const events = (await res.text()).split("\n").filter(x => x.startsWith("data: ")).map(x => JSON.parse(x.slice(6)));
      expect(events.filter(e => e.type === "error")).toEqual([]);
      expect(events.some(e => e.type === "done")).toBe(true);
      const id = events.find(e => e.job_id).job_id;
      expect((await (await ctx.request.get(`/api/jobs/${id}`)).json()).status).toBe("completed");
      return { id, events };
    }));
    expect(results[0].id).not.toBe(results[1].id);
    for (const i of [0, 1]) expect((await contexts[i].request.get(`/api/jobs/${results[1 - i].id}`)).status()).toBe(404);
    if (live) {
      expect(results[0].events.filter(e => e.type === "token").map(e => e.delta).join("")).toContain("导数");
      expect(results[1].events.filter(e => e.type === "token").map(e => e.delta).join("")).toContain("过去");
    }
    await writeFile(info.outputPath("concurrent-evidence.json"), JSON.stringify(results, null, 2));
  } finally { await Promise.all(contexts.map(c => c.close())); }
});
