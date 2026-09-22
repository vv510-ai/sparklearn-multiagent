import { expect, test } from "@playwright/test";

test("网课跨主题搜索、故障恢复与手机布局", async ({ page }, info) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.setViewportSize({ width: 1512, height: 982 });
  const registration = await page.request.post("/api/auth/register", { data: {
    email: `course-search-${Date.now()}@example.test`, password: "Course-search-e2e-2026!", name: "网课验收",
  } });
  expect(registration.status()).toBe(201);
  await page.request.post("/api/onboarding", { data: { skipped: true } });
  // Exercise the previous hidden topic length failure with a real BFF request.
  const longTopic = await page.request.get(`/api/courses?${new URLSearchParams({q: "英语六级", topic: "学习目标".repeat(50)})}`);
  expect(longTopic.ok()).toBeTruthy();
  expect((await longTopic.json()).items.length).toBeGreaterThan(0);
  await page.goto("/");
  await page.getByRole("button", { name: "跳过引导", exact: true }).click();
  await page.getByRole("button", { name: /推荐网课.*按知识点/ }).click();
  await expect(page.getByRole("heading", { name: "找你想学的课程" })).toBeVisible();
  for (const query of ["英语六级", "Python 入门", "高数"]) {
    await page.getByLabel("搜索课程", {exact: true}).fill(query);
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.locator(".course-card").first()).toBeVisible();
    await expect(page.getByRole("link", { name: "B 站全站搜索" })).toHaveAttribute("href", new RegExp(encodeURIComponent(query).replace(/%20/g, "\\+")));
  }
  // Inject only provider transport output to cover a subject outside all seeds.
  const snapshot = await (await page.request.get("/api/courses?q=Python")).json();
  await page.route("**/api/courses?**", async route => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("q")).toBe("摄影入门");
    expect(url.searchParams.get("kp")).toBe("");
    await route.fulfill({json: {...snapshot, reason: "搜索：摄影入门", search_text: "摄影入门", search_status: "ok", notice: "B 站公开搜索结果", items: [
      {...snapshot.items[0], id: "photography-fixture", title: "摄影入门：光圈与快门", source: "bilibili_search", topics: []},
    ]}});
  });
  await page.getByLabel("搜索课程", {exact: true}).fill("摄影入门");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByRole("heading", {name: "摄影入门：光圈与快门"})).toBeVisible();
  await page.screenshot({path: info.outputPath("courses-desktop.png"), fullPage: true});
  await page.setViewportSize({width:390, height:844});
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: info.outputPath("courses-mobile.png"), fullPage: true});
  await page.unroute("**/api/courses?**");
  await page.route("**/api/courses?**", route => route.fulfill({status:503, json:{detail:"temporary outage"}}));
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByRole("alert").filter({hasText:"课程加载失败"})).toBeVisible();
  await expect(page.getByRole("heading", {name:"暂未找到匹配课程"})).toHaveCount(0);
  await expect(page.getByRole("link", {name:"B 站全站搜索"})).toHaveAttribute("href", /%E6%91%84%E5%BD%B1/);
  await page.unroute("**/api/courses?**");
  await page.getByLabel("搜索课程", {exact: true}).fill("Python");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.locator(".course-card").first()).toBeVisible();
  await expect(page.getByRole("alert").filter({hasText:"课程加载失败"})).toHaveCount(0);
  expect(errors).toEqual([]);
});
