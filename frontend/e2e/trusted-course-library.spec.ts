import { expect, test } from "@playwright/test";
import { registerLearner } from "./intake-helpers";

test("无上传进入十课课程，练习、代码和阅读记录可恢复", async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await registerLearner(page, "course-library");
  await page.getByRole("link", { name: "没有资料也能学：打开课程目录 →" }).click();
  await expect(page.getByRole("heading", { name: "选一门课，直接开始学。" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Python 零基础入门" })).toBeVisible();
  await page.getByRole("button", { name: "开始第一课" }).click();
  await expect(page.getByRole("heading", { name: "运行第一个程序" })).toBeVisible();
  await expect(page.getByRole("region", { name: "本课新题练习" })).toBeVisible();
  await page.getByText("查看本课依据：Python 官方教程", { exact: true }).click();
  await expect(page.locator(".library-sources")).toContainText("3.14.7");
  await page.getByText("查看本课依据：Python 官方教程", { exact: true }).click();
  await page.getByLabel("记录你的代码、运行结果和解释").fill("unsaved draft");
  await page.getByRole("button", { name: "我已阅读，记录进度" }).click();
  await expect(page.getByRole("button", { name: "已记录阅读，再次确认" })).toBeEnabled();
  await expect(page.getByLabel("记录你的代码、运行结果和解释")).toHaveValue("unsaved draft");
  await page.getByRole("radio", { name: /^A\./ }).check();
  await page.getByRole("button", { name: "提交新题答案" }).click();
  await expect(page.locator(".library-feedback")).toContainText("这道题答对了");
  await expect(page.getByLabel("记录你的代码、运行结果和解释")).toHaveValue("unsaved draft");
  await expect(page.getByRole("region", { name: "本课新题练习" })).toContainText("隔日新题");
  await page.getByLabel("记录你的代码、运行结果和解释").fill("print('CS101')\nprint(7 * 4)\n运行输出：CS101 和 28");
  await page.getByRole("checkbox", { name: "有两个 print 调用" }).check();
  await page.getByRole("button", { name: "保存代码与自查记录" }).click();
  await expect(page.getByRole("status").filter({ hasText: "代码与自查记录已保存" })).toBeVisible();
  const savedURL = page.url();
  await page.reload();
  await expect(page.getByRole("heading", { name: "运行第一个程序" })).toBeVisible();
  await expect(page.getByLabel("记录你的代码、运行结果和解释")).toHaveValue(/CS101/);
  await expect(page.locator(".library-feedback")).toContainText("自述独立作答");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("heading", { name: "运行第一个程序" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("course-desktop.png"), fullPage: true });
  for (const width of [834, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (width === 390) {
      await page.getByRole("combobox", { name: "课程目录", exact: true }).selectOption("values");
      await expect(page.getByRole("heading", { name: "变量、类型与输入" })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath("course-mobile.png"), fullPage: true });
    }
  }
  await page.goto(savedURL);
  await expect(page.getByRole("heading", { name: "运行第一个程序" })).toBeVisible();
  await expect(page.getByLabel("记录你的代码、运行结果和解释")).toHaveValue(/CS101/);
  // Production acceptance also exercises the actual configured model and release RAG.
  if (process.env.PLAYWRIGHT_REAL_MODE === "1") {
    expect(process.env.ACCEPTANCE_EXPECTED_COMMIT).toMatch(/^[0-9a-f]{40}$/);
    const user = await (await page.request.get("/api/auth/me")).json();
    const catalog = await (await page.request.get("/api/library")).json();
    const current = catalog.studies.find((x: { release_id: string }) => x.release_id === catalog.items[0].release_id);
    const response = await page.request.post("/api/chat", { timeout: 180_000, data: {
      user_id: user.id, notebook_id: current.notebook_id, source_policy: "strict",
      message: "请依据本课 Python 官方教程说明：函数没有 return 时返回什么？给一个简短例子，并引用教材。",
    } });
    expect(response.ok()).toBeTruthy();
    const stream = await response.text();
    const events = stream.split("\n").filter(line => line.startsWith("data: ")).map(line => JSON.parse(line.slice(6)));
    expect(events.some(e => e.type === "done")).toBeTruthy();
    expect(events.filter(e => e.type === "error")).toEqual([]);
    const answer = events.filter(e => e.type === "token").map(e => e.delta || "").join("");
    expect(answer).toContain("None");
    const evidence = events.filter(e => e.type === "citations" && e.agent === "tutor").flatMap(e => e.evidence || []);
    expect(evidence.some(e => e.course_release_id === current.release_id && e.url.startsWith("https://docs.python.org/"))).toBeTruthy();
    await testInfo.attach("course-answer", { body: JSON.stringify({ release: current.release_id, answer, evidence }, null, 2), contentType: "application/json" });
  }
  expect(errors).toEqual([]);
});
