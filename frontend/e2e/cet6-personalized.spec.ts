import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

async function register(page: Page) {
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("六级个性化验收");
  await page.getByPlaceholder("you@example.com").fill(`cet6-journey-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Cet6-Journey-QA-2026!");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建课程" });
  await expect(dialog).toBeVisible();
  const catalogue = await (await page.request.get("/api/notebooks/learning/catalogue")).json();
  await dialog.getByRole("radio", { name: catalogue.items.find((c: { id: string }) => c.id === "cet6").title, exact: true }).check();
  const created = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/notebooks");
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  await expect(page.getByRole("heading", { name: "六级备考中心" })).toBeVisible();
  const notebook = (await (await created).json()).id;
  return { notebook, base: `/api/notebooks/${notebook}/cet6` };
}

test("可选目标、全量词汇、回忆记录与新对话恢复", async ({ page }, info) => {
  await page.setViewportSize({ width: 1500, height: 980 });
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  const { notebook, base } = await register(page);
  await page.screenshot({ path: info.outputPath("cet6-home-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "学习偏好", exact: true }).click();
  const preferences = page.getByRole("form", { name: "学习偏好设置" });
  await preferences.getByLabel("我现在最想解决的问题").fill("阅读时能区分转折与因果");
  await preferences.getByLabel("每天可用分钟").fill("10");
  await preferences.getByLabel("学习侧重点").selectOption("foundation");
  await preferences.getByRole("checkbox", { name: "阅读", exact: true }).check();
  await preferences.getByRole("button", { name: "保存并查看建议" }).click();
  await expect(page.getByRole("heading", { name: "你的六级备考建议" })).toBeVisible();
  await page.locator(".cet6-main-nav").getByRole("button", { name: "今天", exact: true }).click();
  await expect(page.locator(".cet6-today")).toContainText("阅读时能区分转折与因果");
  await page.reload(); await expect(page.locator(".cet6-today")).toContainText("10 分钟");
  await page.locator(".cet6-main-nav").getByRole("button", { name: "背单词", exact: true }).click();
  await page.getByRole("button", { name: "查词与全部词汇", exact: true }).click();
  await expect(page.getByRole("region", { name: "六级词汇学习" })).toContainText("8010 个结果");
  await page.getByRole("textbox", { name: "搜索单词或派生词" }).fill("evidence");
  await page.locator(".cet6-word-list button").filter({ has: page.locator("strong", { hasText: /^evidence$/ }) }).click();
  await page.getByRole("button", { name: "加入我的生词", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("已收藏到我的生词");
  await page.getByRole("button", { name: "开始回忆", exact: true }).click();
  await page.getByLabel("我的回忆", { exact: true }).fill("支持判断的证据");
  await page.getByRole("button", { name: "核对答案", exact: true }).click();
  await expect(page.locator(".cet6-feedback")).toContainText("支持判断的证据");
  await page.getByRole("button", { name: /^正常想起/ }).click();
  await expect(page.locator(".cet6-next-review")).toContainText("学习者自评");
  await page.reload(); await expect(page.getByRole("button", { name: "已收藏", exact: true })).toBeVisible();
  await expect(page.locator(".cet6-next-review")).toContainText("词义");
  await page.getByLabel("这次练什么").selectOption("spelling");
  await page.getByRole("button", { name: "开始回忆", exact: true }).click();
  await expect(page.getByRole("heading", { name: "根据词义回忆拼写" })).toBeVisible();
  await page.getByLabel("我的回忆", { exact: true }).fill("evidance");
  await page.getByRole("button", { name: "核对答案", exact: true }).click();
  await expect(page.getByRole("button", { name: /^正常想起/ })).toBeDisabled();
  await page.getByRole("button", { name: /^忘记了/ }).click();
  await expect(page.locator(".cet6-next-review")).toContainText("拼写");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("cet6-vocabulary-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1500, height: 980 });
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  expect((await (await page.request.get(base)).json()).preferences.goal).toBe("阅读时能区分转折与因果");
  await page.goto(`/?notebook=${notebook}&cet6=vocabulary`);
  await page.getByRole("button", { name: "我的生词", exact: true }).click();
  await expect(page.locator(".cet6-word-list")).toContainText("evidence");
  expect(errors).toEqual([]);
});

test("写作与翻译保留初稿、刷新恢复、修改后独立复习", async ({ page }, info) => {
  const { notebook, base } = await register(page);
  await page.goto(`/?notebook=${notebook}&cet6=practice&cet6_kind=translation`);
  await page.getByRole("button", { name: /先保留信息，再调整表达/ }).click();
  await expect(page.getByRole("button", { name: "提交我的作答", exact: true })).toBeDisabled();
  await page.getByLabel("我的初稿").fill("Many public libraries have extended their opening hours.");
  await expect(page.locator(".cet6-section-heading [role=status]")).toHaveText("已保存到账号");
  await page.reload(); await expect(page.getByLabel("我的初稿")).toHaveValue("Many public libraries have extended their opening hours.");
  await page.getByRole("button", { name: "提交我的作答", exact: true }).click();
  await expect(page.locator(".cet6-feedback")).toContainText("自编参考译文");
  await page.getByLabel("我的修改稿").fill("In recent years, public libraries in many cities have extended their opening hours and offered free activities.");
  await page.getByLabel("记下一处修改或重听后的发现").fill("补回近年来、许多城市和免费这三个信息。");
  await expect(page.locator(".cet6-section-heading [role=status]")).toHaveText("已保存到账号");
  await page.getByRole("button", { name: "保存订正，安排复习", exact: true }).click();
  await expect(page.locator(".cet6-complete")).toContainText("这次练习已保存");
  const saved = await (await page.request.get(base + "/practice/translation-library-v1")).json();
  await page.reload();
  await expect(page.locator(".cet6-feedback")).toHaveCount(0);
  await page.getByRole("button", { name: "隐藏参考，重新独立尝试", exact: true }).click();
  await expect(page.locator(".cet6-feedback")).toHaveCount(0);
  await expect(page.getByLabel("我的初稿")).toHaveValue("");
  expect((await (await page.request.get(base + "/practice/translation-library-v1")).json()).history[0].first).toBeUndefined();
  await page.screenshot({ path: info.outputPath("cet6-independent-reattempt.png"), fullPage: true });
  await page.goto(`/?notebook=${notebook}&cet6=practice&cet6_task=writing-community-v1`);
  await page.getByLabel("我的初稿").fill("University students can contribute to their communities by helping local children learn to read.");
  await expect(page.locator(".cet6-section-heading [role=status]")).toHaveText("已保存到账号");
  await page.getByRole("button", { name: "提交我的作答", exact: true }).click();
  await expect(page.locator(".cet6-feedback")).toContainText("大学生能怎样贡献社区");
  await page.getByLabel("我的修改稿").fill("University students can organize a weekly reading group for children and choose books with local teachers.");
  await page.getByLabel("记下一处修改或重听后的发现").fill("增加了每周读书会这个具体行动。");
  await expect(page.locator(".cet6-section-heading [role=status]")).toHaveText("已保存到账号");
  await page.getByRole("button", { name: "保存订正，安排复习", exact: true }).click();
  expect(saved.first.answer).toBe("Many public libraries have extended their opening hours.");
  await expect(page.locator(".cet6-complete")).toContainText("这次练习已保存");
});

test("听力先播放后提交，文本按需展开，手机无横向溢出", async ({ page }, info) => {
  test.setTimeout(180000);
  const { notebook, base } = await register(page);
  await page.goto(`/?notebook=${notebook}&cet6=practice&cet6_kind=listening`);
  await page.getByRole("button", { name: /听出方案调整的原因/ }).click();
  const audio = page.getByLabel("听力短练音频");
  await expect.poll(() => audio.evaluate((a: HTMLAudioElement) => a.readyState)).toBeGreaterThanOrEqual(1);
  expect(await audio.evaluate((a: HTMLAudioElement) => a.duration)).toBeGreaterThan(20);
  await expect(page.getByText("按需查看听力文本", { exact: true })).toHaveCount(0);
  await page.getByRole("radio", { name: /^A\. Students asked/ }).check();
  await expect(page.getByRole("button", { name: "提交我的作答", exact: true })).toBeDisabled();
  await audio.evaluate(async (a: HTMLAudioElement) => { a.muted = true; a.playbackRate = 4; await a.play(); });
  await expect.poll(() => audio.evaluate((a: HTMLAudioElement) => a.ended), { timeout: 20000 }).toBe(true);
  await page.getByRole("button", { name: "提交我的作答", exact: true }).click();
  await expect(page.locator(".cet6-feedback")).toContainText("这次选择正确");
  await page.getByText("按需查看听力文本", { exact: true }).click();
  await expect(page.locator(".cet6-feedback")).toContainText("remain unchanged");
  await page.getByLabel("记下一处修改或重听后的发现").fill("重听了 however 后的偏好，晚上时间没有变化。");
  await expect(page.locator(".cet6-section-heading [role=status]")).toHaveText("已保存到账号");
  await page.getByRole("button", { name: "保存订正，安排复习", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("cet6-listening-mobile.png"), fullPage: true });
  expect((await (await page.request.get(base + "/practice/listening-library-v1")).json()).first.correct).toBe(true);
});

test("阅读生词连同原句保存，返回原题并恢复同一学生记录", async ({ page }) => {
  const { notebook, base } = await register(page);
  await page.goto(`/?notebook=${notebook}&cet6=reading`);
  await page.getByRole("button", { name: "开始阅读体验", exact: true }).click();
  await page.getByRole("button", { name: "第 2 题", exact: true }).click();
  await page.getByText("保存题中生词", { exact: true }).click();
  await page.getByLabel("查找词库", { exact: true }).fill("library");
  await page.getByRole("button", { name: "查找单词", exact: true }).click();
  await page.locator(".reading-vocabulary .reading-list-item").filter({ has: page.locator("strong", { hasText: /^library$/ }) }).click();
  await page.getByLabel("我理解的语境义（选填）", { exact: true }).fill("这里指供学生学习的图书馆");
  await page.getByRole("button", { name: "连同原句保存生词", exact: true }).click();
  await expect(page.locator(".reading-vocabulary [role=status]")).toContainText("已保存到我的生词");
  const reading = new URL(page.url()).searchParams.get("reading")!;
  await expect.poll(async () => (await (await page.request.get(`/api/notebooks/${notebook}/reading/${reading}`)).json()).used_help).toBe(true);
  await page.getByRole("link", { name: "去词卡复习 ↗", exact: true }).click();
  await expect(page.getByRole("heading", { name: "library", exact: true })).toBeVisible();
  await expect(page.getByText("这里指供学生学习的图书馆", { exact: false })).toBeVisible();
  await page.getByRole("link", { name: "回到原阅读", exact: true }).click();
  await expect(page.getByRole("region", { name: "阅读训练工作区" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("reading")).toBe(reading);
  await expect(page.getByRole("button", { name: "第 2 题", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect((await (await page.request.get(base + "/words?view=mine")).json()).total).toBe(1);
});

test("五个新词固定结束、暂停刷新恢复与到期复习分开", async ({ page }, info) => {
  const { base } = await register(page);
  await page.locator(".cet6-main-nav").getByRole("button",{name:"背单词",exact:true}).click();
  await page.getByRole("button",{name:/开始 \/ 继续新词/}).click();
  const region=page.getByRole("region",{name:"有限词卡练习"});
  await expect(region).toContainText("0 / 5");
  await expect(page.getByLabel("我的回忆",{exact:true})).toHaveCount(0);
  const id=new URL(page.url()).searchParams.get("cet6_round")!;
  const initial=await(await page.request.get(base+"/word-rounds/"+encodeURIComponent(id))).json();
  for(let i=0;i<5;i++){
    const word=page.locator(".word-flash-face h3");await expect(word).toBeVisible();
    if(i===1){
      const old=await word.innerText();await page.getByRole("button",{name:"暂停，返回背词"}).click();
      await page.getByRole("button",{name:/开始 \/ 继续新词/}).click();
      await expect.poll(()=>new URL(page.url()).searchParams.get("cet6_round")).toBe(id);
      await page.reload();await expect(word).toHaveText(old);
    }
    await page.getByRole("button",{name:"翻面看释义",exact:true}).click();
    await expect(page.locator(".word-rating-grid button")).toHaveCount(4);
    if(i===0)await page.screenshot({path:info.outputPath("word-round-desktop.png"),fullPage:true});
    await page.getByRole("button",{name:i===0?/忘记了/:/想起来了/}).click();
    await expect(region).toContainText(`${i+1} / 5`);
  }
  await expect(page.getByRole("heading",{name:"这一轮完成了"})).toBeVisible();
  await expect(page.locator(".word-flashcard")).toHaveCount(0);
  const finished=await(await page.request.get(base+"/word-rounds/"+encodeURIComponent(id))).json();
  expect(finished.items.map((v:{entry_id:string})=>v.entry_id)).toEqual(initial.items.map((v:{entry_id:string})=>v.entry_id));
  expect(finished.finished).toBe(true);
  expect((await(await page.request.get(base+"/word-plan")).json()).new_done).toBe(5);
  await page.reload();await expect(page.getByRole("heading",{name:"这一轮完成了"})).toBeVisible();
  await page.getByRole("button",{name:"完成，回到背词",exact:true}).click();
  const reviewResponse=page.waitForResponse(r=>r.request().method()==="POST"&&new URL(r.url()).pathname===base+"/word-rounds");
  await page.getByRole("button",{name:/开始 \/ 继续到期复习/}).click();
  const nextRound=await(await reviewResponse).json();
  if(nextRound.total){
    await expect(page.getByRole("region",{name:"有限词卡练习"})).toContainText("本轮到期复习");
    const reviewId=new URL(page.url()).searchParams.get("cet6_round")!;
    const review=await(await page.request.get(base+"/word-rounds/"+encodeURIComponent(reviewId))).json();
    expect(review.kind).toBe("review");expect(review.total).toBeLessThanOrEqual(20);
  }else await expect(page.locator(".cet6-notice[role=status]")).toContainText("目前没有到期复习卡");
  expect((await(await page.request.get(base+"/word-plan")).json()).new_done).toBe(5);
});

test("跨阶段草稿可恢复，提交期间不丢输入", async ({ page }) => {
  const { notebook, base } = await register(page);
  const taskUrl = `${base}/practice/writing-community-v1`;
  await page.goto(`/?notebook=${notebook}&cet6=practice&cet6_task=writing-community-v1`);
  await expect(page.getByLabel("我的初稿")).toBeVisible();
  await page.route(`**${taskUrl}`, async route => {
    if (route.request().method() === "POST" && route.request().postDataJSON().action === "draft") await route.abort("failed");
    else await route.continue();
  });
  const localText = "This unsynced local draft must survive a submission in another window.";
  await page.getByLabel("我的初稿").fill(localText);
  await expect(page.getByRole("alert")).toBeVisible();
  const state = await (await page.request.get(taskUrl)).json();
  const submit = await page.request.post(taskUrl, { data: { action: "submit", revision: state.revision, request_id: randomUUID(), answer: "A different window submitted this independent first answer." } });
  expect(submit.ok()).toBe(true);
  await page.unroute(`**${taskUrl}`);
  await page.reload();
  await expect(page.getByRole("region", { name: "未同步草稿恢复" })).toBeVisible();
  await expect(page.getByLabel("保留的初稿")).toHaveValue(localText);
  await page.getByRole("button", { name: "使用已保存的记录", exact: true }).click();
  await expect(page.getByRole("region", { name: "未同步草稿恢复" })).toHaveCount(0);
  await page.getByLabel("我的修改稿").fill("Students can organize a weekly reading group in their communities.");
  await page.getByLabel("记下一处修改或重听后的发现").fill("补充了具体可执行的行动。");
  await expect(page.locator(".cet6-section-heading [role=status]")).toHaveText("已保存到账号");
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**${taskUrl}`, async route => {
    if (route.request().method() === "POST" && route.request().postDataJSON().action === "finish") await gate;
    await route.continue();
  });
  await page.getByRole("button", { name: "保存订正，安排复习", exact: true }).click();
  try { await expect(page.getByLabel("我的修改稿")).toBeDisabled(); }
  finally { release(); }
  await expect(page.locator(".cet6-complete")).toBeVisible();
  const saved = await (await page.request.get(taskUrl)).json();
  expect(saved.first.answer).toBe("A different window submitted this independent first answer.");
  expect(saved.revision_text).toBe("Students can organize a weekly reading group in their communities.");
});

test("小目标两张即停、可选精讲或离线提示与手机词卡布局", async ({ page }, info) => {
  const {base}=await register(page);
  await page.locator(".cet6-main-nav").getByRole("button",{name:"背单词",exact:true}).click();
  const plan=page.getByRole("region",{name:"每日背词计划"});
  await plan.getByRole("button",{name:"背词设置"}).click();
  await plan.getByLabel("每日新词数",{exact:true}).fill("2");
  await plan.getByRole("button",{name:"保存背词设置"}).click();
  await expect(plan).toContainText("/ 2 个");
  const ids=(await(await page.request.get(base+"/word-plan")).json()).new_ids;
  await page.reload();expect((await(await page.request.get(base+"/word-plan")).json()).new_ids).toEqual(ids);
  await plan.getByRole("button",{name:/开始 \/ 继续新词/}).click();
  await expect(page.getByRole("region",{name:"有限词卡练习"})).toContainText("0 / 2");
  await page.getByRole("button",{name:"翻面看释义",exact:true}).click();
  await expect(page.getByRole("region",{name:"单词精讲"})).toHaveCount(0);
  await page.getByRole("button",{name:/看用法与例句/}).click();
  // Priority order now begins with a syllabus-marked word rather than the
  // small curated lesson sample. Offline QA must show the real unavailable state.
  await expect(page.getByRole("region",{name:"单词精讲"})).toContainText(
    process.env.PLAYWRIGHT_REAL_MODE === "1" ? "常见搭配与用法" : "当前演示环境未连接词汇讲解服务");
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath("cet6-word-lesson-mobile.png"),fullPage:true});
  await page.getByRole("button",{name:/想起来了/}).click();
  await expect(page.getByRole("region",{name:"有限词卡练习"})).toContainText("1 / 2");
  await page.getByRole("button",{name:"翻面看释义",exact:true}).click();
  await page.getByRole("button",{name:/想起来了/}).click();
  await expect(page.getByRole("heading",{name:"这一轮完成了"})).toBeVisible();
  await page.getByRole("button",{name:"完成，回到背词",exact:true}).click();
  await expect(plan).toContainText("2 / 2 个");
  await plan.getByRole("button",{name:/开始 \/ 继续新词/}).click();
  await expect(page.locator(".cet6-notice[role=status]")).toContainText("今天的新词计划已完成");
});

test("官方样卷站内作答、草稿恢复、核对、订正与生词回链", async ({ page }, info) => {
  const { notebook, base } = await register(page);
  await page.goto(`/?notebook=${notebook}&cet6=papers`);
  await page.getByRole("button", { name: "打开原卷并作答" }).click();
  const workspace = page.getByRole("region", { name: "官方样卷训练" });
  await expect(workspace).toContainText("官方听力音频待核验");
  await expect(workspace.locator("iframe")).toHaveAttribute("src", /cet\.neea\.edu\.cn.*#page=176/);
  await expect(workspace.getByText("官方答案 C", { exact: false })).toHaveCount(0);
  await page.getByLabel("第26题答案", { exact: true }).selectOption("C");
  await page.getByRole("textbox", { name: "错因与订正笔记", exact: true }).fill("先核对空格前后的词性要求。");
  await page.reload();
  await expect(page.getByLabel("第26题答案", { exact: true })).toHaveValue("C");
  await page.getByRole("button", { name: "保存作答与笔记", exact: true }).click();
  await expect(workspace.getByRole("status")).toHaveText("已保存到账号");
  await page.getByRole("button", { name: "仔细阅读", exact: true }).click();
  await page.getByLabel("第55题答案", { exact: true }).selectOption("B");
  await page.getByRole("button", { name: "提交阅读作答", exact: true }).click();
  await expect(page.getByRole("region", { name: "阅读结果" })).toContainText("已答 2/30 题，答对 1 题");
  await expect(page.getByLabel("第55题答案", { exact: true })).toBeDisabled();
  const q55 = page.locator(".cet6-paper-question").filter({ has: page.getByLabel("第55题答案", { exact: true }) });
  await expect(q55).toContainText("官方答案 A");
  await q55.getByRole("button", { name: "保存本题生词" }).click();
  await page.getByText("保存题中生词", { exact: true }).click();
  await page.getByLabel("查找词库", { exact: true }).fill("evidence");
  await page.getByRole("button", { name: "查找单词", exact: true }).click();
  await page.locator(".reading-vocabulary .reading-list-item").filter({ has: page.locator("strong", { hasText: /^evidence$/ }) }).click();
  await page.getByLabel("摘录原卷中的一句话（自行核对原文）", { exact: true }).fill("My note about the evidence in this paper.");
  await page.getByRole("button", { name: "连同原句保存生词", exact: true }).click();
  await expect(page.locator(".reading-vocabulary [role=status]")).toContainText("已保存到我的生词");
  await page.getByRole("link", { name: "去词卡复习 ↗", exact: true }).click();
  await page.getByRole("link", { name: "回到原卷 · 第55题", exact: true }).click();
  await expect(page.getByRole("button", { name: "仔细阅读", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(workspace.locator("iframe")).toHaveAttribute("src", /#page=183/);
  await page.setViewportSize({ width: 1500, height: 980 });
  await page.screenshot({ path: info.outputPath("cet6-official-paper-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("cet6-official-paper-mobile.png"), fullPage: true });
  const item = (await (await page.request.get(base + "/papers")).json()).items[0];
  const state = await (await page.request.get(base + "/papers/" + item.id)).json();
  expect(state.first.answers).toEqual({ "26": "C", "55": "B" });
  expect(new URL(page.url()).searchParams.get("notebook")).toBe(notebook);
});

test("原卷双窗口保存响应不会清除另一窗口未保存草稿", async ({ page, context }) => {
  const { notebook } = await register(page);
  const url = `/?notebook=${notebook}&cet6=papers&cet6_paper=official-syllabus-2016-cet6`;
  await page.goto(url);
  await expect(page.getByRole("textbox", { name: "错因与订正笔记", exact: true })).toBeVisible();
  const other = await context.newPage(); await other.goto(url);
  await expect(other.getByRole("textbox", { name: "错因与订正笔记", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "错因与订正笔记", exact: true }).fill("窗口A本次准备保存的笔记");
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/cet6/papers/official-syllabus-2016-cet6", async route => {
    if (route.request().method() === "POST") { const response = await route.fetch(); await gate; await route.fulfill({ response }); }
    else await route.continue();
  });
  await page.getByRole("button", { name: "保存作答与笔记", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "错因与订正笔记", exact: true })).toBeDisabled();
  try { await other.getByRole("textbox", { name: "错因与订正笔记", exact: true }).fill("窗口B尚未保存的输入必须保留"); }
  finally { release(); }
  await expect(page.locator(".cet6-answer-sheet [role=status]")).toHaveText("已保存到账号");
  await other.reload();
  await expect(other.getByRole("region", { name: "原卷草稿冲突" })).toContainText("窗口B尚未保存的输入必须保留");
  await other.getByRole("button", { name: "保留本页输入继续编辑", exact: true }).click();
  await expect(other.getByRole("textbox", { name: "错因与订正笔记", exact: true })).toHaveValue("窗口B尚未保存的输入必须保留");
  await other.close();
});
