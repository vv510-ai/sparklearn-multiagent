import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

test.use({ hasTouch: true });

async function student(page: Page) {
  if (process.env.PLAYWRIGHT_REAL_MODE === "1") {
    const health = await (await page.request.get("/api/health")).json();
    expect(health.release).toBe(process.env.ACCEPTANCE_EXPECTED_COMMIT);
    expect(health.demo_mode).toBe(false);
  }
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("六级学生流程验收");
  await page.getByPlaceholder("you@example.com").fill(`cet6-student-${randomUUID()}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Cet6-Student-2026!");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程" });
  await expect(dialog).toBeVisible();
  const courses = await (await page.request.get("/api/notebooks/learning/catalogue")).json();
  await dialog.getByRole("radio", { name: courses.items.find((c: { id: string }) => c.id === "cet6").title, exact: true }).check();
  await expect(dialog).not.toContainText("28 个学习单元");
  const created = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/notebooks");
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  const notebook = (await (await created).json()).id;
  await expect(page.getByRole("heading", { name: "六级备考中心" })).toBeVisible();
  await expect(page.getByText(/备考参考.*28/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "继续课程学习" })).toHaveCount(0);
  return { notebook, base: `/api/notebooks/${notebook}/cet6` };
}

async function pane(page: Page, source = false) {
  const tabs = page.getByRole("group", { name: "原卷与作答切换" });
  const button = tabs.getByRole("button", { name: source ? "阅读原卷" : /我的作答|结果与解析/ });
  if (await button.isVisible()) await button.click();
}

test("词表覆盖进度、背词顺序与词族分组保存，备考入口合并", async ({ page }, info) => {
  await page.setViewportSize({ width: 1500, height: 980 });
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const { notebook, base } = await student(page);
  const nav = page.getByRole("navigation", { name: "六级学习入口" });
  await expect(nav.getByRole("button", { name: "考试与目标", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("button", { name: "备考建议", exact: true })).toHaveCount(1);
  await nav.getByRole("button", { name: "背单词", exact: true }).click();
  const coverage = page.getByRole("region", { name: "大纲词表学习进度" });
  await expect(coverage).toContainText("8010 个已学");
  await expect(page.getByRole("progressbar", { name: "完整备考词表进度", exact: true })).toHaveAttribute("value", "0");
  let plan = await (await page.request.get(base + "/word-plan")).json();
  expect(plan.word_order).toBe("priority");
  const all = await (await page.request.get(base + "/words")).json();
  expect(all.items.every((item: {level: string}) => item.level === "cet6")).toBe(true);
  await page.getByRole("button", { name: "背词设置", exact: true }).click();
  await page.getByRole("combobox", { name: "背词顺序", exact: true }).selectOption("family");
  await page.getByLabel("每日新词数", { exact: true }).fill("5");
  await page.getByRole("button", { name: "保存背词设置", exact: true }).click();
  await expect(page.locator(".cet6-daily-plan")).toContainText("学习方式：词族一起背");
  await page.reload();
  await expect(page.locator(".cet6-daily-plan")).toContainText("学习方式：词族一起背");
  await expect(page.getByRole("combobox", { name: "词表排序", exact: true })).toHaveValue("family");
  await page.getByLabel("搜索单词或派生词", { exact: true }).fill("able");
  const able = page.locator(".cet6-family-heading").filter({ has: page.locator("strong", { hasText: /^able$/ }) });
  await expect(able).toContainText("词族");
  await able.getByRole("button", { name: "查看整个词族", exact: true }).click();
  await expect(page.locator(".cet6-word-row > button")).toHaveCount(2);
  await expect(page.locator(".cet6-word-list")).toContainText("ability");
  await page.screenshot({ path: info.outputPath("vocabulary-family-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "返回全部词表", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await coverage.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("vocabulary-coverage-mobile.png") });
  await page.getByRole("button", { name: /开始 \/ 继续新词/ }).click();
  await page.getByRole("button", { name: "翻面看释义", exact: true }).click();
  await page.getByRole("button", { name: /^想起来了/ }).click();
  await expect(page.getByRole("region", { name: "有限词卡练习" })).toContainText("1 / 5");
  await page.getByRole("button", { name: "暂停，返回背词", exact: true }).click();
  await expect(page.getByRole("progressbar", { name: "完整备考词表进度", exact: true })).toHaveAttribute("value", "1");
  await page.getByRole("button", { name: "背词设置", exact: true }).click();
  await page.getByRole("combobox", { name: "背词顺序", exact: true }).selectOption("random");
  await page.getByRole("button", { name: "保存背词设置", exact: true }).click();
  plan = await (await page.request.get(base + "/word-plan")).json();
  await page.reload();
  const restored = await (await page.request.get(base + "/word-plan")).json();
  expect(restored.new_ids).toEqual(plan.new_ids);
  expect(restored.coverage.learned).toBe(1);
  expect(restored.word_order).toBe("random");
  const profile = await (await page.request.get(base)).json();
  expect((await page.request.post(base + "/preferences", { data: { revision: profile.revision,
    preferences: { ...profile.preferences, target_score: 520, exam_date: "2026-12-12" } } })).ok()).toBe(true);
  await page.goto(`/?notebook=${notebook}&cet6=examinfo`);
  await expect(page.getByRole("heading", { name: "你的六级备考建议", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "当前备考目标" })).toContainText("目标 520 分");
  await expect(page).toHaveURL(/cet6=advice/);
  await page.getByRole("region", { name: "当前备考目标" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("merged-advice-goal-mobile.png") });
  await page.getByText("考试说明与成绩要求", { exact: true }).click();
  await expect(page.getByText("报考资格", { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("merged-advice-mobile.png"), fullPage: true });
  await nav.getByRole("button", { name: "今天", exact: true }).click();
  await expect(page.locator(".cet6-today")).toContainText("目标 520 分");
  await expect(page.locator(".cet6-today")).not.toContainText("目标还未填写");
  expect(errors).toEqual([]);
});

test("学生手机五词一轮：翻面、真实触屏滑动、刷新续学并到点停止", async ({ page, context }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { base } = await student(page);
  await page.locator(".cet6-main-nav").getByRole("button", { name: "背单词", exact: true }).click();
  await page.getByRole("button", { name: /开始 \/ 继续新词/ }).click();
  const round = page.getByRole("region", { name: "有限词卡练习" });
  await expect(round).toContainText("0 / 5");
  const roundId = new URL(page.url()).searchParams.get("cet6_round")!;
  const snapshot = await (await page.request.get(base + "/word-rounds/" + encodeURIComponent(roundId))).json();
  expect(new Set(snapshot.items.map((i: { entry_id: string }) => i.entry_id)).size).toBe(5);
  const client = await context.newCDPSession(page);
  const words = new Set<string>();
  for (let i = 0; i < 5; i++) {
    await expect(page.getByRole("button", { name: "翻面看释义", exact: true })).toBeEnabled();
    words.add((await page.locator(".word-flash-face h3").textContent())!);
    expect(await page.locator(".word-flash-face h3").evaluate(e => parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(36);
    if (i === 0) {
      await page.getByLabel("发音口音", { exact: true }).selectOption("en-GB");
      await page.getByText("发音来源与声音", { exact: true }).click();
      await expect(page.locator(".word-pronunciation")).toContainText("本站合成音频");
      await expect(page.locator(".word-pronunciation a")).toHaveAttribute("href", /dictionary.cambridge.org/);
    }
    await page.getByRole("button", { name: "翻面看释义", exact: true }).click();
    // Raw CDP gestures do not wait for the reveal request like Playwright clicks do.
    await expect(page.getByRole("button", { name: /^想起来了/ })).toBeEnabled();
    if (i === 0) {
      await page.locator(".word-flash-face h3").scrollIntoViewIfNeeded();
      const box = (await page.locator(".word-flash-face h3").boundingBox())!;
      const x = box.x + box.width / 2 - 45, y = box.y + box.height / 2;
      await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
      await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + 100, y }] });
      await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    } else await page.getByRole("button", { name: /^想起来了/ }).click();
    await expect(round).toContainText(`${i + 1} / 5`);
    if (i === 1) {
      await page.reload();
      await expect(round).toContainText("2 / 5");
      await expect(page.getByLabel("发音口音", { exact: true })).toHaveValue("en-GB");
      await page.screenshot({ path: info.outputPath("student-word-mobile.png"), fullPage: true });
    }
  }
  expect(words.size).toBe(5);
  await expect(page.getByRole("heading", { name: "这一轮完成了" })).toBeVisible();
  await expect(page.getByRole("group", { name: "单词闪卡" })).toHaveCount(0);
  await page.reload(); await expect(round).toContainText("5 / 5");
  await page.screenshot({ path: info.outputPath("student-round-finished.png"), fullPage: true });
  await page.getByRole("button", { name: "完成，回到背词", exact: true }).click();
  await expect(page.getByRole("button", { name: /开始 \/ 继续到期复习/ })).toBeVisible();
  const plan = await (await page.request.get(base + "/word-plan")).json();
  expect(plan.new_done).toBe(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("三类阅读独立保存，Word 与 PDF 跨年份可答，原解析可定位", async ({ page }, info) => {
  test.setTimeout(300000);
  await page.setViewportSize({ width: 1500, height: 980 });
  const { notebook, base } = await student(page);
  const catalogue = await (await page.request.get(base + "/exams")).json();
  for (const kind of ["reading_cloze", "reading_matching", "reading_careful", "writing", "translation"]) expect(catalogue.items.filter((p: { counts: Record<string, number> }) => p.counts[kind]).length).toBe(15);
  const cases = [
    { paper: "cet6-2024-06-2", kind: "reading_matching", number: 45, options: 0 },
    { paper: "cet6-2025-12-2", kind: "reading_matching", number: 36, options: 0 },
    { paper: "cet6-2024-12-3", kind: "reading_careful", number: 46, options: 4 },
    { paper: "cet6-2026-06-3", kind: "reading_cloze", number: 26, options: 15 },
  ];
  for (const c of cases) {
    await page.goto(`/?notebook=${notebook}&cet6=exams&exam_kind=${c.kind}&exam_paper=${c.paper}`);
    await expect(page.locator(".exam-source-text")).not.toBeEmpty({ timeout: 60000 });
    await pane(page);
    await page.getByRole("navigation", { name: "本板块题号" }).getByRole("button", { name: new RegExp(`^第 ${c.number} 题`) }).click();
    await expect(page.locator(".exam-question-stem")).not.toContainText("请在原卷");
    expect((await page.locator(".exam-question-stem").textContent())!.length).toBeLessThan(600);
    await expect(page.locator(".exam-number-grid button")).toHaveCount(10);
    if (c.options) {
      await expect.poll(() => page.locator(".exam-choice-list label > span > span").count()).toBe(c.options);
    }
    await page.locator(`input[name="exam-${c.number}"][value="A"]`).check();
    await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
    await page.reload(); await pane(page);
    await expect(page.locator(".exam-submit-bar")).toContainText("1 / 10");
    const otherKind = c.kind === "reading_cloze" ? "reading_matching" : "reading_cloze";
    expect((await (await page.request.get(`${base}/exams/${c.paper}/${otherKind}`)).json()).answers).toEqual({});
    await page.screenshot({ path: info.outputPath(`${c.paper}-${c.kind}.png`), fullPage: true });
  }
  await page.getByRole("button", { name: "提交本板块", exact: true }).click();
  await page.getByRole("button", { name: "仍然提交本板块", exact: true }).click();
  await expect(page.locator(".exam-analysis")).toHaveCount(10);
  const first = page.locator(".exam-analysis").first();
  if (!(await first.getAttribute("open") !== null)) await first.locator("summary").first().click();
  await first.getByRole("button", { name: "对照本题的来源解析", exact: true }).click();
  await pane(page, true);
  await expect(page.getByRole("button", { name: "返回题目材料", exact: true })).toBeVisible();
  await expect.poll(() => page.locator(".exam-canvas-scroll canvas").evaluate((c: HTMLCanvasElement) => c.width), { timeout: 60000 }).toBeGreaterThan(100);
  await expect(page.locator(".exam-reader-body")).toHaveAttribute("aria-busy", "false", { timeout: 60000 });
  await expect(page.locator(".exam-source-pane .exam-error")).toHaveCount(0);
  expect(await page.locator(".exam-canvas-scroll canvas").evaluate((c: HTMLCanvasElement) => c.toDataURL().length)).toBeGreaterThan(10000);
  await expect(page.locator(".exam-source-pane")).toContainText("非官方答案");
  await page.screenshot({ path: info.outputPath("student-source-analysis.png"), fullPage: true });
});

test("阅读双栏自然段、独立滚动、手机切换与扫描卷原版", async ({ page }, info) => {
  test.setTimeout(240000);
  const { notebook } = await student(page);
  await page.goto(`/?notebook=${notebook}&cet6=exams&exam_kind=reading_careful&exam_paper=cet6-2026-06-1`);
  await expect(page.locator(".exam-source-text")).toContainText("social media", { timeout: 60000 });
  for (const width of [1500, 1024]) {
    await page.setViewportSize({ width, height: 980 });
    const source = (await page.locator(".exam-source-pane").boundingBox())!, answer = (await page.locator(".exam-answer-pane").boundingBox())!;
    expect(source.width).toBeGreaterThan(width === 1500 ? 600 : 400);
    expect(answer.x).toBeGreaterThan(source.x + source.width);
    expect(Math.abs(source.y - answer.y)).toBeLessThan(2);
    expect(await page.locator(".exam-source-text").evaluate(e => getComputedStyle(e).whiteSpace)).toBe("normal");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`student-reading-${width}.png`), fullPage: true });
  }
  await page.locator(".exam-reader-body").evaluate(e => { e.scrollTop = 150; });
  expect(await page.locator(".exam-answer-pane").evaluate(e => e.scrollTop)).toBe(0);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await pane(page, true);
    await page.locator(".exam-reader-body").evaluate(e => { e.scrollTop = 100; });
    const before = await page.locator(".exam-reader-body").evaluate(e => e.scrollTop);
    await pane(page); await page.locator('input[name="exam-46"][value="A"]').check();
    await pane(page, true);
    expect(await page.locator(".exam-reader-body").evaluate(e => e.scrollTop)).toBe(before);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`student-reading-${width}.png`), fullPage: true });
  }
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  await page.setViewportSize({ width: 1500, height: 980 });
  await page.goto(`/?notebook=${notebook}&cet6=exams&exam_kind=reading_careful&exam_paper=cet6-2025-06-3`);
  await expect(page.locator(".exam-source-pane")).toContainText("本卷为扫描件");
  await expect.poll(() => page.locator(".exam-canvas-scroll canvas").evaluate((c: HTMLCanvasElement) => c.width), { timeout: 60000 }).toBeGreaterThan(100);
  await expect(page.locator(".exam-reader-body")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("navigation", { name: "本板块题号" }).getByRole("button", { name: /^第 55 题/ }).click();
  await expect(page.getByLabel("原卷页码", { exact: true })).toHaveValue("9");
  await expect(page.locator(".exam-reader-body")).toHaveAttribute("aria-busy", "false");
  await page.screenshot({ path: info.outputPath("student-scanned-paper.png"), fullPage: true });
});
