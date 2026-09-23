import { expect, test } from "@playwright/test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "../components/chat/Markdown";
import ResourceCard from "../components/resource/ResourceCard";
import type { ResourceItem } from "../lib/types";
import SourceEvidence from "../components/chat/SourceEvidence";

const evidence = [{ index: 2, citation: "同一份讲义 p.1", excerpt: "递归必须有终止条件。<script>不要执行</script>" },
  { index: 5, citation: "同一份讲义 p.1", excerpt: "每次调用向终止条件靠近。" }];

test("稀疏编号定位正确片段，同来源不合并，原文按文本展示", async ({ page }) => {
  await page.setContent(renderToStaticMarkup(React.createElement(React.Fragment, null,
    React.createElement(Markdown, { text: "终止条件[^2]；缩小问题[^5]。", citeBase: "answer", evidence }),
    React.createElement(SourceEvidence, { citeBase: "answer", evidence }))));
  await expect(page.getByRole("link", { name: "查看引用 2 原文" })).toHaveAttribute("href", "#answer-source-2");
  await expect(page.getByRole("link", { name: "查看引用 5 原文" })).toHaveAttribute("href", "#answer-source-5");
  await expect(page.locator("details")).toHaveCount(2);
  await page.locator("#answer-source-2 summary").click();
  await expect(page.locator("#answer-source-2")).toContainText("递归必须有终止条件。<script>不要执行</script>");
  await expect(page.locator("script")).toHaveCount(0);
});

test("历史引用没有原文时明确缺失，不把字符串列表重编号", async ({ page }) => {
  await page.setContent(renderToStaticMarkup(React.createElement(Markdown, {
    text: "结论[^2]", citeBase: "old", citations: ["历史讲义 p.1"],
  })));
  await expect(page.getByRole("link")).toHaveCount(0);
  await expect(page.locator("body")).toContainText("2：原文未保存");
});


test("同一资源隐藏与可见副本的引用锚点互不冲突", async ({ page }) => {
  const r: ResourceItem = { id: "same-resource", kind: "doc", kp: "recursion", title: "递归",
    payload: { markdown: "终止条件[^2]", source_evidence: evidence }, citations: ["同一份讲义"] };
  await page.setContent(renderToStaticMarkup(React.createElement(React.Fragment, null,
    React.createElement("div", { hidden: true }, React.createElement(ResourceCard, { r, defaultOpen: true })),
    React.createElement("div", { id: "visible" }, React.createElement(ResourceCard, { r, defaultOpen: true })))));
  const ids = await page.locator("details[id]").evaluateAll(nodes => nodes.map(n => n.id));
  expect(new Set(ids).size).toBe(ids.length);
  const link = page.locator("#visible").getByRole("link", { name: "查看引用 2 原文" });
  const href = await link.getAttribute("href");
  await link.click();
  await expect(page.locator(`#visible ${href} summary`)).toBeVisible();
  await page.locator(`#visible ${href} summary`).click();
  await expect(page.locator(href!)).toHaveAttribute("open", "");
  await expect(page.locator("div[hidden] details[open]")).toHaveCount(0);
});
