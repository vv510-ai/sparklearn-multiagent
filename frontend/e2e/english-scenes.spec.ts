import { expect, test } from "@playwright/test";
import { registerLearner } from "./intake-helpers";

test("三节英语课：真实播放、逐句复听、表达拆解和任务恢复", async ({ page }, testInfo) => {
  test.setTimeout(600_000);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await registerLearner(page, "english-scenes");
  await page.goto("/library");
  const card = page.locator(".library-course-card").filter({ has: page.getByRole("heading", { name: "英语生活场景 · 三课试学" }) });
  await card.getByRole("button", { name: "开始第一课" }).click();
  await expect(page.getByRole("heading", { name: "同学邀约", exact: true })).toBeVisible();
  const studyURL = page.url();
  const studyID = new URL(studyURL).searchParams.get("study")!;
  const lessonURL = `/api/library/studies/${studyID}/lessons/invitation`;
  const first = await (await page.request.get(lessonURL)).json();
  expect(first.work_reference).toBeUndefined();
  expect(first.question.answer).toBeUndefined();
  expect(first.scene.audio.notice).toContain("合成");
  const range = await page.request.get(first.scene.audio.url, { headers: { Range: "bytes=0-127" } });
  expect(range.status()).toBe(206);
  expect((await range.body()).subarray(0, 4).toString()).toBe("RIFF");
  await expect(page.getByRole("button", { name: "记录完整播放", exact: true })).toBeDisabled();
  await expect(page.locator(".scene-current-line")).not.toContainText("Would you like");
  await page.getByRole("checkbox", { name: "显示英文字幕" }).check();
  await page.getByRole("checkbox", { name: "显示中文释义" }).check();
  await expect(page.locator(".scene-current-line")).toContainText("Would you like");
  const firstLine = await page.locator(".scene-current-line").innerText();
  await page.getByRole("button", { name: "下一句", exact: true }).click();
  await expect(page.locator(".scene-current-line")).toContainText("I'd love to");
  await page.getByRole("button", { name: "上一句", exact: true }).click();
  expect(await page.locator(".scene-current-line").innerText()).toBe(firstLine);
  await page.getByRole("combobox", { name: "跳到句子" }).selectOption("3");
  await expect(page.locator(".scene-current-line")).toContainText("four thirty");
  await page.getByRole("checkbox", { name: "循环当前句" }).check();
  await page.getByRole("button", { name: "复听当前句" }).click();
  const cue = first.scene.audio.cues[3];
  await page.waitForTimeout((cue.end - cue.start + 1.2) * 1000);
  const repeated = await page.locator("audio").evaluate((el: HTMLAudioElement) => ({ time: el.currentTime, paused: el.paused, duration: el.duration }));
  expect(repeated.paused).toBe(false);
  expect(repeated.time).toBeGreaterThanOrEqual(cue.start);
  expect(repeated.time).toBeLessThan(cue.end + .25);
  // Simulate the browser visibility signal; actual PCM playback above is not mocked.
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => page.locator("audio").evaluate((el: HTMLAudioElement) => el.paused)).toBe(true);
  await page.evaluate(() => { Reflect.deleteProperty(document, "hidden"); document.dispatchEvent(new Event("visibilitychange")); });
  await page.getByRole("button", { name: "复听当前句" }).click();
  await expect.poll(() => page.locator("audio").evaluate((el: HTMLAudioElement) => el.paused)).toBe(false);
  await page.getByRole("button", { name: "暂停音频" }).click();
  await page.getByRole("checkbox", { name: "循环当前句" }).uncheck();
  await expect(page.getByRole("button", { name: "记录完整播放", exact: true })).toBeDisabled();
  const animation = page.getByRole("region", { name: "表达拆解" });
  await animation.focus();
  await page.keyboard.press("End");
  await expect(animation).toContainText("Saturday morning");
  await page.keyboard.press("Home");
  await expect(animation).toContainText("to study together");
  await animation.getByRole("button", { name: "播放拆解" }).click();
  await expect(animation).toContainText("友好地说明冲突", { timeout: 7000 });
  await animation.getByRole("button", { name: "暂停拆解" }).click();
  await animation.getByRole("button", { name: "回到第一步" }).click();
  await expect(animation).toContainText("to study together");
  const input = page.getByLabel("写下你的英语回应");
  await input.fill("Would you like to visit the exhibition?");
  await input.press("End");
  await input.press("Space");
  await expect(input).toHaveValue("Would you like to visit the exhibition? ");
  await page.getByRole("button", { name: "我已阅读，记录进度" }).click();
  await expect(page.getByRole("button", { name: "已记录阅读，再次确认" })).toBeEnabled();
  await expect(input).toHaveValue("Would you like to visit the exhibition? ");
  await page.getByRole("radio", { name: /^A\./ }).check();
  await page.getByRole("button", { name: "提交新题答案" }).click();
  await expect(page.locator(".library-feedback").first()).toContainText("自述独立作答");
  await expect(page.getByRole("region", { name: "本课新题练习" })).toContainText("隔日新题");
  await input.fill("Would you like to visit the photo exhibition? Would ten thirty work for you? Let's meet by the student center.");
  await page.getByRole("button", { name: "保存英语回应与自查" }).click();
  await expect(page.getByRole("button", { name: "保存后查看参考回应" })).toBeEnabled();
  await page.getByRole("button", { name: "保存后查看参考回应" }).click();
  await expect(page.getByRole("heading", { name: "参考回应（示例，不是唯一答案）" })).toBeVisible();
  expect((await (await page.request.get(lessonURL)).json()).progress.work.assisted).toBe(true);

  // Let all three final WAV files naturally reach ended; no seek or synthetic event.
  for (const [id, title] of [["invitation", "同学邀约"], ["cafe", "咖啡店点单"], ["roommates", "室友协商"]]) {
    await page.goto(`/library?study=${studyID}&lesson=${id}`);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "播放整段", exact: true }).click();
    await expect.poll(() => page.locator("audio").evaluate((el: HTMLAudioElement) => el.currentTime), { timeout: 15000 }).toBeGreaterThan(.2);
    await expect(page.getByRole("button", { name: "记录完整播放", exact: true })).toBeEnabled({ timeout: 100000 });
    const ended = await page.locator("audio").evaluate((el: HTMLAudioElement) => ({ ended: el.ended, duration: el.duration, time: el.currentTime }));
    expect(ended.ended).toBe(true);
    expect(Math.abs(ended.duration - ended.time)).toBeLessThan(.1);
    await page.getByRole("button", { name: "记录完整播放", exact: true }).click();
    await expect(page.getByRole("button", { name: "已记录完整播放", exact: true })).toBeVisible();
    await testInfo.attach(`audio-${id}`, { body: JSON.stringify(ended), contentType: "application/json" });
  }
  await page.goto(studyURL);
  await expect(input).toHaveValue(/photo exhibition/);
  await expect(page.getByRole("heading", { name: "参考回应（示例，不是唯一答案）" })).toBeVisible();
  await page.getByRole("checkbox", { name: "显示英文字幕" }).check();
  await page.getByRole("checkbox", { name: "显示中文释义" }).check();
  for (const width of [1280, 834, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("heading", { name: "同学邀约", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`english-${width}.png`), fullPage: true });
  }
  if (process.env.PLAYWRIGHT_REAL_MODE === "1") {
    expect(process.env.ACCEPTANCE_EXPECTED_COMMIT).toMatch(/^[a-f0-9]{40}$/);
    const study = await (await page.request.get(`/api/library/studies/${studyID}`)).json();
    const user = await (await page.request.get("/api/auth/me")).json();
    const res = await page.request.post("/api/chat", { timeout: 180000, data: { user_id: user.id, notebook_id: study.notebook_id, source_policy: "strict", message: "请依据本课原创咖啡店对话：客人最初要什么奶，最后换成了什么奶？请引用本课出处，不引用 Python 教材。" } });
    expect(res.ok()).toBeTruthy();
    const events = (await res.text()).split("\n").filter(x => x.startsWith("data: ")).map(x => JSON.parse(x.slice(6)));
    expect(events.some(x => x.type === "done")).toBe(true);
    expect(events.filter(x => x.type === "error")).toEqual([]);
    const answer = events.filter(x => x.type === "token").map(x => x.delta || "").join("");
    expect(answer).toMatch(/豆奶|soy/i);
    const evidence = events.filter(x => x.type === "citations" && x.agent === "tutor").flatMap(x => x.evidence || []);
    expect(evidence.some(x => x.course_release_id === study.release_id && x.source_type === "platform_original")).toBe(true);
    await testInfo.attach("english-live-rag", { body: JSON.stringify({ answer, evidence }), contentType: "application/json" });
  }
  expect(errors).toEqual([]);
});

test("音频不可用时可文字学习，但不能伪记完整播放", async ({ page }) => {
  await registerLearner(page, "english-fallback");
  await page.route("**/api/library/releases/*/media/*", route => route.fulfill({ status: 503, body: "unavailable" }));
  await page.goto("/library");
  await page.locator(".library-course-card").filter({ has: page.getByRole("heading", { name: "英语生活场景 · 三课试学" }) }).getByRole("button", { name: "开始第一课" }).click();
  await expect(page.getByRole("region", { name: "场景听力" }).getByRole("alert")).toContainText("音频暂时无法播放");
  await page.getByRole("checkbox", { name: "显示英文字幕" }).check();
  await expect(page.locator(".scene-current-line")).toContainText("Would you like");
  await expect(page.getByRole("button", { name: "记录完整播放", exact: true })).toBeDisabled();
  await page.getByLabel("写下你的英语回应").fill("Would Saturday work for you?");
  await page.getByRole("button", { name: "保存英语回应与自查" }).click();
  await expect(page.getByRole("status").filter({ hasText: "英语回应与自查记录已保存" })).toBeVisible();
  const id = new URL(page.url()).searchParams.get("study");
  const data = await (await page.request.get(`/api/library/studies/${id}`)).json();
  expect(data.progress.lessons.invitation.listening).toBeUndefined();
});
