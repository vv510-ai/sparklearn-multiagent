import { expect, test } from "@playwright/test";

// Response fixtures test display states; actual provider calls have separate live acceptance.
for (const status of ["passed", "failed", "unverified", "generation_failed"] as const) {
  test(`一图看懂成图核对状态：${status}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 950 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), button => button.click());
    const signup = await page.request.post("/api/auth/register", { data: {
      email: `image-review-${status}-${Date.now()}@example.test`, password: "Review-UI-test!2026", name: "知识图验收",
    } });
    expect(signup.status()).toBe(201);
    expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBe(true);
    const book = await (await page.request.post("/api/notebooks", { data: { title: "知识图验收" } })).json();
    await page.goto("/");
    await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(book.id);
    if (status === "unverified") await page.setViewportSize({ width: 390, height: 950 });
    await page.route("**/api/static/gen/review-fixture.png", route => route.fulfill({
      contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="864"><rect width="1536" height="864" fill="#FAF9F6"/><text x="100" y="180" font-size="60">栈与队列 · 界面测试夹具</text><text x="100" y="360" font-size="44">后进先出 ≠ 先进先出</text></svg>',
    }));
    const verification = { status: status === "generation_failed" ? "unverified" : status,
      issues: status === "failed" ? ["右侧不等号被画成等号，请以文字版为准。"] : status === "unverified" ? ["图片理解服务暂不可用，连线关系尚未核对。"] : [],
    };
    const visual = { title: "栈与队列", renderer: "xiaoyunque-infographic-v1", provider: "xiaoyunque",
      image_status: status === "generation_failed" ? "fallback" : "ready", content_status: "checked", verification,
      image_url: status === "generation_failed" ? undefined : "/static/gen/review-fixture.png",
      image_error: "小云雀图片未生成成功，已保留文字版与出处，请稍后重试。", generation_attempts: status === "failed" ? 2 : 1 };
    await page.route("**/api/chat", route => route.fulfill({ contentType: "text/event-stream", body: [
      { type: "resource", resource: { id: `review-${status}`, kind: "doc", kp: "stack", title: "栈与队列·一图看懂",
        payload: { template: "one_page", markdown: "# 栈与队列\n\n后进先出 ≠ 先进先出。", one_page_visual: visual }, citations: [] } },
      { type: "done" },
    ].map(event => `data: ${JSON.stringify(event)}\n\n`).join("") }));
    await page.getByLabel("学习目标输入", { exact: true }).fill("生成栈与队列一图看懂");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const card = page.getByRole("button", { name: /栈与队列·一图看懂/ }).first();
    await expect(card).toBeVisible();
    if (await card.getAttribute("aria-expanded") === "false") await card.click();
    if (status === "generation_failed") {
      await expect(page.getByText("一图看懂图片未生成", { exact: true })).toBeVisible();
      await expect(page.getByRole("img", { name: /^一图看懂/ })).toHaveCount(0);
    } else {
      const label = status === "passed" ? "已完成图片自动核对" : status === "failed" ? "图片仍有待修正内容" : "图片已生成，仍需核对";
      await expect(page.getByText(label, { exact: true })).toBeVisible();
      const image = page.getByRole("img", { name: /^一图看懂/ });
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBe(1536);
      await expect(page.getByText("查看旧版配图", { exact: true })).toHaveCount(0);
      if (status !== "passed") await expect(page.getByText(verification.issues[0], { exact: true })).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: info.outputPath(`review-${status}.png`), fullPage: true });
  });
}
