import { test, expect } from "@playwright/test";

test("学习方案一键保存、刷新保留，并收起个人密钥", async ({ page }, info) => {
  const marker = Date.now();
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const registered = await page.request.post("/api/auth/register", { data: {
    email: `model-presets-${marker}@example.test`, password: "Preset-local-test-2026!", name: "方案验收",
  } });
  expect(registered.status()).toBe(201);
  await page.request.post("/api/onboarding", { data: { skipped: true } });
  // Inert credentials test account settings only; no provider is contacted.
  const setup = await page.request.post("/api/settings/models", { data: {
    revision: 0, routes: {}, keys: { deepseek: "test-only-deepseek", kimi: "test-only-kimi" },
  } });
  expect(setup.ok()).toBeTruthy();
  let providerTests = 0;
  page.on("request", request => { if (request.url().endsWith("/api/settings/models/test")) providerTests++; });
  await page.goto("/");
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "选一次，之后自动搭配" })).toBeVisible();
  await expect(page.getByLabel("Kimi · 国产 API Key")).toBeHidden();
  await page.getByRole("button", { name: "启用智能搭配", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("已启用智能搭配，下次生成自动使用。");
  let saved = await (await page.request.get("/api/settings/models")).json();
  expect(saved.routes.default).toBe("deepseek-v4-pro");
  expect(saved.routes.research).toBe("kimi-k3");
  expect(saved.routes.notes).toBe("kimi-k3");
  expect(JSON.stringify(saved)).not.toContain("test-only-");
  await page.screenshot({ path: info.outputPath("model-presets-desktop.png"), fullPage: true });

  await page.getByRole("button", { name: "启用全程 K3", exact: true }).click();
  await expect(page.getByRole("button", { name: "已启用全程 K3", exact: true })).toBeDisabled();
  saved = await (await page.request.get("/api/settings/models")).json();
  expect(saved.routes).toEqual({ default: "kimi-k3" });
  await page.reload();
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await expect(page.getByRole("button", { name: "已启用全程 K3", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("model-presets-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "启用日常学习", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("已启用日常学习，下次生成自动使用。");
  expect(providerTests).toBe(0);
  expect(errors).toEqual([]);
});
