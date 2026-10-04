import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

test("真题点词、原句保存、待复习、刷新恢复、原题回链与句子理解", async ({ page }, info) => {
  test.setTimeout(300000);
  const live = process.env.PLAYWRIGHT_REAL_MODE === "1";
  if (live) {
    const health = await (await page.request.get("/api/health")).json();
    expect(health.release).toBe(process.env.ACCEPTANCE_EXPECTED_COMMIT);
    expect(health.demo_mode).toBe(false);
  }
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("真题复习流程验收");
  await page.getByPlaceholder("you@example.com").fill(`reading-loop-${randomUUID()}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Reading-Loop-QA-2026!");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程" });
  await expect(dialog).toBeVisible();
  const catalogue = await (await page.request.get("/api/notebooks/learning/catalogue")).json();
  await dialog.getByRole("radio", { name: catalogue.items.find((c: { id: string }) => c.id === "cet6").title, exact: true }).check();
  const creation = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/notebooks");
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  const notebook = (await (await creation).json()).id;
  await expect(page.getByRole("heading", { name: "六级备考中心" })).toBeVisible();
  const base = `/api/notebooks/${notebook}/cet6`, exam = `${base}/exams/cet6-2026-06-1/reading_careful`;
  await page.goto(`/?notebook=${notebook}&cet6=exams&exam_kind=reading_careful&exam_paper=cet6-2026-06-1&exam_question=46`);
  await expect(page.getByRole("navigation", { name: "本板块题号" })).toBeVisible();
  const initial = await (await page.request.get(exam)).json();
  expect((await page.request.post(exam, { data: { action: "save", request_id: randomUUID(), revision: initial.revision, version: initial.version, used_help: true } })).ok()).toBe(true);
  await page.locator('input[name="exam-46"][value="A"]').check();
  await page.getByRole("button", { name: "保留本页输入，准备保存", exact: true }).click();
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  const settled = (await (await page.request.get(exam)).json()).revision;
  // Cover the former 650 ms autosave loop after a remote monotonic help flag.
  await page.waitForTimeout(2000);
  expect((await (await page.request.get(exam)).json()).revision).toBe(settled);
  await page.getByRole("button", { name: "查词 social", exact: true }).first().click({ timeout: 90000 });
  const panel = page.getByRole("region", { name: "词句学习", exact: true });
  await expect(panel.locator(".exam-excerpt-word > strong")).toHaveText("social");
  const sentence = await panel.locator("blockquote").first().innerText();
  await expect(panel.locator("audio")).toHaveAttribute("src", /\/word-audio\/v1\/en-US\/cet-.*\.mp3$/);
  await panel.getByRole("button", { name: "听发音", exact: true }).click();
  await expect.poll(() => panel.locator("audio").evaluate((audio: HTMLAudioElement) => audio.currentTime)).toBeGreaterThan(0);
  await panel.getByLabel("我的语境理解（选填）").fill("本句语境笔记，仅翻面后显示");
  // A lost response must be retryable without adding another context or recall.
  let lost = false;
  await page.route(`**/api/notebooks/${notebook}/cet6/words/*`, async route => {
    if (route.request().method() === "POST" && !lost) { lost = true; await route.fetch(); await route.abort(); }
    else await route.continue();
  });
  await panel.getByRole("button", { name: "加入复习，保留原句", exact: true }).click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await panel.getByRole("button", { name: "加入复习，保留原句", exact: true }).click();
  await expect(panel.getByRole("button", { name: "加入复习，保留原句", exact: true })).toBeEnabled();
  await expect(panel.getByRole("status").filter({ hasText: "已加入今日待复习" })).toBeVisible();
  await panel.getByRole("button", { name: "加入复习，保留原句", exact: true }).click();
  await expect(panel.getByRole("button", { name: "加入复习，保留原句", exact: true })).toBeEnabled();
  await expect.poll(async () => (await (await page.request.get(exam)).json()).used_help).toBe(true);
  const found = (await (await page.request.get(base + "/words?q=social")).json()).items.find((w: { word: string }) => w.word === "social");
  const wordPath = base + "/words/" + found.id;
  const saved = await (await page.request.get(wordPath)).json();
  const card = saved.cards.find((c: { contexts: unknown[] }) => c.contexts.length);
  expect(card.contexts).toHaveLength(1); expect(card.tracks).toEqual({});
  expect((await page.request.post(wordPath, { data: { action: "collect", revision: card.revision, request_id: randomUUID(), version: saved.version, sense_id: card.sense_id } })).ok()).toBe(true);
  await panel.getByRole("button", { name: "加入复习，保留原句", exact: true }).click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await panel.getByRole("button", { name: "重新读取词卡，保留原句与笔记", exact: true }).click();
  await expect(panel.getByLabel("我的语境理解（选填）")).toHaveValue("本句语境笔记，仅翻面后显示");
  await panel.getByRole("button", { name: "加入复习，保留原句", exact: true }).click();
  await expect(panel.getByRole("button", { name: "加入复习，保留原句", exact: true })).toBeEnabled();
  await expect(panel.getByRole("status").filter({ hasText: "已加入今日待复习" })).toBeVisible();
  expect((await (await page.request.get(base + "/word-plan")).json()).coverage.learned).toBe(0);
  await page.screenshot({ path: info.outputPath("reading-word-desktop.png"), fullPage: true });
  if (live) {
    const longest = await panel.getByLabel("选择原句").locator("option").evaluateAll(options => options.map(o => (o as HTMLOptionElement).value).sort((a, b) => b.length - a.length)[0]);
    await panel.getByLabel("选择原句").selectOption(longest);
  }
  await panel.getByRole("button", { name: "拆解这句话", exact: true }).click();
  if (live) {
    await expect(panel.getByRole("heading", { name: "先看主干" })).toBeVisible({ timeout: 115000 });
    await expect(panel.getByRole("button", { name: "对照参考答案" })).toBeDisabled();
    await panel.locator("textarea").fill("先根据主干与上下文说明自己的理解。");
    await panel.getByRole("button", { name: "对照参考答案" }).click();
    await expect(panel.locator(".exam-sentence-result > p").last()).not.toBeEmpty();
    await page.screenshot({ path: info.outputPath("sentence-live.png"), fullPage: true });
    await writeFile(info.outputPath("sentence-live.txt"), await panel.innerText(), "utf8");
  } else {
    await expect(panel.getByRole("alert")).toContainText("演示环境未启用 AI 拆句");
    await expect(panel.getByRole("button", { name: "加入复习，保留原句" })).toBeEnabled();
  }
  await page.reload();
  await expect(page.getByText("本轮使用过查词或拆句帮助，结果按借助帮助的练习记录。", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "今日复习", exact: true }).click();
  await page.getByRole("button", { name: "先开始学习", exact: true }).click();
  const due = page.locator(".cet6-overview button").first();
  await expect(due.locator("strong")).toHaveText("1");
  await due.click();
  await page.getByRole("button", { name: /开始 \/ 继续到期复习/ }).click();
  await expect(page.getByRole("region", { name: "原句复习" })).toContainText(sentence);
  await expect(page.getByText("本句语境笔记，仅翻面后显示", { exact: false })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("region", { name: "原句复习" })).toContainText(sentence);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "翻面看释义", exact: true }).click();
  await expect(page.getByRole("region", { name: "原句复习" })).toContainText("本句语境笔记，仅翻面后显示");
  const roundURL = page.url();
  await page.screenshot({ path: info.outputPath("context-recall-mobile.png"), fullPage: true });
  await page.getByRole("link", { name: "回到原题 · 第 46 题", exact: true }).click();
  await expect(page).toHaveURL(/exam_question=46/);
  await expect(page.getByRole("button", { name: "查词 social", exact: true }).first()).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "查词 social", exact: true }).first().click();
  await expect(panel.locator(".exam-excerpt-word > strong")).toHaveText("social");
  await page.screenshot({ path: info.outputPath("reading-word-mobile.png"), fullPage: true });
  await page.goto(roundURL);
  await page.getByRole("button", { name: /^想起来了/ }).click();
  await expect(page.getByRole("heading", { name: "这一轮完成了" })).toBeVisible();
  const after = await (await page.request.get(wordPath)).json();
  const reviewed = after.cards.find((c: { sense_id: string }) => c.sense_id === card.sense_id);
  expect(reviewed.queued_at).toBeNull(); expect(reviewed.tracks.meaning.attempts).toBe(1);
  expect(reviewed.tracks.meaning.due_at).toBeTruthy();
  expect(errors).toEqual([]);
});
