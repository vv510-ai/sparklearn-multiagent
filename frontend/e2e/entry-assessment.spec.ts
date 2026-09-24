import { expect, test } from "@playwright/test";
import { completeIntake } from "./intake-helpers";

test("起点测评可续答，并生成计划、资料与可预览的网课", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1512, height: 982 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const marker = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("起点功能验收");
  await page
    .getByPlaceholder("you@example.com")
    .fill(`entry-e2e-${marker}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Entry-E2E-2026!pass");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await completeIntake(page, "foundation");
  await expect(page.getByText("第一次使用？先试一下怎么回答（不计分）", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "起点测评与学习计划" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("assessment-desktop.png"),
    fullPage: true,
  });
  const answer = async (index: number) => {
    const radios = page.locator(".entry-options input");
    await radios.first().check();
    // The optional confidence controls stay out of the primary answer flow.
    if (!(await page.locator(".assessment-confidence").evaluate(el => (el as HTMLDetailsElement).open)))
      await page.locator(".assessment-confidence summary").click();
    await page.getByRole("button", { name: "很确定", exact: true }).click();
    await page.getByRole("button", { name: "提交，继续下一题" }).click();
    if (index < 18)
      await expect(
        page.getByText(`已提交 ${index} 题 / 最多 22 题`, { exact: true }),
      ).toBeVisible();
  };
  await answer(1);
  await answer(2);
  await page.getByRole("button", { name: "暂停，稍后继续" }).click();
  await page.reload();
  await page.getByRole("button", { name: "打开起点测评", exact: true }).click();
  await expect(
    page.getByText("已提交 2 题 / 最多 22 题", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("assessment-mobile.png"),
    fullPage: true,
  });
  for (let i = 3; i <= 18; i++) await answer(i);
  await expect(
    page.getByRole("heading", { name: /你的学习起点，已经清楚了一些|先学一步，再逐步了解你/ }),
  ).toBeVisible();
  await page.locator(".entry-report-details > summary").click();
  await expect(page.locator(".entry-skill")).toHaveCount(6);
  await expect(page.locator(".entry-material").first()).toBeVisible();
  await page.setViewportSize({ width: 1512, height: 982 });
  await page.screenshot({
    path: testInfo.outputPath("assessment-results.png"),
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出计划" }).click();
  const downloaded = await downloadPromise;
  expect(downloaded.suggestedFilename()).toContain("学习计划.md");
  await page.getByRole("button", { name: "找对应网课" }).first().click();
  await expect(
    page.getByRole("heading", { name: "找你想学的课程" }),
  ).toBeVisible();
  await expect(page.locator(".course-card").first()).toBeVisible();
  await expect(page.locator(".course-player iframe")).toHaveCount(0);
  // Isolate the provider: verify click-to-load embedding, not Bilibili playback.
  await page.route("https://player.bilibili.com/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<p>Official player contract fixture</p>",
    }),
  );
  await page
    .getByRole("button", { name: /^预览 / })
    .first()
    .click();
  await expect(page.locator(".course-player iframe")).toHaveAttribute(
    "src",
    /https:\/\/player\.bilibili\.com\/player\.html\?.*autoplay=0/,
  );
  await page.getByRole("button", { name: "关闭课程预览" }).click();
  await expect(page.locator(".course-player iframe")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "去 B 站观看" }).first(),
  ).toHaveAttribute("href", /^https:\/\/www\.bilibili\.com\/video\/BV/);
  await page.screenshot({
    path: testInfo.outputPath("courses-desktop.png"),
    fullPage: true,
  });
  await page.getByLabel("搜索课程", {exact: true}).fill("不存在的课程xyz");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "暂未找到匹配课程" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "B 站全站搜索" }),
  ).toHaveAttribute("href", /keyword=/);
  await page.reload();
  await page.getByRole("button", { name: "打开起点测评", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /你的学习起点，已经清楚了一些|先学一步，再逐步了解你/ }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
