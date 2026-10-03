import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import type { Cet6AdviceData } from "../lib/cet6-advice";

const live = process.env.PLAYWRIGHT_REAL_MODE === "1";

async function register(page: Page) {
  if (live) {
    const health = await (await page.request.get("/api/health")).json();
    expect(health.release).toBe(process.env.ACCEPTANCE_EXPECTED_COMMIT);
    expect(health.demo_mode).toBe(false);
  }
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("入门建议验收");
  await page.getByPlaceholder("you@example.com").fill(`advice-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Advice-QA-2026-Only!");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程" });
  await expect(dialog).toBeVisible();
  const catalogue = await (await page.request.get("/api/notebooks/learning/catalogue")).json();
  await dialog.getByRole("radio", { name: catalogue.items.find((c: { id: string }) => c.id === "cet6").title, exact: true }).check();
  const response = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/notebooks");
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  const book = (await (await response).json()).id;
  await expect(page.getByRole("form", { name: "学习偏好设置" })).toBeVisible();
  return { book, base: `/api/notebooks/${book}/cet6` };
}

async function completed(page: Page, base: string): Promise<Cet6AdviceData> {
  await expect(page.getByRole("heading", { name: "你的六级备考建议" })).toBeVisible();
  let state: Cet6AdviceData;
  await expect.poll(async () => {
    state = await (await page.request.get(base + "/advice")).json();
    return state.status;
  }, { timeout: 155000, intervals: [1000, 2000, 3000] }).toBe(live ? "ready" : "unavailable");
  await expect(page.locator(".advice-summary")).toBeVisible({ timeout: 10000 });
  return state!;
}

test("首次填写即获得完整建议，刷新恢复并进入实际练习", async ({ page }, info) => {
  test.setTimeout(260000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  const { book, base } = await register(page);
  const form = page.getByRole("form", { name: "学习偏好设置" });
  await form.getByLabel("我现在最想解决的问题").fill("阅读经常来不及做完，认识单词却找不到句子之间的关系。");
  await form.getByLabel("每天可用分钟").fill("20");
  await form.getByLabel("目标分数（选填）").fill("450");
  await form.getByText("参考历史成绩（选填）", { exact: true }).click();
  for (const [label, score] of [["历史总分", "353"], ["听力成绩", "145"], ["阅读成绩", "112"], ["写作与翻译合计", "96"]]) await form.getByLabel(label, { exact: true }).fill(score);
  await form.getByText("补充上次备考情况（选填）", { exact: true }).click();
  await form.getByLabel("上次怎样准备").selectOption("irregular");
  await form.getByLabel("上次阅读完成情况").selectOption("unfinished");
  await form.getByRole("button", { name: "保存并查看建议" }).click();
  const state = await completed(page, base);
  expect(state.input.total_score).toBe(353); expect(state.facts.score_gap).toBe(97);
  expect(state.content.followup_keys).toEqual([]);
  for (const day of state.week) expect(day.tasks.reduce((sum, t) => sum + t.minutes, 0)).toBe(20);
  for (const kind of ["阅读", "听力", "写作", "翻译", "词汇"]) await expect(page.getByRole("region", { name: `${kind}学习方法`, exact: true })).toBeVisible();
  await info.attach("saved-advice", { body: JSON.stringify(state, null, 2), contentType: "application/json" });
  await page.screenshot({ path: info.outputPath("advice-desktop-top.png") });
  await page.screenshot({ path: info.outputPath("advice-desktop.png"), fullPage: true });
  await page.getByRole("region", { name: "阅读学习方法", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("advice-reading-desktop.png") });
  await page.getByRole("region", { name: "近期学习安排" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("advice-week-desktop.png") });
  await page.reload(); await expect(page.locator(".advice-summary")).toContainText(state.content.summary);
  expect((await (await page.request.get(base + "/advice")).json()).generated_at).toBe(state.generated_at);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole("heading", { name: "你的六级备考建议" }).scrollIntoViewIfNeeded();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole("button", { name: "调整我的情况", exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`advice-${width}-top.png`) });
    await page.screenshot({ path: info.outputPath(`advice-${width}.png`), fullPage: true });
    await page.getByRole("region", { name: "阅读学习方法", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`advice-reading-${width}.png`) });
    await page.getByRole("region", { name: "近期学习安排" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`advice-week-${width}.png`) });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => { document.documentElement.style.zoom = ""; });
  const action = state.actions.find(a => a.kind === state.content.priority_kind)!;
  await page.locator(".advice-summary").getByRole("button", { name: action.label, exact: true }).click();
  if (action.kind !== "vocabulary") {
    await expect(page.locator(".exam-workspace")).toBeVisible();
    expect(new URL(page.url()).searchParams.get("exam_paper")).toBe(action.paper_id);
    if (action.kind === "reading") {
      expect(new URL(page.url()).searchParams.get("exam_kind")).toBe("reading_careful");
      await expect(page.locator(".exam-number-grid button")).toHaveCount(10);
    }
  } else await expect(page.getByRole("region", { name: "六级词汇学习" })).toBeVisible();
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await page.goto(`/?notebook=${book}&cet6=advice`);
  await expect(page.locator(".advice-summary")).toContainText(state.content.summary);
  expect(errors).toEqual([]);
});

test("可跳过入门填写，只有总分时按90分钟安排且修改后提示更新", async ({ page }, info) => {
  test.setTimeout(250000);
  const { book, base } = await register(page);
  await page.getByRole("button", { name: "先开始学习", exact: true }).click();
  await expect(page.locator(".cet6-today")).toBeVisible();
  await page.reload(); await expect(page.locator(".cet6-today")).toBeVisible();
  await page.getByRole("button", { name: "学习偏好", exact: true }).click();
  const form = page.getByRole("form", { name: "学习偏好设置" });
  await form.getByLabel("每天可用分钟").fill("90");
  await form.getByLabel("我现在最想解决的问题").fill("希望建立稳定的备考习惯，先了解各项怎样复习。");
  await form.getByText("参考历史成绩（选填）", { exact: true }).click();
  await form.getByLabel("历史总分", { exact: true }).fill("353");
  await form.getByRole("button", { name: "保存并查看建议" }).click();
  const state = await completed(page, base);
  expect(state.input.reading_score).toBeNull(); expect(state.input.target_score).toBeNull(); expect(state.facts.score_gap).toBeNull();
  for (const day of state.week) expect(day.tasks.reduce((sum, t) => sum + t.minutes, 0)).toBe(90);
  await info.attach("total-only-advice", { body: JSON.stringify(state, null, 2), contentType: "application/json" });
  const current = await (await page.request.get(base)).json();
  const updated = await page.request.post(base + "/preferences", { data: { revision: current.revision, preferences: { ...current.preferences, daily_minutes: 15 } } });
  expect(updated.ok()).toBeTruthy();
  await page.goto(`/?notebook=${book}&cet6=advice`);
  await expect(page.getByText("你的学习情况已更新", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "按最新情况更新建议", exact: true })).toBeVisible();
  expect((await (await page.request.get(base + "/advice")).json()).input.daily_minutes).toBe(90);
});

if (!live) test("无成绩也能生成起步安排，网络失败保留输入且可恢复", async ({ page }) => {
  const { base } = await register(page);
  await page.route("**/cet6/advice", async route => {
    if (route.request().method() === "POST") await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "验收注入：暂时不可用" }) });
    else await route.continue();
  });
  await page.getByRole("button", { name: "保存并查看建议" }).click();
  await expect(page.locator(".cet6-advice").getByRole("alert")).toContainText("验收注入：暂时不可用");
  expect((await (await page.request.get(base)).json()).preferences.total_score).toBeNull();
  await page.unroute("**/cet6/advice");
  await page.getByRole("button", { name: "重新读取并生成", exact: true }).click();
  await completed(page, base);
  await expect(page.getByRole("region", { name: "近期学习安排" })).toBeVisible();
});
