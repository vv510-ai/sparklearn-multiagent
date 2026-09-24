import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { registerLearner } from "./intake-helpers";
test.use({ actionTimeout: 20_000 });

for (const scenario of [
  { question: "选词有没有记忆点", supported: true, title: "六级自然追问保留课程依据并生成一图看懂" },
  { question: "量子纠缠有没有记忆点", supported: false, title: "六级资料没有相关内容时明确未生成，不展示错误知识图" },
]) test(scenario.title, async ({ page }, info) => {
  test.setTimeout(360_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  // The guide imports asynchronously and can appear before or after returning
  // from assessment. Dismiss it through its UI whenever it blocks an action.
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), async button => {
    await button.click();
  });
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
  await page.getByTitle("返回学习对话", { exact: true }).click();
  await page.getByTitle("对话选项", { exact: true }).click();
  await page.getByRole("combobox", { name: "回答依据" }).selectOption("strict");
  await page.keyboard.press("Escape");
  console.log("one-page: course prepared");
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
  const request = result.request().postDataJSON();
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 240_000 });
  // Read the persisted result; Chromium can discard a completed SSE response body.
  const saved = await (await page.request.get(`/api/resources?${new URLSearchParams({ user_id: "session_user", notebook_id: request.notebook_id })}`)).json();
  const resource = saved.items.find((item: { payload: { template: string } }) => item.payload.template === "one_page");
  expect(resource).toBeTruthy();
  const summary = await page.locator('[aria-label="小知回答"]').last().innerText();
  await writeFile(info.outputPath("one-page-evidence.json"), JSON.stringify({
    request, resource, summary,
    chat: await page.locator('[aria-label="小知回答"]').allTextContents(),
  }, null, 2));
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 180_000 });
  const card = page.getByRole("button", { name: new RegExp(resource.title) }).first();
  if (await card.getAttribute("aria-expanded") === "false") await card.click();
  await page.screenshot({ path: info.outputPath("one-page-result.png"), fullPage: true });
  if (!scenario.supported) {
    expect(resource?.payload.generation_mode).toBe("unavailable");
    expect(resource?.payload.one_page_visual).toBeUndefined();
    expect(summary).toContain("未生成");
    await page.getByText("当前资料中未找到与这次问题相关的内容，尚未开始生成图片。", { exact: true }).scrollIntoViewIfNeeded();
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
  {
    expect(resource.payload.one_page_visual.image_status).toBe("ready");
    expect(["svg-text-v1", "svg-map-v2"]).toContain(resource.payload.one_page_visual.renderer);
    expect(resource.payload.one_page_visual.markdown_sha256).toBe(createHash("sha256").update(resource.payload.markdown).digest("hex"));
    if (process.env.PLAYWRIGHT_BASE_URL) expect(["model", "source_guide"]).toContain(resource.payload.generation_mode);
    const pages = resource.payload.one_page_visual.pages || [resource.payload.one_page_visual];
    expect(pages.every((p: { image_status: string }) => p.image_status === "ready")).toBe(true);
    const images = page.getByRole("img", { name: /^一图看懂/ });
    await expect(images).toHaveCount(pages.length);
    for (let index = 0; index < pages.length; index++) {
      const image = images.nth(index);
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(500);
      await image.evaluate(async el => { await (el as HTMLImageElement).decode(); await new Promise(requestAnimationFrame); });
      await image.screenshot({ path: info.outputPath(`one-page-image-${index + 1}.png`), animations: "disabled" });
      const original = await page.context().newPage();
      await original.setViewportSize({ width: 1600, height: 920 });
      const url = new URL(`/api${pages[index].image_url}`, page.url()).href;
      const svgResponse = await original.goto(url);
      expect(svgResponse?.status()).toBe(200);
      expect(svgResponse?.headers()["content-type"]).toContain("image/svg+xml");
      const text = await original.locator('text[data-content="true"]').allTextContents();
      expect(createHash("sha256").update(text.join("")).digest("hex")).toBe(pages[index].text_sha256);
      // Real font metrics must fit the card, not just estimated character counts.
      const overflow = await original.locator('text[data-content="true"]').evaluateAll(nodes => nodes.filter(node => {
        const box = (node as SVGGraphicsElement).getBBox();
        if (node.hasAttribute("data-bound-left")) return box.x < Number(node.getAttribute("data-bound-left")) - 1
          || box.y < Number(node.getAttribute("data-bound-top")) - 1
          || box.x + box.width > Number(node.getAttribute("data-bound-right")) + 1
          || box.y + box.height > Number(node.getAttribute("data-bound-bottom")) + 1;
        const columnRight = box.x < 800 ? 785 : 1540;
        const rowBottom = box.y < 480 ? 469 : 807;
        return box.x + box.width > columnRight - 15 || box.y + box.height > rowBottom - 10;
      }).map(node => node.textContent));
      expect(overflow).toEqual([]);
      await writeFile(info.outputPath(`one-page-${index + 1}.svg`), await svgResponse!.text());
      await original.screenshot({ path: info.outputPath(`one-page-original-${index + 1}.png`), animations: "disabled" });
      await original.close();
    }
    if (resource.payload.one_page_visual.content_status === "source_excerpt") {
      await expect(page.getByText("本次扩写未通过核对，以下仅展示相关资料原文摘录，未覆盖整份资料。").first()).toBeVisible();
      expect(summary).toMatch(/文字摘要|资料摘录/);
    }
    const outsider = await page.context().browser()!.newContext({ baseURL: new URL(page.url()).origin });
    try {
      const asset = `/api${pages[0].image_url}`;
      expect((await outsider.request.get(asset)).status()).toBe(401);
      const signup = await outsider.request.post("/api/auth/register", { data: {
        email: `one-page-outsider-${Date.now()}@example.test`, password: "Intake-E2E-2026!pass", name: "资源隔离验收",
      } });
      expect(signup.status()).toBe(201);
      expect((await outsider.request.get(asset)).status()).toBe(404);
      await writeFile(info.outputPath("asset-access.json"), JSON.stringify({ owner: 200, anonymous: 401, otherUser: 404 }));
    } finally { await outsider.close(); }
    await page.screenshot({ path: info.outputPath("one-page-final.png"), fullPage: true, animations: "disabled" });
  }
});
