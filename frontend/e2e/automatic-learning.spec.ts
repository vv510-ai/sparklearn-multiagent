import { expect, test, type Page } from "@playwright/test";

test.use({ actionTimeout: 20_000 });

async function register(page: Page) {
  const r = await page.request.post("/api/auth/register", { data: {
    email: `automatic-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`,
    password: "Automatic-guide-test-2026!", name: "学习指引验收",
  } });
  expect(r.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBeTruthy();
  return (await r.json()).user;
}

test("首次登录动态指引、关闭记忆、主动重看和全部功能可达", async ({ page }, info) => {
  await page.setViewportSize({ width: 1512, height: 982 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await register(page);
  const errors: string[] = [];
  let generations = 0;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (/\/api\/(chat|resources\/generate|settings\/models\/test)$/.test(request.url())) generations++; });
  await page.goto("/");
  const popover = page.locator(".driver-popover");
  await expect(popover).toContainText("从你卡住的地方开始");
  await page.screenshot({ path: info.outputPath("guide-desktop.png"), fullPage: true });
  await popover.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(popover).toContainText("有自己的资料，就带进来");
  await popover.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(popover).toContainText("学过以后，试着用一次");
  await popover.getByRole("button", { name: "开始学习", exact: true }).click();
  await expect(popover).toHaveCount(0);
  await expect(page.getByRole("button", { name: "模型设置", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /全部工具/ })).toHaveCount(0);
  await expect(page.locator(".studio-tile")).toHaveCount(11);
  await expect(page.locator(".studio-view")).toHaveCount(6);
  await page.getByRole("region", { name: "小知的下一步建议" }).getByRole("button", { name: "开始提问", exact: true }).click();
  await expect(page.getByLabel("学习目标输入")).toBeFocused();
  await page.getByRole("button", { name: "关闭下一步建议", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "显示下一步建议" })).toBeVisible();
  await expect(page.getByLabel("学习目标输入")).toBeVisible();
  await expect(popover).toHaveCount(0);
  await page.getByRole("button", { name: "学习指引", exact: true }).click();
  await expect(popover).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(popover).toHaveCount(0);
  await expect(page.getByRole("button", { name: "学习指引", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "显示下一步建议" }).click();
  await page.screenshot({ path: info.outputPath("workspace-desktop.png"), fullPage: true });
  expect(generations).toBe(0);
  expect(errors).toEqual([]);
});

test("手机引导定位导航、无横向溢出，学习功能直接展示", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await register(page);
  await page.goto("/");
  const popover = page.locator(".driver-popover");
  for (let step = 0; step < 3; step++) {
    await expect(popover).toBeVisible();
    const box = await popover.boundingBox();
    expect(box).toBeTruthy();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(391);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(845);
    if (step === 1) await expect(page.locator("[data-guide='sources-nav']")).toHaveClass(/driver-active-element/);
    if (step === 2) await expect(page.locator("[data-guide='studio-nav']")).toHaveClass(/driver-active-element/);
    await page.screenshot({ path: info.outputPath(`guide-mobile-${step + 1}.png`), fullPage: true });
    await popover.getByRole("button", { name: step === 2 ? "开始学习" : "下一步", exact: true }).click();
  }
  await page.getByRole("button", { name: "学习工坊", exact: true }).click();
  const sheet = page.locator(".notebook-mobile-sheet");
  await expect(sheet.locator(".studio-tile")).toHaveCount(11);
  await expect(sheet.locator(".studio-view")).toHaveCount(6);
  await expect(sheet.getByRole("button", { name: /全部工具/ })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("workspace-mobile.png"), fullPage: true });
  await sheet.getByRole("button", { name: /深度研究.*检索真实/ }).click();
  await expect(page.getByLabel("想深入研究什么？")).toBeVisible();
});
