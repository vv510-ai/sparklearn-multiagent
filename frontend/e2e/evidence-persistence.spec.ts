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
  await page.locator('.intake-upload input[type="file"]').setInputFiles({ name: "引用核对生态讲义.txt", mimeType: "text/plain", buffer: Buffer.from(NOTES) });
  await expect(page.getByText("解析完成，已选中的资料将用于准备课程范围与起点题。", { exact: true })).toBeVisible();
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  await page.getByRole("button", { name: "返回对话", exact: true }).click();
  await page.getByRole("combobox", { name: "回答依据" }).selectOption("strict");
  const response = page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await page.getByLabel("学习目标输入", { exact: true }).fill("请用上传讲义解释能量流动和物质循环的区别，举草、兔、狐的例子，并保留引用编号。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const result = await response;
  const request = result.request().postDataJSON();
  expect(result.status()).toBe(200);
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0, { timeout: 180_000 });
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
  if (await page.getByRole("button", { name: "返回对话", exact: true }).count()) await page.getByRole("button", { name: "返回对话", exact: true }).click();
  const reloaded = page.locator('[aria-label="小知回答"]').last();
  await reloaded.getByRole("link", { name: /查看引用/ }).first().click();
  expect(await page.locator(href!).innerText()).toBe(before);
  await writeFile(info.outputPath("saved-evidence.json"), JSON.stringify({ request, message, events: body }, null, 2));
  await page.screenshot({ path: info.outputPath("source-after-reload.png"), fullPage: true });
});
