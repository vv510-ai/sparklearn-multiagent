import { expect, test } from "@playwright/test";
import { registerLearner } from "./intake-helpers";

test("工作台可直接选经典课程，失败续建不重复，切换课程保留各自范围", async ({ page }, info) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await registerLearner(page, "course-library");
  await page.getByRole("button", { name: "先进入，稍后继续", exact: true }).click();
  await expect(page.getByRole("button", { name: "学习首页", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "减少透明效果", exact: true })).toHaveCount(0);
  await expect(page.getByText("数据结构基础讲义", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "新建课程", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程", exact: true });
  for (const name of ["数据结构与算法", "Python 入门", "高等数学入门", "自定义学习主题", "上传课本生成课程"]) {
    await expect(dialog.getByRole("radio", { name, exact: true })).toBeVisible();
  }
  await dialog.getByRole("radio", { name: "Python 入门", exact: true }).check();
  await expect(dialog.getByLabel("课程名称或学习主题")).toHaveValue("Python 入门");
  await page.screenshot({ path: info.outputPath("course-picker-desktop.png"), fullPage: true });
  let failed = false;
  await page.route("**/api/notebooks/*/learning/prepare", async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "课程准备暂时中断，请重试" }) }); }
    else await route.continue();
  });
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("课程准备暂时中断");
  const before = (await (await page.request.get("/api/notebooks?user_id=session_user")).json()).items;
  expect(before).toHaveLength(1);
  await dialog.getByRole("button", { name: "继续准备课程", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const after = (await (await page.request.get("/api/notebooks?user_id=session_user")).json()).items;
  expect(after).toHaveLength(1);
  expect(after[0].id).toBe(before[0].id);
  const pythonId = after[0].id;
  const python = (await (await page.request.get(`/api/notebooks/${pythonId}/learning`)).json()).course;
  expect(python.kind).toBe("python");
  expect(python.question_count).toBe(12);
  await expect(page.locator(".course-source-summary").first()).toContainText("Python 入门");
  await expect(page.getByRole("heading", { name: "你希望小知先帮你完成什么？", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "新建课程", exact: true }).click();
  await dialog.getByRole("radio", { name: "高等数学入门", exact: true }).check();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("course-picker-mobile.png"), fullPage: true });
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const books = (await (await page.request.get("/api/notebooks?user_id=session_user")).json()).items;
  expect(books).toHaveLength(2);
  const mathsId = books.find((b: { id: string }) => b.id !== pythonId).id;
  expect((await (await page.request.get(`/api/notebooks/${mathsId}/learning`)).json()).course.kind).toBe("calculus");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(pythonId);
  await expect(page.locator(".course-source-summary").first()).toContainText("Python 入门");
  await expect(page.getByText("数据结构基础讲义", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("python-workspace.png"), fullPage: true });
});

test("新建入口上传课本后真实生成独立课程，资料在刷新后仍绑定", async ({ page }, info) => {
  test.skip(process.env.PLAYWRIGHT_REAL_MODE !== "1", "需线上真实模型生成课程");
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerLearner(page, "course-upload");
  await page.getByRole("button", { name: "先进入，稍后继续", exact: true }).click();
  await page.getByRole("button", { name: "上传课本 / 自定义课程", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程", exact: true });
  await dialog.getByRole("radio", { name: "上传课本生成课程", exact: true }).check();
  await dialog.getByLabel("课程名称或学习主题").fill("植物与生态入门");
  await dialog.getByLabel("上传课程课本", { exact: true }).setInputFiles({ name: "生态课本.txt", mimeType: "text/plain", buffer: Buffer.from(
    "生产者：绿色植物通过光合作用把太阳能转化为有机物中的化学能，为生态系统提供有机物。消费者：兔吃草，狐吃兔，它们靠摄食获得有机物和能量。分解者：真菌和细菌分解遗体及排泄物，使有机物变为无机物并返回环境。\n食物链：草到兔到狐，箭头表示从被吃者到捕食者的能量传递方向。能量沿食物链单向流动、逐级递减，部分转化为热散失。分解者通常不列在捕食食物链中。\n物质循环：碳元素在生物与无机环境间循环。植物固定二氧化碳，生物呼吸和分解作用将二氧化碳释放回环境。物质可循环，能量不能循环。\n应用辨析：池塘藻类是生产者，吃藻的小动物是消费者，分解枯叶的真菌是分解者。角色由获取有机物的方式决定，不能只看体型大小。") });
  await page.screenshot({ path: info.outputPath("textbook-selected.png"), fullPage: true });
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  await expect(dialog).toHaveCount(0, { timeout: 150_000 });
  const books = (await (await page.request.get("/api/notebooks?user_id=session_user")).json()).items;
  expect(books).toHaveLength(1);
  const id = books[0].id;
  const learning = (await (await page.request.get(`/api/notebooks/${id}/learning`)).json());
  expect(learning.course.kind).toBe("generated");
  expect(learning.course.source_ids).toHaveLength(1);
  expect(learning.course.question_count).toBeGreaterThanOrEqual(9);
  expect(learning.course.sources[0].sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(learning.course.outline.map((n: { name: string }) => n.name).join(" ")).not.toContain("二叉树");
  await expect(page.locator(".course-source-summary").first()).toContainText("已绑定 1 份上传资料");
  await page.reload();
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(id);
  await expect(page.locator(".course-source-summary").first()).toContainText("植物与生态入门");
  const sources = (await (await page.request.get(`/api/knowledge/sources?user_id=session_user&notebook_id=${id}`)).json()).items;
  expect(sources.map((s: { id: string }) => s.id)).toEqual(learning.course.source_ids);
  await page.screenshot({ path: info.outputPath("material-course-restored.png"), fullPage: true });
});
