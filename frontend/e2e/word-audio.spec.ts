import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

async function openWord(page: Page) {
  if (process.env.PLAYWRIGHT_REAL_MODE === "1") {
    const health = await (await page.request.get("/api/health")).json();
    expect(health.release).toBe(process.env.ACCEPTANCE_EXPECTED_COMMIT);
    expect(health.demo_mode).toBe(false);
  }
  await page.addInitScript(() => {
    // Reproduce phones with no installed English voices. Accessing speech
    // synthesis fails the test instead of quietly rescuing audio playback.
    Object.defineProperty(window, "speechSynthesis", { configurable: true, get() { throw new Error("Device TTS must not be used for vocabulary"); } });
    const events: object[] = [];
    (window as unknown as { wordAudioEvents: object[] }).wordAudioEvents = events;
    for (const name of ["click", "touchend", "play", "playing", "pause", "ended", "error", "emptied", "loadstart"]) {
      document.addEventListener(name, event => {
        const target = event.target;
        if (!(target instanceof Element) || !target.closest(".word-pronunciation")) return;
        const a = document.querySelector<HTMLAudioElement>(".word-pronunciation audio");
        events.push({ event: name, time: performance.now(), currentTime: a?.currentTime, paused: a?.paused, src: a?.currentSrc });
      }, true);
    }
  });
  const registration = await page.request.post("/api/auth/register", { data: {
    name: "单词音频验收", email: `word-audio-${randomUUID()}@example.test`, password: "Word-Audio-2026!",
  } });
  expect(registration.ok()).toBe(true);
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "新建课程" });
  await expect(dialog).toBeVisible();
  const courses = await (await page.request.get("/api/notebooks/learning/catalogue")).json();
  await dialog.getByRole("radio", { name: courses.items.find((c: { id: string }) => c.id === "cet6").title, exact: true }).check();
  const created = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/notebooks");
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  const notebook = (await (await created).json()).id;
  await expect(page.getByRole("heading", { name: "六级备考中心" })).toBeVisible();
  const base = `/api/notebooks/${notebook}/cet6`;
  const words = await (await page.request.get(base + "/words?q=analyze")).json();
  const entry = words.items.find((w: { word: string }) => w.word === "analyze");
  expect(entry).toBeTruthy();
  // Word details can automatically generate a missing explanation. Select an
  // existing curated lesson before navigation so live audio QA needs no model.
  const detail = await (await page.request.get(`${base}/words/${entry.id}`)).json();
  const lesson = await (await page.request.get(`${base}/words/${entry.id}/lesson?sense_id=${encodeURIComponent(detail.preferred_sense_id)}`)).json();
  expect(lesson.status).toBe("ready");
  expect(lesson.origin).toBe("curated");
  await page.goto(`/?notebook=${notebook}&cet6=vocabulary&cet6_word=${entry.id}`);
  await expect(page.locator(".word-pronunciation")).toBeVisible();
  return { notebook, base, entry };
}

async function listen(page: Page) {
  const button = page.getByRole("button", { name: "听发音", exact: true });
  if (test.info().project.use.hasTouch) await button.tap();
  else await button.click();
}

async function playToEnd(page: Page) {
  const audio = page.locator(".word-pronunciation audio");
  await listen(page);
  // Observe the real decoder reaching the natural end: no fake events, mute,
  // seeking to the end, route fixtures, or browser speech engine.
  try {
    await expect.poll(() => audio.evaluate((a: HTMLAudioElement) => a.ended), { timeout: 15000 }).toBe(true);
  } catch (error) {
    const diagnostic = await audio.evaluate((a: HTMLAudioElement) => ({
      src: a.currentSrc, paused: a.paused, ended: a.ended, currentTime: a.currentTime,
      duration: a.duration, readyState: a.readyState, error: a.error?.code,
      events: (window as unknown as { wordAudioEvents: object[] }).wordAudioEvents,
    }));
    await test.info().attach("playback-state", { body: JSON.stringify(diagnostic, null, 2), contentType: "application/json" });
    throw error;
  }
  const result = await audio.evaluate((a: HTMLAudioElement) => ({
    currentTime: a.currentTime, duration: a.duration, error: a.error?.code || null,
    muted: a.muted, rate: a.playbackRate, src: a.currentSrc,
  }));
  expect(result.error).toBeNull();
  expect(result.muted).toBe(false);
  expect(result.duration).toBeGreaterThan(.15);
  expect(result.currentTime).toBeCloseTo(result.duration, 1);
  await expect(page.locator(".word-pronunciation [role=alert]")).toHaveCount(0);
  return result;
}

test("无设备语音仍可播放英美音频、慢速、重播和恢复口音", async ({ page }, info) => {
  await openWord(page);
  const audio = page.locator(".word-pronunciation audio");
  expect(await audio.evaluate((a: HTMLAudioElement) => a.paused)).toBe(true);
  const us = await playToEnd(page);
  expect(us.src).toContain("/en-US/");
  const range = await page.request.get(us.src, { headers: { Range: "bytes=0-127" } });
  expect(range.status()).toBe(206);
  expect(range.headers()["content-type"]).toMatch(/audio\/(mpeg|mp3)/);
  expect(range.headers()["content-range"]).toMatch(/^bytes 0-127\//);
  expect((await range.body()).length).toBe(128);
  await page.getByLabel("发音口音", { exact: true }).selectOption("en-GB");
  await page.getByLabel("慢速", { exact: true }).check();
  const gb = await playToEnd(page);
  expect(gb.src).toContain("/en-GB/");
  expect(gb.rate).toBe(.75);
  await playToEnd(page);
  await page.reload();
  await expect(page.getByLabel("发音口音", { exact: true })).toHaveValue("en-GB");
  await playToEnd(page);
  await page.getByText("发音来源与声音", { exact: true }).click();
  await expect(page.locator(".word-pronunciation")).toContainText("本站合成音频");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("word-audio.png"), fullPage: true });
});

test("音频网络故障和播放权限拒绝后可原地重试", async ({ page }) => {
  await openWord(page);
  const originalSource = await page.locator(".word-pronunciation audio").getAttribute("src");
  // Use a real 404: WebKit native media can bypass Playwright route interception.
  await page.locator(".word-pronunciation audio").evaluate((a: HTMLAudioElement) => { a.src = "/word-audio/missing-test-audio.mp3"; });
  await listen(page);
  await expect(page.locator(".word-pronunciation [role=alert]")).toBeVisible();
  await expect(page.locator(".word-pronunciation audio")).toBeVisible();
  await page.locator(".word-pronunciation audio").evaluate((a: HTMLAudioElement, src) => { a.src = src!; }, originalSource);
  await playToEnd(page);
  await page.evaluate(() => {
    const original = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      HTMLMediaElement.prototype.play = original;
      return Promise.reject(new DOMException("User gesture required", "NotAllowedError"));
    };
  });
  await listen(page);
  await expect(page.locator(".word-pronunciation [role=alert]")).toContainText("浏览器暂未允许播放");
  await playToEnd(page);
});

test("轮次词卡连续点击、切换口音和离开页面会停止旧发音", async ({ page }) => {
  const { notebook, base } = await openWord(page);
  const response = await page.request.post(base + "/word-rounds", { data: { kind: "new", request_id: randomUUID() } });
  expect(response.ok()).toBe(true);
  const round = await response.json();
  await page.goto(`/?notebook=${notebook}&cet6=vocabulary&cet6_round=${round.id}`);
  const audio = page.locator(".word-pronunciation audio");
  await expect(audio).toHaveAttribute("src", /word-audio/);
  await listen(page);
  await listen(page);
  await expect.poll(() => audio.evaluate((a: HTMLAudioElement) => a.ended), { timeout: 15000 }).toBe(true);
  await expect(page.locator(".word-pronunciation [role=alert]")).toHaveCount(0);
  await listen(page);
  await page.getByLabel("发音口音", { exact: true }).selectOption("en-GB");
  await expect.poll(() => audio.evaluate((a: HTMLAudioElement) => a.paused)).toBe(true);
  await playToEnd(page);
  await audio.evaluate(a => { (window as unknown as { previousWordAudio: Element }).previousWordAudio = a; });
  await listen(page);
  await page.getByRole("button", { name: "暂停，返回背词", exact: true }).click();
  expect(await page.evaluate(() => (window as unknown as { previousWordAudio: HTMLAudioElement }).previousWordAudio.paused)).toBe(true);
});
