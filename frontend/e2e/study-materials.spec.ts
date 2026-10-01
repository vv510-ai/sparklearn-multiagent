import { expect, test, type Page } from "@playwright/test";

const password = "Materials-QA-2026!";
async function registerHere(page: Page) {
  const email = `materials-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.test`;
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("资料学习验收");
  await page.getByPlaceholder("you@example.com").fill(email);
  await page.getByPlaceholder("至少 8 位").fill(password);
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await expect(page.getByRole("heading", { name: "找到真资料，把学习做下去。" })).toBeVisible();
  return email;
}
async function startStudy(page: Page) {
  await page.goto("/materials?course=cet6&kind=past_paper&year=2025-06");
  await page.locator(".material-card").first().getByRole("button", { name: "加入学习清单" }).click();
  const email = await registerHere(page);
  await expect(page.getByLabel("做到哪里（题号 / 页码 / 章节）")).toBeVisible();
  return email;
}

test("公开资料按课程、来源和考期筛选，站内明确内容边界", async ({ page }, testInfo) => {
  await page.goto("/materials?course=cet6&kind=past_paper");
  await expect(page.locator(".materials-result")).toContainText("33 个资料入口");
  expect((await page.request.get("/api/materials/studies")).status()).toBe(401);
  expect((await page.request.post("/api/materials/studies", { data: { material_id: "cet6-format" } })).status()).toBe(401);
  await page.getByLabel("考期 / 版本").selectOption("2025-06");
  await expect(page.locator(".material-card")).toHaveCount(3);
  await expect(page.locator(".material-card").first().getByRole("link", { name: "打开原始资料 ↗" })).toHaveAttribute("href", "https://cet6.koolearn.com/20250609/901413.html");
  await page.reload();
  await expect(page.getByLabel("考期 / 版本")).toHaveValue("2025-06");
  await page.screenshot({ path: testInfo.outputPath("materials-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "清除筛选" }).click();
  await page.getByRole("combobox", { name: "课程", exact: true }).selectOption("python");
  await expect(page.locator(".material-card")).toHaveCount(6);
  await page.getByLabel("搜索资料").fill("CS50");
  await expect(page.locator(".material-card")).toHaveCount(2);
  await page.getByLabel("搜索资料").fill("no such material xyz");
  await expect(page.getByText("暂未收录符合条件的资料。", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await page.getByRole("combobox", { name: "来源", exact: true }).selectOption("华研外语");
  await expect(page.locator(".material-card").first()).toContainText("扫码");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("materials-mobile.png"), fullPage: true });
});

test("BFF登录保存、刷新恢复、到期复习和冲突草稿保护", async ({ page }, testInfo) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await startStudy(page);
  const location = page.getByLabel("做到哪里（题号 / 页码 / 章节）");
  await location.fill("第一套阅读46—50题");
  await page.getByLabel("错题与复盘").fill("47题定位错误；重新找对应句。");
  await page.getByLabel("累计用时（分钟）").fill("20");
  await page.getByLabel("下次复习日期").fill("2026-01-01");
  await page.getByLabel("任务状态").selectOption("done");
  await page.getByRole("button", { name: "保存学习记录", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "学习记录已保存" })).toBeVisible();
  await expect(page.getByText("有 1 项到了复习日期")).toBeVisible();
  await page.reload();
  await page.locator(".material-study-choice").first().click();
  await expect(location).toHaveValue("第一套阅读46—50题");
  await expect(page.getByLabel("错题与复盘")).toHaveValue("47题定位错误；重新找对应句。");
  const current = (await (await page.request.get("/api/materials/studies")).json()).items[0];
  const { id, material_id: _material, ...payload } = current;
  expect((await page.request.post(`/api/materials/studies/${id}`, { data: { ...payload, notes: "另一页面保存的记录" } })).ok()).toBeTruthy();
  await page.getByLabel("错题与复盘").fill("当前页仍有草稿");
  await page.getByRole("button", { name: "保存学习记录", exact: true }).click();
  await expect(page.locator(".materials-error")).toContainText("其他页面更新");
  await expect(page.getByLabel("错题与复盘")).toHaveValue("当前页仍有草稿");
  await page.getByRole("button", { name: "重新加载记录" }).click();
  await expect(page.getByRole("status").filter({ hasText: "已加载服务器记录" })).toBeVisible();
  await page.getByRole("button", { name: "放弃草稿，显示已保存记录" }).click();
  await expect(page.getByLabel("错题与复盘")).toHaveValue("另一页面保存的记录");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("materials-study-mobile.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("登录失效后同账号恢复草稿，换账号不泄露记录", async ({ page }) => {
  const email = await startStudy(page);
  await page.getByLabel("错题与复盘").fill("失效前未保存的私有草稿");
  await page.request.post("/api/auth/logout");
  await page.getByRole("button", { name: "保存学习记录", exact: true }).click();
  await expect(page.locator(".materials-error")).toContainText("登录已失效");
  await page.getByRole("button", { name: "登录保存进度" }).click();
  await page.getByPlaceholder("you@example.com").fill(email);
  await page.getByPlaceholder("至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录并继续", exact: true }).click();
  await expect(page.getByLabel("错题与复盘")).toHaveValue("失效前未保存的私有草稿");
  await page.request.post("/api/auth/logout");
  await page.getByRole("button", { name: "保存学习记录", exact: true }).click();
  await expect(page.locator(".materials-error")).toContainText("登录已失效");
  await page.getByRole("button", { name: "登录保存进度" }).click();
  await registerHere(page);
  await expect(page.getByText("还没有资料。", { exact: false })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("失效前未保存的私有草稿");
  expect((await (await page.request.get("/api/materials/studies")).json()).items).toEqual([]);
});
