import { expect, test } from "@playwright/test";

// UI fixture only; real-model content acceptance is a separate production run.
test("多选先组合再提交，回答依据在刷新后保持", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addLocatorHandler(page.getByRole("button", { name: "跳过引导", exact: true }), b => b.click());
  await page.emulateMedia({ reducedMotion: "reduce" });
  // This case isolates chat controls; first-time onboarding has a separate real-model test.
  const registration = await page.request.post("/api/auth/register", { data: { email: `reliability-ui-${Date.now()}@example.test`, password: "Reliability-UI-test!2026", name: "交互验收" } });
  expect(registration.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", { data: { skipped: true } })).ok()).toBe(true);
  const book = await (await page.request.post("/api/notebooks", { data: { user_id: "session_user", title: "选择题交互验收" } })).json();
  expect((await page.request.post(`/api/notebooks/${book.id}/learning/prepare`, { data: { title: "数据结构与算法", course_key: "ds_algo" } })).ok()).toBe(true);
  await page.goto("/");
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(book.id);
  await page.getByLabel("对话选项", { exact: true }).click();
  await page.getByRole("combobox", { name: "回答依据" }).selectOption("strict");
  await page.reload();
  await page.getByRole("combobox", { name: "切换科目书本" }).selectOption(book.id);
  await page.getByLabel("对话选项", { exact: true }).click();
  await expect(page.getByRole("combobox", { name: "回答依据" })).toHaveValue("strict");
  await page.getByLabel("对话选项", { exact: true }).press("Escape");
  const requests: { message: string; display_message: string; source_policy: string }[] = [];
  const question = "**多选理解检查**\n\n按整数加法判断。\n\n以下哪些等式成立？\nA. $1+1=2$\nB. $2+2=4$\nC. $1+1=3$";
  await page.route("**/api/chat", async route => {
    requests.push(route.request().postDataJSON());
    const text = requests.length === 1 ? question : "已收到组合答案。";
    await route.fulfill({ contentType: "text/event-stream", body: [{ type: "token", delta: text }, { type: "done" }].map(e => `data: ${JSON.stringify(e)}\n\n`).join("") });
  });
  await page.getByLabel("学习目标输入", { exact: true }).fill("请给一个多选检查题");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const group = page.getByRole("group", { name: "点击选择答案" });
  await expect(group.locator(".katex")).toHaveCount(3);
  await expect(group.getByRole("button", { name: "提交所选答案" })).toBeDisabled();
  await group.getByRole("button").nth(0).click();
  await group.getByRole("button").nth(1).click();
  expect(requests).toHaveLength(1);
  await expect(group.getByRole("button").nth(0)).toHaveAttribute("aria-pressed", "true");
  await group.getByRole("button", { name: "提交所选答案" }).click();
  await expect(page.getByText("已收到组合答案。", { exact: true })).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1].display_message).toBe("A. $1+1=2$；B. $2+2=4$");
  expect(requests[1].source_policy).toBe("strict");
});
