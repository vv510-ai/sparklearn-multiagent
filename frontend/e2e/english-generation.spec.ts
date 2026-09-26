import { expect, test } from "@playwright/test";

import { openEnglish } from "./english-helpers";
import type { DictionarySource } from "../components/learning/DictionaryEvidence";

const evidence: DictionarySource = {
  status: "included", headword: "figure out", provider: "Wiktionary 社区词典 · Kaikki 提取",
  notice: "以下是部分词典义项，请结合场景对照；不代表上方 AI 解释已核验。",
  version: "english-dictionary-2026-09-26-v1", retrieved_at: "2026-09-26T11:00:00Z",
  source_url: "https://en.wiktionary.org/wiki/figure_out#English", extraction_url: "https://kaikki.org/dictionary/English/meaning/f/fi/figure%20out.jsonl",
  license: "CC BY-SA 4.0", license_url: "https://creativecommons.org/licenses/by-sa/4.0/", attribution: "Wiktionary contributors；部分义项原文摘录。",
  senses: [{ id: "figure out:0:0", pos: "verb", tags: ["informal"], definition: "To come to understand; to discover or find a solution; to deduce." }],
};

const question = { stem: "figure out 在本句中表示什么？", options: ["弄明白", "离开", "画画", "迟到"], answer: "A", explanation: "指通过思考找到办法。" };
const scene = {
  resource_id: "r_english_fixture", title: "周末计划", provenance: "原创教学场景，非真实影视台词",
  notes: "## figure out\n通过思考弄明白。", source_text: "",
  request: { words: "hesitate, awkward, figure out", scene: "朋友一起商量周末计划", goal: "影视理解与日常交流", level: "中等" },
  lines: [{ speaker: "A", text: "We can figure it out.", translation: "我们能想明白的。", timestamp: "" }],
  vocabulary: [{ word: "figure out", meaning: "弄明白", usage: "figure it out", memory: "", contrast: "", dictionary: evidence }, { word: "serendipity", meaning: "偶然发现", usage: "an unexpected discovery", memory: "", contrast: "", dictionary: { status: "not_included", headword: "serendipity" } as DictionarySource }],
  question: null as typeof question | null,
  generation: { status: "partial", message: "对话和词汇笔记已保存，可以先学习；练习暂未就绪，可单独补生成。" },
};

test("场景和词汇保留、只重试练习、恢复与手机布局", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  let saved: typeof scene | null = null;
  let sceneCalls = 0;
  let questionCalls = 0;
  await page.route("**/api/learning/english/scene/latest?*", route => route.fulfill({ json: saved }));
  await page.route("**/api/learning/english/scene", route => {
    sceneCalls++;
    if (sceneCalls > 1) return route.fulfill({ status: 503, json: { detail: "英语生成服务暂时繁忙，请稍后重试。" } });
    saved = structuredClone(scene);
    return route.fulfill({ json: saved });
  });
  await page.route("**/api/learning/english/scene/question", route => {
    questionCalls++;
    expect(route.request().postDataJSON().resource_id).toBe(scene.resource_id);
    if (questionCalls === 1) return route.fulfill({ status: 503, json: { detail: "英语生成服务额度暂时不足，请稍后再试或联系管理员。" } });
    saved = { ...saved!, question, generation: { status: "completed", message: "" } };
    return route.fulfill({ json: { question, generation: saved.generation } });
  });
  await openEnglish(page);
  await expect(page.getByRole("link", { name: "进入场景课程" })).toHaveAttribute("href", "/library#course-english-scenes");
  await expect(page.getByLabel("真实字幕或原句（可选）")).not.toBeVisible();
  await page.getByRole("button", { name: "生成场景笔记", exact: true }).click();
  await expect(page.getByRole("region", { name: "场景原句" })).toContainText("We can figure it out.");
  await page.getByRole("button", { name: "只补生成练习", exact: true }).click();
  await expect(page.getByRole("region", { name: "场景练习" }).getByRole("alert")).toContainText("额度");
  await expect(page.getByRole("region", { name: "词汇与搭配" })).toContainText("弄明白");
  await page.getByRole("button", { name: "只补生成练习", exact: true }).click();
  await page.getByRole("button", { name: "A. 弄明白", exact: true }).click();
  await page.getByRole("button", { name: "确认答案", exact: true }).click();
  await expect(page.getByText("回答正确 · 答案 A", { exact: true })).toBeVisible();
  expect(sceneCalls).toBe(1); expect(questionCalls).toBe(2);

  await page.getByLabel("想学的单词或短语").fill("clarify");
  await page.getByRole("button", { name: "生成场景笔记", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "服务暂时繁忙" })).toContainText("上次保存的场景仍保留");
  await expect(page.getByRole("region", { name: "场景原句" })).toContainText("We can figure it out.");
  await expect(page.getByLabel("想学的单词或短语")).toHaveValue("clarify");

  await page.reload();
  await page.getByRole("button", { name: /英语场景学习.*影视字幕/ }).click();
  await expect(page.getByText("已恢复本课程最近保存的场景。", { exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: "英语练习选项" })).toBeVisible();
  await page.getByRole("button", { name: "显示中文", exact: true }).click();
  await expect(page.getByText("我们能想明白的。", { exact: true })).toBeVisible();
  for (const width of [1280, 834, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("heading", { name: "周末计划", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath("english-generation-" + width + ".png"), fullPage: true });
  }
  const vocabulary = page.getByRole("region", { name: "词汇与搭配" });
  await expect(vocabulary.getByText(evidence.senses![0].definition, { exact: true })).not.toBeVisible();
  await vocabulary.getByText("查看词典原文", { exact: true }).click();
  await expect(vocabulary.getByText(evidence.senses![0].definition, { exact: true })).toBeVisible();
  await expect(vocabulary).toContainText("不代表上方 AI 解释已核验");
  await expect(vocabulary.getByRole("link", { name: "完整词条（新窗口）", exact: true })).toHaveAttribute("href", evidence.source_url!);
  await expect(vocabulary.getByRole("link", { name: "CC BY-SA 4.0", exact: true })).toHaveAttribute("href", evidence.license_url!);
  await expect(vocabulary.getByRole("link", { name: "去词典查找（新窗口）", exact: true })).toHaveAttribute("href", /search=serendipity$/);
  await expect(vocabulary).toContainText("暂无内置词典摘录");
  for (const width of [1512, 834, 390]) {
    await page.setViewportSize({ width, height: 950 });
    await vocabulary.scrollIntoViewIfNeeded();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("english-dictionary-" + width + ".png"), fullPage: true });
  }
  expect(errors).toEqual([]);
});

test("本地无模型仍可进入现成课程，上传说明可按需展开", async ({ page }) => {
  await openEnglish(page, "english-offline");
  await page.getByRole("button", { name: "工作沟通", exact: true }).click();
  await expect(page.getByLabel("想学的单词或短语")).toHaveValue("follow up, clarify, deadline");
  await page.getByText("使用自己的字幕或本地视频（可选）", { exact: true }).click();
  await expect(page.getByLabel("真实字幕或原句（可选）")).toBeVisible();
  await page.getByRole("button", { name: "生成场景笔记", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "需要可用模型" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "需要可用模型" })).not.toContainText("POST /");
  await page.getByRole("link", { name: "进入场景课程" }).click();
  await expect(page.locator("#course-english-scenes")).toContainText("英语生活场景");
});
