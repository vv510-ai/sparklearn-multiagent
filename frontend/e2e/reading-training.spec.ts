import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const packs = JSON.parse(readFileSync(path.resolve(__dirname, "../../backend/app/data/reading_examples_v1.json"), "utf8"));
const sample = packs[0].material;

async function register(page: Page) {
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("阅读训练验收");
  await page.getByPlaceholder("you@example.com").fill(`reading-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Reading-Journey-QA-2026!");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程" });
  await expect(dialog).toBeVisible();
  const catalogue = await (await page.request.get("/api/notebooks/learning/catalogue")).json();
  await dialog.getByRole("radio", { name: catalogue.items.find((c: { id: string }) => c.id === "cet6").title, exact: true }).check();
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  await expect(page.getByRole("region", { name: "今日阅读任务" })).toBeVisible();
  const notebook = await page.getByRole("combobox", { name: "切换科目书本" }).inputValue();
  return { notebook, base: `/api/notebooks/${notebook}/reading` };
}

async function openExample(page: Page) {
  await page.getByRole("button", { name: "开始阅读体验", exact: true }).click();
  await expect(page.getByRole("region", { name: "阅读训练工作区" })).toBeVisible();
  await expect(page.locator(".reading-source-badge")).toContainText("非真题");
  return new URL(page.url()).searchParams.get("reading")!;
}

async function answer(page: Page, index: number, choice: number) {
  await page.locator(".reading-question-nav").getByRole("button", { name: new RegExp(`^第 ${index + 1} 题`) }).click();
  await page.locator(".reading-options").getByRole("radio").nth(choice).check();
}

async function saved(page: Page) {
  await expect(page.locator(".reading-save-status")).toHaveText("已保存到账号");
}

test("真实账号完成阅读、跨设备恢复、订正、提前复习和手机布局", async ({ page, browser }, info) => {
  await page.setViewportSize({ width: 1520, height: 1000 });
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  const { base } = await register(page); const id = await openExample(page);
  await expect(page.locator(".notebook-layout")).toHaveAttribute("data-sources-collapsed", "true");
  const before = await (await page.request.get(`${base}/${id}`)).json();
  expect(before.feedback).toBeUndefined(); expect(before.material.questions[0].answer).toBeUndefined();
  await answer(page, 0, (sample.questions[0].answer + 1) % 4); await saved(page);
  const secondContext = await browser.newContext({ storageState: { cookies: (await page.context().storageState()).cookies, origins: [] } });
  const second = await secondContext.newPage();
  second.on("pageerror", e => errors.push(e.message));
  await second.goto(page.url());
  await expect(second.locator(".reading-options").getByRole("radio").nth((sample.questions[0].answer + 1) % 4)).toBeChecked();
  await secondContext.close();
  await page.reload(); await expect(page.locator(".reading-options").getByRole("radio").nth((sample.questions[0].answer + 1) % 4)).toBeChecked();
  await expect(page.getByRole("button", { name: "提交首次答案", exact: true })).toBeInViewport();
  await page.screenshot({ path: info.outputPath("reading-desktop.png"), fullPage: true });
  for (let i = 1; i < sample.questions.length; i++) {
    await answer(page, i, sample.questions[i].answer);
    if (i === 1) await page.getByLabel("这题我不太确定，之后再复习").check();
  }
  await page.getByRole("button", { name: "提交首次答案", exact: true }).click();
  await expect(page.locator(".reading-feedback")).toContainText("需要订正");
  await expect(page.locator(".reading-feedback blockquote")).toHaveText(sample.questions[0].evidence.quote);
  await expect(page.locator(".reading-options input").first()).toBeDisabled();
  await page.getByLabel("记下一个容易忽略的地方（选填）").fill("区分使用次数与学习效果，保留原文的人群范围。");
  await page.screenshot({ path: info.outputPath("reading-feedback-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "做一个短练习", exact: true }).click();
  const drilling = await (await page.request.get(`${base}/${id}`)).json();
  for (const [i, qid] of drilling.focus_ids.entries()) await answer(page, i, sample.questions.find((q: { id: string }) => q.id === qid).drill.answer);
  await page.getByRole("button", { name: "提交短练习", exact: true }).click();
  await page.getByRole("button", { name: "完成订正，安排复习", exact: true }).click();
  await expect(page.locator(".reading-completion")).toContainText("首次作答 4 / 5");
  await expect(page.locator(".reading-next-review")).toContainText("关闭网站后不会发送通知");
  const completed = await (await page.request.get(`${base}/${id}`)).json();
  await page.getByRole("button", { name: "提前练习一次", exact: true }).click();
  await expect(page.locator(".reading-callout")).toContainText("不推进原复习计划");
  for (const [i, qid] of completed.focus_ids.entries()) await answer(page, i, sample.questions.find((q: { id: string }) => q.id === qid).recall.answer);
  await saved(page); await page.reload();
  await expect(page.getByRole("button", { name: "提交复习答案", exact: true })).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator(".reading-passage")).not.toBeVisible();
  await page.getByRole("button", { name: "练习材料", exact: true }).click();
  await expect(page.locator(".reading-passage")).toBeVisible();
  await page.screenshot({ path: info.outputPath("reading-mobile-material.png"), fullPage: true });
  await page.getByRole("button", { name: "题目与作答", exact: true }).click();
  await expect(page.getByRole("button", { name: "提交复习答案", exact: true })).toBeInViewport();
  await page.screenshot({ path: info.outputPath("reading-mobile-question.png"), fullPage: true });
  await page.getByRole("button", { name: "提交复习答案", exact: true }).click();
  await expect(page.locator(".reading-completion")).toContainText("这次复习已记录");
  const reviewed = await (await page.request.get(`${base}/${id}`)).json();
  expect(reviewed.review).toEqual(completed.review); expect(reviewed.first).toEqual(completed.first);
  expect(reviewed.history).toHaveLength(1); expect(reviewed.history[0].early).toBe(true);
  await page.getByRole("button", { name: "回到今日任务", exact: true }).click();
  await expect(page.locator(".reading-today")).toContainText(packs[1].material.title);
  await page.screenshot({ path: info.outputPath("reading-today-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1520, height: 1000 });
  await page.getByRole("button", { name: "学习画像" }).click();
  await expect(page.getByRole("region", { name: "阅读学习记录" })).toContainText("首次 4/5");
  await page.screenshot({ path: info.outputPath("reading-progress.png"), fullPage: true });
  await page.getByRole("region", { name: "阅读学习记录" }).getByRole("button", { name: new RegExp(sample.title) }).click();
  await expect(page.locator(".reading-completion")).toContainText("首次作答 4 / 5");
  expect(errors).toEqual([]);
});

test("表单导入自备材料，核对原文证据并保留原题复习边界", async ({ page }, info) => {
  const { base } = await register(page);
  await page.getByRole("button", { name: "导入自己的真题", exact: true }).click();
  const q = packs[1].material.questions[0];
  await page.getByRole("textbox", { name: "材料标题", exact: true }).fill("自备阅读验收样本（非真实考卷）");
  await page.getByRole("textbox", { name: "具体来源", exact: true }).fill("由验收导入的原创样本；用于检查自备材料流程");
  await page.getByRole("textbox", { name: "文章原文", exact: true }).fill(packs[1].material.paragraphs.join("\n\n"));
  await page.getByRole("textbox", { name: "题干", exact: true }).fill(q.prompt);
  for (let i = 0; i < 4; i++) await page.getByLabel(`选项 ${String.fromCharCode(65 + i)}`, { exact: true }).fill(q.options[i]);
  await page.getByRole("combobox", { name: "标准答案", exact: true }).selectOption(String(q.answer));
  await page.getByRole("textbox", { name: "原文证据", exact: true }).fill("This quote does not occur in the passage.");
  await page.getByRole("textbox", { name: "答案说明", exact: true }).fill(q.explanation);
  await page.getByRole("button", { name: "保存材料，开始练习", exact: true }).click();
  await expect(page.locator(".reading-error[role=alert]")).toContainText("没有出现在指定段落");
  await page.getByRole("textbox", { name: "原文证据", exact: true }).fill(q.evidence.quote);
  await page.getByRole("button", { name: "保存导入草稿", exact: true }).click();
  await page.screenshot({ path: info.outputPath("reading-import.png"), fullPage: true });
  await page.getByRole("button", { name: "保存材料，开始练习", exact: true }).click();
  await expect(page.locator(".reading-source-badge")).toContainText("答案与解析由导入者提供");
  const id = new URL(page.url()).searchParams.get("reading")!;
  const imported = await (await page.request.get(`${base}/${id}`)).json(); expect(imported.demo).toBe(false);
  await answer(page, 0, q.answer); await page.getByLabel("作答时查看过提示或答案").check();
  await page.getByRole("button", { name: "提交首次答案", exact: true }).click();
  await expect(page.locator(".reading-feedback")).toContainText("导入者提供的解析");
  await page.getByRole("button", { name: "做一个短练习", exact: true }).click();
  await expect(page.locator(".reading-passage h2")).toHaveText("原题重做");
  await answer(page, 0, q.answer); await page.getByRole("button", { name: "提交短练习", exact: true }).click();
  await page.getByRole("button", { name: "完成订正，安排复习", exact: true }).click();
  await expect(page.locator(".reading-completion")).toContainText("使用过提示或答案");
  expect((await (await page.request.get(`${base}/${id}`)).json()).first.used_help).toBe(true);
});

test("并发冲突与保存失败都保留当前草稿，可核对后恢复", async ({ page }) => {
  const { base } = await register(page); const id = await openExample(page); const url = `${base}/${id}`;
  await answer(page, 0, 0); await saved(page);
  const state = await (await page.request.get(url)).json();
  const changed = await page.request.post(url, { data: { request_id: randomUUID(), revision: state.revision, version: state.version, action: "draft", answers: { [sample.questions[0].id]: 1 } } });
  expect(changed.ok()).toBeTruthy();
  await answer(page, 0, 2);
  await expect(page.locator(".reading-error[role=alert]")).toContainText("另一页面已保存");
  await expect(page.locator(".reading-options").getByRole("radio").nth(2)).toBeChecked();
  await page.getByRole("button", { name: "重新加载，保留草稿", exact: true }).click();
  await page.getByRole("button", { name: "保存当前草稿", exact: true }).click(); await saved(page);
  expect((await (await page.request.get(url)).json()).draft[sample.questions[0].id]).toBe(2);
  await page.route(`**${url}`, async route => { if (route.request().method() === "POST") await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "验收模拟：保存暂时不可用" }) }); else await route.continue(); });
  await answer(page, 0, 3);
  await expect(page.locator(".reading-error[role=alert]")).toContainText("保存暂时不可用");
  await expect(page.locator(".reading-options").getByRole("radio").nth(3)).toBeChecked();
  await page.unroute(`**${url}`);
  await page.getByRole("button", { name: "保存当前草稿", exact: true }).click(); await saved(page);
  await page.reload(); await expect(page.locator(".reading-options").getByRole("radio").nth(3)).toBeChecked();
  const prior = await (await page.request.get(url)).json(); expect(prior.first).toBeNull();
  let committedRevision = 0;
  await page.route(`**${url}`, async route => {
    if (route.request().method() === "POST") { const response = await route.fetch(); committedRevision = (await response.json()).revision; await route.abort("failed"); }
    else await route.continue();
  });
  await answer(page, 1, 1);
  await expect(page.locator(".reading-error[role=alert]")).toBeVisible();
  expect(committedRevision).toBe(prior.revision + 1);
  await page.unroute(`**${url}`);
  await page.getByRole("button", { name: "保存当前草稿", exact: true }).click(); await saved(page);
  expect((await (await page.request.get(url)).json()).revision).toBe(committedRevision);
});


test("阅读可返回课程章节；一页保存不删除另一页的新草稿", async ({ page, context }) => {
  const { base } = await register(page); const id = await openExample(page); const url = `${base}/${id}`;
  const other = await context.newPage(); await other.goto(page.url());
  await expect(other.locator(".reading-options")).toBeVisible();
  let release!: () => void; let seen!: () => void;
  const held = new Promise<void>(r => { release = r; }); const pending = new Promise<void>(r => { seen = r; });
  await page.route(`**${url}`, async route => { if (route.request().method() === "POST") { seen(); await held; } await route.continue(); });
  await other.route(`**${url}`, async route => { if (route.request().method() === "POST") await route.abort("failed"); else await route.continue(); });
  await answer(page, 0, 0); await pending;
  await answer(other, 0, 2); release(); await saved(page);
  const localAnswer = await other.evaluate(({ qid, id }) => {
    const key = Object.keys(localStorage).find(k => k.startsWith("learnloop:reading-draft:") && k.includes(id) && k.endsWith(":answer"));
    return key ? JSON.parse(localStorage.getItem(key)!).value.answers[qid] : null;
  }, { qid: sample.questions[0].id, id });
  expect(localAnswer).toBe(2);
  await other.reload();
  await expect(other.locator(".reading-options").getByRole("radio").nth(2)).toBeChecked();
  await expect(other.locator(".reading-error[role=alert]")).toContainText("服务器已有新记录");
  await other.getByRole("button", { name: "使用服务器版本", exact: true }).click();
  await expect(other.locator(".reading-options").getByRole("radio").nth(0)).toBeChecked();
  await other.close(); await page.unroute(`**${url}`);
  await page.getByRole("button", { name: "学习对话", exact: true }).click();
  await page.locator(".course-source-path").getByRole("button", { name: "继续课程学习", exact: true }).click();
  await expect(page.locator(".course-study-card h1")).toBeVisible();
  await expect(page.locator(".reading-player")).toHaveCount(0);
  expect(new URL(page.url()).searchParams.has("reading")).toBe(false);
});
