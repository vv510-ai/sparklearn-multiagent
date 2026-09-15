import { expect, test } from "@playwright/test";

test("公开体验记录真实选择，提示后答对仍需独立复测", async ({ page }) => {
  await page.goto("/review");
  await expect(page.locator('a[href="/evidence"], a[href="/teacher"]')).toHaveCount(0);
  await page.getByRole("radio", { name: "A → B → C" }).check();
  await page.getByRole("button", { name: "提交本次作答" }).click();
  await expect(page.getByRole("heading", { name: /需要区分/ })).toBeVisible();
  await page.getByRole("button", { name: "用新题独立复测" }).click();
  await page.getByRole("button", { name: "我需要一个提示" }).click();
  await page.getByRole("radio", { name: "K → M → P" }).check();
  await page.getByRole("button", { name: "提交本次作答" }).click();
  await expect(page.getByRole("heading", { name: "下一步：再练一次访问顺序。" })).toBeVisible();
  await expect(page.getByText("正确 · 使用提示", { exact: true })).toBeVisible();
  await expect(page.getByText(/当前没有延迟复习记录/)).toBeVisible();
  await page.screenshot({ path: "test-results/review-desktop.png", fullPage: true });
});

test("旧项目页面回到学习入口，手机可直接进入练习体验", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/evidence");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await expect(page.locator('a[href="/evidence"], a[href="/teacher"]')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/learning-entry-mobile.png", fullPage: true });
  let releaseScripts!: () => void;
  const scriptsReady = new Promise<void>((resolve) => { releaseScripts = resolve; });
  await page.route("**/_next/static/chunks/**", async (route) => {
    await scriptsReady;
    await route.continue();
  });
  try {
    await page.getByRole("link", { name: "先体验一次练习", exact: true }).click({ noWaitAfter: true });
    await page.waitForURL(/\/review$/, { waitUntil: "commit" });
    await expect(page.getByRole("radio", { name: "B → A → C", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "我需要一个提示" })).toBeDisabled();
  } finally {
    releaseScripts();
  }
  await expect(page.getByRole("button", { name: "提交本次作答" })).toBeDisabled();
  await page.getByRole("radio", { name: "B → A → C", exact: true }).check();
  await page.getByRole("button", { name: "提交本次作答" }).click();
  await expect(page.getByRole("heading", { name: "顺序正确，接着检验能否迁移。" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/review-mobile.png", fullPage: true });
});

test("教师可导入匿名试点并看到配对统计和未采集阶段", async ({ page }) => {
  const marker=Date.now().toString(36);
  const account=await page.request.post("/api/auth/register", { data: {email:`pilot-${marker}@example.test`, password:"Pilot-Test-2026!", name:"试点功能测试"} });
  expect(account.status()).toBe(201);
  await page.goto("/teacher");
  await expect(page.getByText("教学研究", { exact: true })).toBeVisible();
  await expect(page.locator('a[href="/evidence"]')).toHaveCount(0);
  await page.getByRole("button", { name: "建立试点", exact: true }).click();
  await page.getByLabel("试点名称", { exact: true }).fill("合成数据功能验证");
  await page.getByLabel("研究方案", { exact: true }).fill("仅用于工程验证；两名合成受试者，前后测配对，不声明真实效果。");
  await page.getByRole("button", { name: "保存试点", exact: true }).click();
  await expect(page.getByText("演示数据，不代表教学效果", { exact: true })).toBeVisible();
  const observations=["intervention","control"].flatMap((arm,i)=>["pre","post"].map((phase,j)=>({
    participant:`DEMO_${i}`,arm,phase,knowledge_point:"二叉树",correct:[[4,7],[4,5]][i][j],
    total:10,independent:10,minutes:12,observed_on:j?"2020-08-29":"2020-08-01",
    consent:true,provenance:"合成工程测试数据",data_kind:"demo",errors:[],
  })));
  await page.locator('input[type="file"]').setInputFiles({ name:"synthetic.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify({observations})) });
  await page.getByRole("button", { name: "校验并导入", exact: true }).click();
  await expect(page.getByText("20.0 个百分点", { exact: true })).toBeVisible();
  await expect(page.getByRole("table").getByText("待采集", { exact: true })).toHaveCount(2);
  await page.screenshot({ path: "test-results/teacher-desktop.png", fullPage: true });
  await page.setViewportSize({width:390,height:844});
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/teacher-mobile.png", fullPage: true });
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "删除当前试点", exact: true }).click();
  await expect(page.getByText("试点及其观测记录已删除。", { exact: true })).toBeVisible();
});
