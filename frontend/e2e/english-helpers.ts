import { expect, type Page } from "@playwright/test";

export async function openEnglish(page: Page, prefix = "english-generation") {
  await page.setViewportSize({ width: 1512, height: 982 });
  const registration = await page.request.post("/api/auth/register", { data: {
    email: prefix + "-" + Date.now() + "-" + Math.random().toString(36).slice(2) + "@example.test",
    password: "English-E2E-2026!", name: "英语场景验收",
  } });
  expect(registration.status()).toBe(201);
  const { user } = await registration.json();
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBeTruthy();
  const response = await page.request.post("/api/notebooks", { data: { user_id: user.id, title: "英语场景练习" } });
  expect(response.status()).toBe(201);
  const notebook = await response.json();
  await page.addInitScript(({ uid, nid }) => localStorage.setItem("learnloop:last-notebook:" + uid, nid), { uid: user.id, nid: notebook.id });
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), async button => { await button.click(); });
  await page.goto("/");
  await page.getByRole("button", { name: /英语场景学习.*影视字幕/ }).click();
  await expect(page.getByRole("button", { name: "生成场景笔记", exact: true })).toBeEnabled();
  return notebook.id as string;
}
