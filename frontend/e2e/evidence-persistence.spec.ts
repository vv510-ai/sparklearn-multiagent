import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { registerLearner } from "./intake-helpers";

const NOTES = `生态学课程验收资料
生产者与消费者
绿色植物通过光合作用把太阳能转化为有机物中的化学能。消费者通过摄食其他生物获得有机物和能量。分解者通过分解遗体和排泄物，把有机物转化为无机物。
能量流动
在草、兔、狐组成的食物链中，能量从草流向兔，再流向狐。能量单向流动并逐级递减，部分以热的形式散失，不能循环利用。兔不是生产者。
物质循环
碳等元素在生物与无机环境之间循环。光合作用固定二氧化碳，呼吸和分解释放二氧化碳。不要把能量流动与物质循环混同。
判读练习
池塘中藻类是生产者，吃藻类的小动物是消费者，分解枯叶的真菌是分解者。判断角色要看获得有机物的方式。`;

test("上传资料的答疑引用可以点开，刷新后保留相同原文", async ({ page }, info) => {
  test.skip(process.env.PLAYWRIGHT_REAL_MODE !== "1", "真实模型验收需显式启用");
  test.setTimeout(420_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), b => b.click());
  expect((await (await page.request.get("/api/health")).json()).demo_mode).toBe(false);
  await registerLearner(page, "evidence-persistence");
  await page.getByRole("checkbox", { name: /看懂手头的课件或教材/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "其他课程或主题", exact: true }).check();
  await page.getByLabel("课程或学习主题", { exact: true }).fill("生态学入门");
  const uploadStarted = Date.now();
  const uploadResponse = page.waitForResponse(r => r.url().endsWith("/api/knowledge/upload") && r.request().method() === "POST");
  await page.locator('.intake-upload input[type="file"]').setInputFiles({ name: "引用核对生态讲义.txt", mimeType: "text/plain", buffer: Buffer.from(NOTES) });
  await expect(page.getByText("解析完成，已选中的资料将用于准备课程范围与起点题。", { exact: true })).toBeVisible();
  const uploaded = await uploadResponse;
  const uploadResult = await uploaded.json();
  const uploadMs = Date.now() - uploadStarted;
  await writeFile(info.outputPath("upload-timings.json"), JSON.stringify({ status: uploaded.status(), elapsed_ms: uploadMs, timings: uploadResult.timings }, null, 2));
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "继续", exact: true }).click();
  const prepareStarted = Date.now();
  const preparedResponse = page.waitForResponse(r => r.url().endsWith("/learning/prepare") && r.request().method() === "POST", { timeout: 150_000 });
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  const prepared = await preparedResponse;
  const preparedBody = await prepared.json();
  await writeFile(info.outputPath("prepared-course.json"), JSON.stringify({ status: prepared.status(), failure: prepared.headers()["x-learning-failure"], validation: prepared.headers()["x-learning-validation"], stage: prepared.headers()["x-learning-stage"], timings: prepared.headers()["x-learning-timings"], elapsed_ms: Date.now() - prepareStarted, course: preparedBody }, null, 2));
  expect(prepared.ok(), JSON.stringify(preparedBody)).toBe(true);
  expect(preparedBody.outline.length).toBeGreaterThan(0);
  expect(preparedBody.quality_review).toEqual({ verification: "model_review", reviewed_questions: preparedBody.question_count });
  await expect(page.getByRole("region", { name: "本次学习范围" })).toContainText(preparedBody.coverage_note);
  await page.screenshot({ path: info.outputPath("confirmed-scope.png"), fullPage: true });
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  await page.getByRole("button", { name: "返回对话", exact: true }).click();
  await page.getByLabel("对话选项", { exact: true }).click();
  await page.getByRole("combobox", { name: "回答依据" }).selectOption("strict");
  await page.getByLabel("对话选项", { exact: true }).press("Escape");
  const response = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await page.getByLabel("学习目标输入", { exact: true }).fill("请用上传讲义解释能量流动和物质循环的区别，举草、兔、狐的例子，并保留引用编号。");
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
  expect(before).toContain("引用核对生态讲义.txt");
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
  // Finish only this disposable test account's check to inspect actual generated keys.
  let assessment = (await (await page.request.get(`/api/assessment?notebook_id=${request.notebook_id}`)).json()).assessment;
  const questions = [];
  for (let i = 0; assessment?.question && i < 20; i++) {
    questions.push(assessment.question);
    const submitted = await page.request.post(`/api/assessment/${assessment.id}/answers`, { data: {
      revision: assessment.revision, question_id: assessment.question.id, status: "dont_know",
    }});
    expect(submitted.ok()).toBe(true);
    assessment = await submitted.json();
  }
  expect(assessment.question).toBeNull();
  await writeFile(info.outputPath("actual-question-review.json"), JSON.stringify({ questions, report: assessment.report }, null, 2));
  const singles = new Set(questions.filter(q => q.type === "single").map(q => q.id));
  const singleKeys = assessment.report.explanations.filter((q: { id: string }) => singles.has(q.id)).map((q: { answer: string }) => q.answer.charAt(0));
  expect(singleKeys.length).toBe(questions.length / 3 * 2);
  expect(new Set(singleKeys).size).toBeGreaterThan(1);

});
