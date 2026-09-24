import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { registerLearner } from "./intake-helpers";

test("复合六级请求保留考点占分方法并直接生成一图看懂", async ({ page }, info) => {
  test.setTimeout(360_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), async button => { await button.click(); });
  await registerLearner(page, "request-quality");
  await page.getByRole("checkbox", { name: /准备课程考试/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "大学英语六级（CET-6）", exact: true }).check();
  await page.getByLabel("以前接触过多少？").selectOption("第一次系统学习");
  for (let step = 0; step < 3; step++) await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  await page.getByRole("button", { name: "返回对话", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "回答依据" })).toHaveValue("auto");
  const question = "帮我列出六级要考的考点、占分、你这个网站能提供的学习方法，以及怎么学习的框架，然后生成一图看懂。";
  await page.getByLabel("学习目标输入", { exact: true }).fill(question);
  const response = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST", { timeout: 180_000 });
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(200);
  const request = result.request().postDataJSON();
  expect(request.message).toBe(question);
  expect(request.source_policy).toBe("auto");
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 240_000 });
  const saved = await (await page.request.get(`/api/resources?${new URLSearchParams({ user_id: "session_user", notebook_id: request.notebook_id })}`)).json();
  const resource = saved.items.find((item: { payload: { template: string } }) => item.payload.template === "one_page");
  expect(resource).toBeTruthy();
  expect(resource.payload.source_policy).toBe("supplement");
  expect(resource.payload.generation_mode).not.toBe("unavailable");
  expect(resource.payload.one_page_visual.image_status).toBe("ready");
  if (process.env.PLAYWRIGHT_BASE_URL) {
    expect(resource.payload.one_page_visual.renderer).toBe("svg-map-v2");
    expect(resource.payload.one_page_visual.layout).toBe("knowledge_map");
    expect(resource.payload.one_page_visual.pages).toHaveLength(1);
    expect(resource.payload.one_page_visual.relation_count).toBeGreaterThan(3);
  }
  if (process.env.PLAYWRIGHT_BASE_URL) {
    // Live checks require a real model response, never a demo/source excerpt.
    expect(resource.payload.generation_mode).toBe("model");
    const markdown = resource.payload.markdown;
    for (const topic of ["听力", "阅读", "写作", "翻译", "35%", "15%"]) expect(markdown).toContain(topic);
    expect(markdown).toMatch(/网站|平台|小知|LearnLoop/);
    // A valid citation must not turn the site's short drill into an exam rule.
    for (const line of markdown.split("\n").filter((line: string) => /120\s*[–—-]\s*150/.test(line))) {
      expect(line).toMatch(/本站|基础|起步|练习长度|非.{0,6}考试|不是.{0,6}考试/);
    }
    expect(resource.payload.grounded).toBe(false);
  }
  const card = page.getByRole("button", { name: new RegExp(resource.title) }).first();
  if (await card.getAttribute("aria-expanded") === "false") await card.click();
  await expect(page.getByRole("img", { name: /^一图看懂/ }).first()).toBeVisible();
  const images = page.getByRole("img", { name: /^一图看懂/ });
  for (let index = 0; index < await images.count(); index++) {
    const image = images.nth(index);
    await expect.poll(() => image.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(500);
    await image.evaluate(async el => { await (el as HTMLImageElement).decode(); });
    await image.screenshot({ path: info.outputPath(`compound-image-${index + 1}.png`), animations: "disabled" });
    const visualPage = resource.payload.one_page_visual.pages[index];
    const svg = await page.context().newPage();
    try {
      const asset = new URL(`/api${visualPage.image_url}`, page.url()).href;
      const opened = await svg.goto(asset);
      expect(opened?.ok()).toBe(true);
      const overflow = await svg.locator('text[data-content="true"]').evaluateAll(nodes => nodes.filter(node => {
        const box = (node as SVGGraphicsElement).getBBox();
        return box.x < Number(node.getAttribute("data-bound-left")) - 1
          || box.y < Number(node.getAttribute("data-bound-top")) - 1
          || box.x + box.width > Number(node.getAttribute("data-bound-right")) + 1
          || box.y + box.height > Number(node.getAttribute("data-bound-bottom")) + 1;
      }).map(node => node.textContent));
      expect(overflow).toEqual([]);
      await writeFile(info.outputPath(`compound-map-${index + 1}.svg`), await opened!.text());
    } finally { await svg.close(); }
  }
  const summary = await page.locator('[aria-label="小知回答"]').last().innerText();
  await writeFile(info.outputPath("compound-request-evidence.json"), JSON.stringify({ request, resource, summary }, null, 2));
  await page.screenshot({ path: info.outputPath("compound-request.png"), fullPage: true, animations: "disabled" });
});
