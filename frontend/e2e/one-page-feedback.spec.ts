import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { registerLearner } from "./intake-helpers";

for (const scenario of [
  { question: "选词有没有记忆点", supported: true, title: "六级自然追问保留课程依据并生成一图看懂" },
  { question: "量子纠缠有没有记忆点", supported: false, title: "六级资料没有相关内容时明确未生成，不展示错误知识图" },
]) test(scenario.title, async ({ page }, info) => {
  test.setTimeout(360_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerLearner(page, "one-page-feedback");
  console.log("one-page: registered");
  await page.getByRole("checkbox", { name: /从零开始，系统学习/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "大学英语六级（CET-6）", exact: true }).check();
  await page.getByLabel("以前接触过多少？").selectOption("第一次系统学习");
  for (let step = 0; step < 3; step++) await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  await page.getByRole("button", { name: "返回对话", exact: true }).click();
  console.log("one-page: course prepared");
  const skip = page.getByRole("button", { name: "跳过引导", exact: true });
  await skip.click({ timeout: 15_000 });
  // Offline intent fixtures require punctuation; production uses the exact feedback wording.
  const question = scenario.question + (process.env.PLAYWRIGHT_BASE_URL ? "" : "？");
  await page.getByLabel("学习目标输入", { exact: true }).fill(question);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator('[aria-label="小知回答"]').last()).toBeVisible();
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 180_000 });
  console.log("one-page: chat finished");
  const response = page.waitForResponse(r => r.url().endsWith("/api/resources/generate") && r.request().method() === "POST", { timeout: 180_000 });
  await page.getByRole("button", { name: /^一图看懂/ }).click();
  const result = await response;
  console.log("one-page: generation response received");
  expect(result.status()).toBe(200);
  const stream = await result.text();
  const events = stream.split("\n").filter(line => line.startsWith("data:")).map(line => JSON.parse(line.slice(5)));
  const resource = events.find(event => event.type === "resource")?.resource;
  await writeFile(info.outputPath("one-page-evidence.json"), JSON.stringify({
    request: result.request().postDataJSON(), resource,
    summary: events.find(event => event.type === "summary"),
    chat: await page.locator('[aria-label="小知回答"]').allTextContents(),
  }, null, 2));
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 180_000 });
  await page.screenshot({ path: info.outputPath("one-page-result.png"), fullPage: true });
  if (!scenario.supported) {
    expect(resource?.payload.generation_mode).toBe("unavailable");
    expect(resource?.payload.one_page_visual).toBeUndefined();
    expect(events.find(event => event.type === "summary")?.text).toContain("未生成");
    const card = page.getByRole("button", { name: /量子纠缠.*一图看懂/ }).first();
    if (await card.getAttribute("aria-expanded") === "false") await card.click();
    await expect(page.getByText("当前资料中未找到与这次问题相关的内容，尚未开始生成图片。", { exact: true })).toBeVisible();
    await expect(page.getByText("知识图暂不可用 · 资料摘录", { exact: true })).toHaveCount(0);
    await expect(page.getByText("根据课程资料整理，先看结论与结构，再沿着例子理解。", { exact: true })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("one-page-blocked.png"), fullPage: true });
    return;
  }
  expect(resource?.payload.generation_mode).not.toBe("unavailable");
  expect(resource?.payload.markdown).not.toContain("资料不足");
  expect(resource?.payload.source_evidence.length).toBeGreaterThan(0);
  expect(resource.citations.every((c: string) => c.includes("cet6-guide-v1"))).toBe(true);
  if (process.env.PLAYWRIGHT_BASE_URL) {
    expect(resource.payload.generation_mode).toBe("model");
    expect(resource.payload.one_page_visual.image_status).toBe("ready");
    const pages = resource.payload.one_page_visual.pages || [resource.payload.one_page_visual];
    expect(pages.every((p: { image_status: string }) => p.image_status === "ready")).toBe(true);
    const images = page.getByRole("img", { name: /^一图看懂/ });
    await expect(images).toHaveCount(pages.length);
    for (let index = 0; index < pages.length; index++) {
      const image = images.nth(index);
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(500);
      await image.screenshot({ path: info.outputPath(`one-page-image-${index + 1}.png`) });
    }
  }
});
