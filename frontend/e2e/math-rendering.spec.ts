import { expect, test } from "@playwright/test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import path from "node:path";
import Markdown from "../components/chat/Markdown";
import MathText from "../components/chat/MathText";
import AnswerChoices from "../components/chat/AnswerChoices";
import AssessmentReview from "../components/assessment/AssessmentReview";
import type { Assessment } from "../lib/assessment";

// Component rendering regressions: these fixtures do not call or mock an LLM.
const render = (text: string) => renderToStaticMarkup(React.createElement(Markdown, { text, allowCodeBlocks: true }));
const katexDir = path.join(__dirname, "../node_modules/katex/dist");
const katexCss = readFileSync(path.join(katexDir, "katex.min.css"), "utf8").replace(/url\((fonts\/[^)]+)\)/g,
  (_, font: string) => `url(data:font/woff2;base64,${readFileSync(path.join(katexDir, font)).toString("base64")})`);
const appCss = readFileSync(path.join(__dirname, "../app/globals.css"), "utf8");
const mathCss = appCss.slice(appCss.indexOf(".math-content {"), appCss.indexOf(".prose-spark {"));

test("反馈原文的极限、分数、积分和旧题上下标都生成公式", async ({ page }) => {
  await page.setContent(render(String.raw`求 $\lim_{x\to2}f(x)$ 不等于求 $f(2)$。$\frac{x^2-4}{x-2}$ 在 $x=2$ 处无定义，但极限是 4。

$$
\int_0^1 2x\,\mathrm{d}x=1
$$`) + renderToStaticMarkup(React.createElement(MathText, { text: "∫₀¹ 2x dx 的值是？∫ₐᵃ f(x)dx = 0" })));
  await expect(page.locator(".katex")).toHaveCount(7);
  await expect(page.locator(".katex-display")).toHaveCount(1);
  await expect(page.locator(".katex-error")).toHaveCount(0);
  await expect(page.locator("math")).toHaveCount(7);
  await expect(page.locator("annotation").last()).toHaveText(String.raw`\int_{a}^{a} f(x)\,\mathrm{d}x`);
});

test("金额、代码、链接保留原文；未闭合与无效公式不使页面崩溃", async ({ page }) => {
  const code = String.raw`$\frac{x}{2}$`;
  await page.setContent(render("价格 $5 和 $10；单价 \\$3。\n\n`" + code + "`\n\n```python\n" + code + "\n```\n\n[资料](https://example.com)\n\n未完成 $\\frac{x}\n\n$\\frac{$\n\n后续文字可读。"));
  await expect(page.locator("body")).toContainText("价格 $5 和 $10；单价 $3。");
  await expect(page.locator("code")).toHaveText([code, code]);
  await expect(page.getByRole("link", { name: "资料" })).toHaveAttribute("href", "https://example.com");
  await expect(page.locator(".katex-error")).toHaveCount(1);
  await expect(page.locator("body")).toContainText("后续文字可读。");
  await page.setContent(render(String.raw`$\frac{x}{2}$`));
  await expect(page.locator(".katex")).toHaveCount(1);
});

test("公式不能创建外部图片、脚本或可点击的危险链接", async ({ page }) => {
  await page.setContent(render(String.raw`$\href{javascript:alert(1)}{x}$ $\includegraphics{https://example.com/track.png}$ <script>alert(1)</script>`));
  await expect(page.locator("img, script, a")).toHaveCount(0);
});

test("题目只解释公式，Python 乘号、数组、原有段落与代码示例保持原样", async ({ page }) => {
  const text = "a*b*c\n\n原文 [1, 2] 和 `value`；代码 `$x^2$`";
  await page.setContent(renderToStaticMarkup(React.createElement(MathText, { text })));
  expect(await page.locator(".math-text").textContent()).toBe(text);
  await expect(page.locator("em, code, .katex")).toHaveCount(0);
});

test("复盘中已保存的本人回答与参考答案同时显示公式", async ({ page }) => {
  const formula = String.raw`$\frac{x^3}{3}$`;
  const report = { skills: [], explanations: [{ id: "saved-answer", stem: "求一个原函数", options: [formula],
    learner_answer: `A. ${formula}`, answer: `A. ${formula}`, explain: "求导可核对", correct: true,
  }] } as unknown as NonNullable<Assessment["report"]>;
  await page.setContent(renderToStaticMarkup(React.createElement(AssessmentReview, { report, onLearn: () => {} })));
  await expect(page.locator("p").filter({ hasText: "你当时的回答：" }).locator(".katex")).toHaveCount(1);
  await expect(page.locator("p").filter({ hasText: "参考答案：" }).locator(".katex")).toHaveCount(1);
});

for (const width of [1440, 390]) test(`${width}px：长公式在自身区域滚动，页面不横向溢出`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 });
  const formula = Array.from({ length: 25 }, (_, i) => `x_{${i}}`).join("+");
  await page.setContent(`<main style="max-width:760px;margin:24px auto;padding:16px"><h2>极限、积分与分数</h2>${render(String.raw`$\lim_{x\to 0}\frac{\sin x}{x}=1$` + "\n\n$$\n" + formula + "\n$$")}</main>`);
  await page.addStyleTag({ content: katexCss + mathCss });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator(".katex-display").evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`formulas-${width}.png`) });
});


test("对话快捷选项也渲染公式，纯文本围栏中的推导仍可见", async ({ page }) => {
  await page.setContent(renderToStaticMarkup(React.createElement(AnswerChoices, {
    text: "单选：哪个终止条件？\nA. $n = 0$\nB. $n-1$", disabled: false, onChoose: () => {},
  })) + renderToStaticMarkup(React.createElement(Markdown, { text: "计算过程：\n```text\n3! → 3 × 2! → 3 × 2 × 1!\n```" })));
  await expect(page.getByRole("group", { name: "点击选择答案" }).locator(".katex")).toHaveCount(2);
  await expect(page.locator("body")).toContainText("3! → 3 × 2! → 3 × 2 × 1!");
});
