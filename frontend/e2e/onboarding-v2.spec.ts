import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { registerLearner, currentAssessment } from "./intake-helpers";

const dataDir = path.resolve(__dirname, "../../backend/app/data");
const answerBank = [
  ...JSON.parse(readFileSync(path.join(dataDir, "seed_quiz.json"), "utf8")).questions,
  ...JSON.parse(readFileSync(path.join(dataDir, "assessment_questions.json"), "utf8")),
  ...JSON.parse(readFileSync(path.join(dataDir, "entry_v2_questions.json"), "utf8")),
];

test("多选引导可恢复，短测直达资料，并继续剩余摸底", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1512, height: 982 });
  await registerLearner(page, "intake-v2");
  await page.screenshot({ path: testInfo.outputPath("01-welcome.png"), fullPage: true });
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await expect(page.locator(".learning-intake [role='alert']")).toContainText("至少选择一个目标");
  await page.getByRole("checkbox", { name: /完成项目或实际任务/ }).check();
  await page.getByRole("checkbox", { name: /准备课程考试/ }).check();
  await page.getByLabel("当前优先解决").selectOption("完成项目或实践");
  await page.reload();
  await expect(page.getByRole("checkbox", { name: /完成项目或实际任务/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /准备课程考试/ })).toBeChecked();
  await expect(page.getByLabel("当前优先解决")).toHaveValue("完成项目或实践");
  await page.screenshot({ path: testInfo.outputPath("02-multiselect-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("03-multiselect-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("radio", { name: "数据结构与算法", exact: true }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByRole("checkbox", { name: /看懂答案，自己不会做/ }).check();
  await page.getByRole("checkbox", { name: /思路懂，代码写不出/ }).check();
  await page.getByRole("checkbox", { name: /符号与步骤讲细些/ }).check();
  await page.getByRole("checkbox", { name: /任务短一些/ }).check();
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await page.getByLabel("每个学习日可用时间（分钟）").fill("20");
  await page.getByLabel("什么时机会比较容易开始？").fill("晚饭后坐到书桌前");
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await expect(page.getByRole("radio", { name: /先找学习起点/ })).toBeChecked();
  await page.locator(".intake-example-details summary").click();
  await page.getByRole("radio", { name: "页面 A" }).check();
  await page.getByRole("button", { name: "看看原因" }).click();
  await expect(page.getByText("先回到 B。一起看一下变化。")).toBeVisible();
  await page.getByRole("button", { name: "生成并核对学习范围", exact: true }).click();
  await page.getByRole("button", { name: "确认范围，开始独立作答", exact: true }).click();
  await expect(page.locator(".entry-question-card")).toBeVisible();
  await expect(page.locator(".learning-intake")).toHaveCount(0);
  const before = await currentAssessment(page);
  expect(before.survey.goals).toEqual(["完成项目或实践", "准备课程考试"]);
  expect(before.survey.barriers).toEqual(["application", "coding"]);
  expect(before.survey.intro_practiced).toBe(true);
  expect(before.maximum).toBe(12);
  let sawMultiple = false;
  for (let i = 0; i < 12; i++) {
    await expect(page.getByText(`已提交 ${i} 题 / 最多 12 题`, { exact: true })).toBeVisible();
    const current = await currentAssessment(page);
    const q = answerBank.find(q => q.id === current.question.id);
    const keys = q.type === "judge" ? [q.answer === "对" ? "A" : "B"] : Array.isArray(q.answer) ? q.answer : [q.answer];
    for (const key of keys) await page.locator(`.entry-options input[value="${key}"]`).check();
    if (current.question.type === "multiple") sawMultiple = true;
    await page.getByRole("button", { name: "提交，继续下一题" }).click();
    if (i === 2) {
      await page.getByRole("button", { name: "暂停，稍后继续" }).click();
      await page.reload();
      await page.getByRole("button", { name: "打开起点测评", exact: true }).click();
      await expect(page.getByText("已提交 3 题 / 最多 12 题", { exact: true })).toBeVisible();
    }
  }
  await expect(page.getByRole("heading", { name: "你的学习起点，已经清楚了一些" })).toBeVisible();
  expect(sawMultiple).toBe(true);
  await expect(page.locator(".entry-skill.is-unmeasured")).toHaveCount(12);
  await expect(page.locator(".entry-adaptations")).toContainText("准备课程考试");
  await expect(page.locator(".entry-adaptations")).toContainText("伪代码");
  await expect(page.locator(".entry-adaptations")).toContainText("晚饭后");
  await page.setViewportSize({ width: 1512, height: 982 });
  await page.screenshot({ path: testInfo.outputPath("04-report.png"), fullPage: true });
  await page.getByRole("button", { name: "开始第一项学习任务" }).click();
  await expect(page.locator(".entry-study")).toBeVisible();
  await expect(page.locator(".entry-study")).toContainText("这份资料怎样帮助你");
  await expect(page.locator(".entry-study")).toContainText("补全关键步骤");
  await page.screenshot({ path: testInfo.outputPath("05-first-task.png"), fullPage: true });
  await page.getByRole("button", { name: "返回起点报告" }).click();
  await page.getByRole("button", { name: "继续补全课程摸底" }).click();
  await expect(page.getByText("已提交 12 题 / 最多 48 题", { exact: true })).toBeVisible();
  const continued = await currentAssessment(page);
  expect(continued.id).toBe(before.id);
  expect(continued.survey.goals).toEqual(before.survey.goals);
  expect(errors).toEqual([]);
});

test("跳过引导后仍能找到测评入口", async ({ page }) => {
  await registerLearner(page, "intake-skip");
  await page.getByRole("button", { name: "返回", exact: true }).click();
  await page.getByRole("button", { name: "先体验一次讲解" }).click();
  await page.getByRole("radio", { name: "页面 B" }).check();
  await page.getByRole("button", { name: "看看原因" }).click();
  await expect(page.getByText("对，你抓住了最近访问的顺序。")).toBeVisible();
  await page.getByRole("button", { name: "已有明确方向，直接进入" }).click();
  await expect(page.getByRole("button", { name: "先测一下我的水平", exact: true })).toBeVisible();
  const profile = (await (await page.request.get("/api/onboarding")).json()).profile;
  expect(profile.learning_intake.intro_practiced).toBe(true);
  await page.getByRole("button", { name: "先测一下我的水平", exact: true }).click();
  await expect(page.getByRole("heading", { name: "你希望小知先帮你完成什么？" })).toBeVisible();
});
