import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { registerLearner } from "./intake-helpers";

const NOTES = `递归课程核对讲义
递归与更小问题
递归函数在解决问题时调用自身，把原问题变为规模更小的同类问题。每次调用都有自己的参数和局部变量。
终止条件
递归必须有终止条件，并且每次递归要向终止条件靠近。只写了终止条件却不缩小问题，仍可能无限递归。
阶乘例子
阶乘满足 n! = n × (n-1)!，零的阶乘是1。计算3的阶乘，可以先计算2的阶乘，再计算1和0的阶乘，然后逐层返回，最终得到6。
易错点
不能把有终止条件等同于一定能结束，还要检查参数变化。返回值要随着调用逐层传回。调用层数过多也会消耗栈空间。`;

test("已有课程上传递归资料并核对理解检查题", async ({ page }, info) => {
  test.skip(process.env.PLAYWRIGHT_REAL_MODE !== "1", "真实模型验收需显式启用");
  test.setTimeout(420_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), b => b.click());
  expect((await (await page.request.get("/api/health")).json()).demo_mode).toBe(false);
  await registerLearner(page, "evidence-persistence");
  await page.getByRole("checkbox", { name: /看懂手头的课件或教材/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "数据结构与算法", exact: true }).check();
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  await page.getByRole("button", { name: "返回对话", exact: true }).click();
  const uploadStarted = Date.now();
  const uploadedResponse = page.waitForResponse(r => r.url().endsWith("/api/knowledge/upload"));
  const picker = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "添加学习资料", exact: true }).click();
  await (await picker).setFiles({ name: "引用核对递归讲义.txt", mimeType: "text/plain", buffer: Buffer.from(NOTES) });
  const uploaded = await uploadedResponse;
  await writeFile(info.outputPath("upload-timings.json"), JSON.stringify({ elapsed_ms: Date.now() - uploadStarted, ...(await uploaded.json()).timings }, null, 2));
  const source = page.getByRole("button", { name: /引用核对递归讲义/ });
  await expect(source).toBeEnabled({ timeout: 150_000 });
  if (!(await source.getAttribute("class"))?.includes("is-selected")) await source.click();
  const builtin = page.getByRole("button", { name: /数据结构基础讲义/ });
  if ((await builtin.getAttribute("class"))?.includes("is-selected")) await builtin.click();
  await page.getByLabel("对话选项", { exact: true }).click();
  await page.getByRole("combobox", { name: "回答依据" }).selectOption("strict");
  await page.getByLabel("对话选项", { exact: true }).press("Escape");
  const response = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await page.getByLabel("学习目标输入", { exact: true }).fill("请用上传讲义解释递归，重点说明终止条件和缩小问题的关系，并保留引用编号。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const result = await response;
  const request = result.request().postDataJSON();
  expect(result.status()).toBe(200);
  await expect(page.getByRole("button", { name: "停止等待", exact: true })).toHaveCount(0, { timeout: 180_000 });
  const answer = page.locator('[aria-label="小知回答"]').last();
  await expect(answer).toContainText("未逐项核验");
  await expect(answer.getByRole("link", { name: /查看引用/ }).first()).toBeVisible();
  const link = answer.getByRole("link", { name: /查看引用/ }).first();
  const href = await link.getAttribute("href");
  await link.click();
  await expect(page.locator(href!)).toHaveAttribute("open", "");
  const before = await page.locator(href!).innerText();
  expect(before).toContain("引用核对递归讲义");
  const saved = await (await page.request.get(`/api/notebooks/${request.notebook_id}?user_id=session_user`)).json();
  const message = saved.messages.filter((m: { role: string }) => m.role === "assistant").at(-1);
  expect(message.source_evidence.length).toBeGreaterThan(0);
  const compact = (s: string) => s.replace(/\s+/g, "");
  for (const item of message.source_evidence) expect(compact(NOTES)).toContain(compact(item.excerpt));
  const body = await result.text().catch(() => "");
  if (body) {
    const events = body.split("\n").filter(s => s.startsWith("data: ")).map(s => JSON.parse(s.slice(6)));
    expect(events.some(e => e.stage === "model_route")).toBe(true);
    const grounding = events.filter(e => e.stage === "grounding").at(-1)?.grounding;
    expect(grounding?.verification).toBe("citation_only");
    expect(grounding?.grounded).toBe(false);
  }
  await page.screenshot({ path: info.outputPath("source-open.png"), fullPage: true });
  await page.reload();
  await page.addLocatorHandler(page.getByRole("button", { name: "返回对话", exact: true }), b => b.click());
  await page.getByLabel("对话选项", { exact: true }).click();
  await expect(page.getByRole("combobox", { name: "回答依据" })).toHaveValue("strict");
  await page.getByLabel("对话选项", { exact: true }).press("Escape");
  const reloaded = page.locator('[aria-label="小知回答"]').last();
  await reloaded.getByRole("link", { name: /查看引用/ }).first().click();
  expect(await page.locator(href!).innerText()).toBe(before);
  await writeFile(info.outputPath("saved-evidence.json"), JSON.stringify({ request, message, events: body }, null, 2));
  await page.screenshot({ path: info.outputPath("source-after-reload.png"), fullPage: true });
  const checked = await page.request.post("/api/tutor", { timeout: 180_000, data: {
    user_id: "session_user", notebook_id: request.notebook_id, source_ids: request.source_ids, source_policy: "strict",
    question: "根据上传递归讲义，用两句话解释终止条件，再给一道单选理解检查题。假设初始参数 n=3 且 n 为整数，问哪种方案不能终止；在每个选项里同时写明停止条件和参数变化。先不要给答案。",
  }});
  expect(checked.ok()).toBe(true);
  const events = (await checked.text()).split("\n").filter(line => line.startsWith("data: ")).map(line => JSON.parse(line.slice(6)));
  expect(events.filter(e => e.type === "error")).toEqual([]);
  const review = events.find(e => e.stage === "question_quality");
  expect(review).toBeTruthy();
  const content = events.filter(e => e.type === "token").map(e => e.delta || "").join("");
  await writeFile(info.outputPath("actual-tutor-question.json"), JSON.stringify({ review, content, routes: events.filter(e => e.stage === "model_route") }, null, 2));

});
