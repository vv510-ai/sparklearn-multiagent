import { expect, test } from "@playwright/test";
import { completeIntake, registerLearner } from "./intake-helpers";
import type { SparkEvent } from "../lib/types";

test("生成时立即反馈并展示真实阶段，完成、停止和失败都清除等待状态", async ({ page }) => {
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), async b => { await b.click(); });
  await registerLearner(page, "generation-progress");
  await completeIntake(page);
  await page.getByRole("button", { name: "返回对话", exact: true }).click();
  await page.getByLabel("学习目标输入", { exact: true }).fill("二叉树是什么？");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator('[aria-label="小知回答"]').last()).toBeVisible();
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  // A controlled transport tests UI transitions, not model quality or live speed.
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = async (...args) => {
      if (!String(args[0]).endsWith("/api/resources/generate")) return original(...args);
      const stream = new ReadableStream({ start(controller) {
        const host = window as unknown as { pushGenerationEvent: (event: unknown) => void };
        host.pushGenerationEvent = event => controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
        args[1]?.signal?.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")));
      } });
      return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
    };
  });
  const push = async (event: SparkEvent) => page.evaluate(event => {
    (window as unknown as { pushGenerationEvent: (event: unknown) => void }).pushGenerationEvent(event);
  }, event);
  const start = async () => {
    await page.getByRole("button", { name: /^互动讲解/ }).click();
    await expect(page.getByRole("status", { name: "生成进度" })).toHaveText("正在准备本次学习内容…", { timeout: 15000 });
  };
  await start();
  for (const [stage, text] of [["resource_content", "正在整理短讲解…"], ["resource_check", "正在检查内容与引用…"], ["resource_audio", "正在生成语音…"]]) {
    await push({ type: "progress", agent: "doc", stage, text });
    await expect(page.getByRole("status", { name: "生成进度" })).toHaveText(text);
  }
  await push({ type: "progress", agent: "media", stage: "tts", detail: "internal provider trace" });
  await expect(page.getByRole("status", { name: "生成进度" })).toHaveText("正在生成语音…");
  await push({ type: "resource", resource: { id: "progress-contract", kind: "doc", kp: "binary_tree", title: "二叉树·互动讲解", payload: { template: "interactive_audio", markdown: "二叉树每个节点最多有两个孩子。" }, citations: [] } });
  await expect(page.getByRole("status", { name: "生成进度" })).toHaveCount(0);
  await push({ type: "summary", text: "互动讲解已整理好。" });
  await push({ type: "done" });
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  await expect(page.locator('[aria-label="小知回答"]').last()).toHaveText("互动讲解已整理好。");
  await start();
  await page.getByRole("button", { name: "停止生成", exact: true }).click();
  await expect(page.getByRole("status", { name: "生成进度" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  await start();
  await push({ type: "error", detail: "测试服务暂不可用" });
  await expect(page.getByRole("status", { name: "生成进度" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  await expect(page.locator('[aria-label="小知回答"]').last()).toContainText("测试服务暂不可用");
});
