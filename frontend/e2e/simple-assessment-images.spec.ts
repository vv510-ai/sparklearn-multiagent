import { expect, test, type Page } from "@playwright/test";

test.use({ actionTimeout: 15_000 });

async function enter(page: Page) {
  const response = await page.request.post("/api/auth/register", { data: {
    email: `image-question-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`,
    password: "Image-Question-2026!", name: "图片与简洁测评验收",
  } });
  expect(response.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBe(true);
  const book = await (await page.request.post("/api/notebooks", { data: { title: "图片与学习安排" } })).json();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: "跳过引导", exact: true }).click();
  await expect(page.getByLabel("学习目标输入", { exact: true })).toBeVisible();
  return book;
}

const picture = {
  name: "不会的一元一次方程.png", mimeType: "image/png",
  buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7WQAAAAASUVORK5CYII=", "base64"),
};

test("图片可选择、预览、移除，识别失败后保留图片和问题以便重试", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page);
  const picker = page.getByLabel("选择错题或知识点图片");
  await expect(page.getByRole("button", { name: "上传图片", exact: true })).toBeInViewport({ ratio: 1 });
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "上传图片", exact: true }).click();
  await (await chooser).setFiles(picture);
  await expect(page.getByAltText("待发送的题目图片")).toBeVisible();
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "移除图片" }).click();
  await expect(page.getByAltText("待发送的题目图片")).toHaveCount(0);
  await picker.setInputFiles({ name: "not-image.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.locator(".composer-image-error[role=alert]")).toContainText("请选择 JPG");
  await picker.setInputFiles({ name: "too-large.png", mimeType: "image/png", buffer: Buffer.alloc(4 * 1024 * 1024 + 1) });
  await expect(page.locator(".composer-image-error[role=alert]")).toContainText("4 MB");
  await picker.setInputFiles(picture);
  await page.getByLabel("学习目标输入", { exact: true }).fill("我算出 x = 7，哪里错了？");
  const received: Record<string, unknown>[] = [];
  await page.route("**/api/chat", async route => {
    received.push(route.request().postDataJSON());
    await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "没能读清图片，请换一张清晰图片。" }) });
  });
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByLabel("学习目标输入", { exact: true })).toHaveValue("我算出 x = 7，哪里错了？");
  await expect(page.getByAltText("待发送的题目图片")).toBeVisible();
  await expect(page.getByLabel("小知回答").last()).toContainText("没能读清图片");
  expect(received[0].image_base64).toMatch(/^data:image\/png;base64,/);
  expect(received[0].message).toContain("x = 7");
  await page.screenshot({ path: info.outputPath("image-retry-mobile.png") });
  await page.unroute("**/api/chat");
  // Exercise the real local API/gateway in demo mode; OCR/model accuracy is tested separately.
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  await expect(page.getByAltText("待发送的题目图片")).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".chat-user-message").last()).toContainText("图片识别内容");
  await expect(page.getByLabel("学习目标输入", { exact: true })).toBeEmpty();
  await page.screenshot({ path: info.outputPath("image-persisted.png") });
});

test("手机与电脑都能粘贴图片并仅发送图片", async ({ page }, info) => {
  await enter(page);
  for (const [width, height] of [[390, 844], [1440, 900]]) {
    await page.setViewportSize({ width, height });
    await page.getByLabel("学习目标输入", { exact: true }).evaluate((input, data) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([Uint8Array.from(atob(data), char => char.charCodeAt(0))], "粘贴的知识点.png", { type: "image/png" }));
      input.dispatchEvent(new ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true }));
    }, picture.buffer.toString("base64"));
    await expect(page.getByAltText("待发送的题目图片")).toBeVisible();
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`image-composer-${width}.png`) });
    await page.getByRole("button", { name: "移除图片" }).click();
  }
  await page.getByLabel("选择错题或知识点图片").setInputFiles(picture);
  const submitted = page.waitForRequest("**/api/chat");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const body = (await submitted).postDataJSON();
  expect(body.message).toContain("图片里的题目或知识点");
  expect(body.image_base64).toMatch(/^data:image\/png;base64,/);
  await expect(page.getByAltText("待发送的题目图片")).toHaveCount(0);
});

test("零覆盖测评先展示下一步，完整计划和来源默认收起", async ({ page }, info) => {
  const book = await enter(page);
  const survey = { notebook_id: book.id, course_key: "python", course_title: "Python 入门", goal: "独立解题与纠错",
    goals: ["独立解题与纠错"], daily_minutes: 20, study_days: [1, 3, 5] };
  const prepared = await page.request.post(`/api/notebooks/${book.id}/learning/prepare`, { data: { title: "Python 入门", course_key: "python", survey } });
  expect(prepared.ok()).toBe(true);
  const course = await prepared.json();
  let state = await (await page.request.post("/api/assessment/start", { data: { mode: "screening", survey: {
    ...survey, course_revision: course.revision, target_kps: course.outline.map((item: { id: string }) => item.id),
  } } })).json();
  for (let i = 0; state.question && i < 30; i++) {
    const response = await page.request.post(`/api/assessment/${state.id}/answers`, { data: {
      revision: state.revision, question_id: state.question.id, status: "skipped",
    } });
    expect(response.ok()).toBe(true);
    state = await response.json();
  }
  expect(state.report.coverage).toBe(0);
  await page.reload();
  const open = page.getByRole("button", { name: "打开起点测评", exact: true });
  if (!await open.isVisible()) await page.getByLabel("学习菜单", { exact: true }).click();
  await open.click();
  for (const [width, height] of [[1440, 900], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.locator(".entry-panel").evaluate(panel => panel.scrollTo(0, 0));
    await expect(page.getByRole("heading", { name: "先学一步，再逐步了解你", exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("button", { name: "开始第一项学习任务", exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.locator(".entry-report-details")).not.toHaveAttribute("open");
    await expect(page.locator(".entry-reference-details")).not.toHaveAttribute("open");
    await expect(page.getByRole("heading", { name: "你的学习起点，已经清楚了一些" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`simple-plan-${width}.png`) });
  }
  await page.locator(".entry-report-details > summary").click();
  await expect(page.getByRole("button", { name: "导出计划", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "已提交答案复盘" })).toBeVisible();
  await page.locator(".entry-reference-details > summary").click();
  await expect(page.getByRole("region", { name: "教材依据与范围" })).toBeVisible();
});
