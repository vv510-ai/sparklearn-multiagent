import { expect as baseExpect, test, type Page } from "@playwright/test";

const expect = baseExpect.configure({ timeout: 15_000 });
test.use({ actionTimeout: 15_000 });

async function enter(page: Page) {
  const registration = await page.request.post("/api/auth/register", { data: {
    email: `glass-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`,
    password: "Glass-acceptance-2026!", name: "玻璃界面验收",
  } });
  expect(registration.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBe(true);
  expect((await page.request.post("/api/notebooks", { data: { title: "数据结构与算法" } })).status()).toBe(201);
  // Stable content for surface inspection, not a model-quality acceptance.
  await page.route("**/api/chat", route => route.fulfill({ contentType: "text/event-stream", body:
    [{ type: "token", delta: "## 栈与队列\n\n**栈：后进先出。** 例如叠放的书，最后放上的最先取走。\n\n**队列：先进先出。** 例如排队买票，先到的人先办理。\n\n试一试：依次放入 A、B、C，栈会先取出哪个？" }, { type: "done" }]
      .map(event => `data: ${JSON.stringify(event)}\n\n`).join("") }));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "跳过引导", exact: true }).click();
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  await page.getByLabel("学习目标输入", { exact: true }).fill("请举例说明栈和队列的区别。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByLabel("小知回答")).toContainText("先进先出");
}

async function surfaces(page: Page) {
  return page.evaluate(() => {
    const read = (selector: string) => {
      const style = getComputedStyle(document.querySelector(selector)!);
      return { image: style.backgroundImage, color: style.backgroundColor, blur: style.backdropFilter, shadow: style.boxShadow };
    };
    return {
      app: read(".notebook-app"), header: read(".notebook-topbar"), main: read(".notebook-main-column"),
      footer: read(".notebook-chat-footer"), composer: read(".notebook-composer"),
      overflow: document.documentElement.scrollWidth > innerWidth,
    };
  });
}

test("各端保留彩色玻璃，手机布局与长答案输入不退回旧版", async ({ page }, info) => {
  await enter(page);
  for (const [width, height] of [[320, 740], [390, 844], [768, 1024], [1024, 768], [1440, 900], [1920, 1080]]) {
    await page.setViewportSize({ width, height });
    const material = await surfaces(page);
    expect(material.app.image).toContain("gradient");
    expect(material.header.image).toContain("gradient");
    expect(material.header.blur, JSON.stringify(material)).toContain("blur");
    expect(material.main.color).toBe("rgba(248, 253, 251, 0.66)");
    expect(material.main.blur).toContain("blur");
    expect(material.footer.blur).toContain("blur");
    expect(material.composer.blur).toContain("blur");
    expect(material.composer.color).toBe("rgba(248, 253, 251, 0.66)");
    expect(material.overflow).toBe(false);
    await expect(page.locator(".notebook-mobile-nav, .learning-context-strip, .notebook-chat-header")).toHaveCount(0);
    const input = page.getByLabel("学习目标输入", { exact: true });
    await expect(input).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport({ ratio: 1 });
    if (width < 900) {
      expect((await page.locator(".notebook-topbar").boundingBox())!.height).toBe(56);
      expect((await input.boundingBox())!.width).toBeGreaterThan(width - 60);
    }
    await page.screenshot({ path: info.outputPath(`glass-${width}x${height}.png`) });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const draft = "我的答案与推理过程。\n".repeat(12);
  await page.getByLabel("学习目标输入", { exact: true }).fill(draft);
  await page.getByRole("button", { name: "展开编辑", exact: true }).click();
  await expect(page.getByLabel("展开的消息编辑器")).toHaveValue(draft);
  await page.getByRole("dialog", { name: "编辑消息", exact: true }).getByRole("button", { name: "返回学习" }).click();
  await expect(page.getByLabel("学习目标输入", { exact: true })).toHaveValue(draft);
});

test("减少透明和增强对比度仍使用不透明可读表面", async ({ page }) => {
  await enter(page);
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ contrast: "more" });
    let material = await surfaces(page);
    expect(material.app.image).toBe("none");
    expect(material.main.blur).toBe("none");
    expect(material.composer.blur).toBe("none");
    expect(material.main.color).toMatch(/^rgb\(/);
    expect(material.composer.color).toMatch(/^rgb\(/);
    await page.emulateMedia({ contrast: "no-preference" });
    await page.locator(".notebook-app").evaluate(el => el.setAttribute("data-transparency", "reduced"));
    material = await surfaces(page);
    expect(material.app.image).toBe("none");
    expect(material.header.blur).toBe("none");
    expect(material.composer.blur).toBe("none");
    await page.locator(".notebook-app").evaluate(el => el.removeAttribute("data-transparency"));
  }
});
