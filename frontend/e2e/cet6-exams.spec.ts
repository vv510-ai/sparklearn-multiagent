import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

async function register(page:Page) {
  if(process.env.PLAYWRIGHT_REAL_MODE==="1"){
    const health=await(await page.request.get("/api/health")).json();
    expect(health.status).toBe("ok");expect(health.demo_mode).toBe(false);
    expect(health.release).toBe(process.env.ACCEPTANCE_EXPECTED_COMMIT);
  }
  await page.goto("/");
  await page.getByRole("tab",{name:"创建账户"}).click();
  await page.getByPlaceholder("怎么称呼你").fill("真题板块验收");
  await page.getByPlaceholder("you@example.com").fill(`exam-${Date.now()}-${randomUUID().slice(0,8)}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Exam-Pilot-QA-2026!");
  await page.getByRole("button",{name:"创建账户",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"新建课程"});
  await expect(dialog).toBeVisible();
  const catalogue=await(await page.request.get("/api/notebooks/learning/catalogue")).json();
  await dialog.getByRole("radio",{name:catalogue.items.find((c:{id:string})=>c.id==="cet6").title,exact:true}).check();
  const creation=page.waitForResponse(r=>r.request().method()==="POST"&&new URL(r.url()).pathname==="/api/notebooks");
  await dialog.getByRole("button",{name:"创建并进入",exact:true}).click();
  const notebook=(await(await creation).json()).id;
  await expect(page.getByRole("heading",{name:"六级备考中心"})).toBeVisible();
  return {notebook,base:`/api/notebooks/${notebook}/cet6/exams/cet6-2026-06-1`};
}
async function open(page:Page,kind:string) {
  await page.locator(".cet6-main-nav").getByRole("button",{name:"真题练习",exact:true}).click();
  await page.locator(".exam-kind-grid").getByRole("button",{name:new RegExp(kind)}).click();
  await page.getByRole("button",{name:"开始作答",exact:true}).click();
  await expect(page.getByRole("heading",{name:`2026 年 6 月 · 第 1 套 · ${kind}`})).toBeVisible();
  await expect(page.locator(".notebook-layout")).toHaveAttribute("data-sources-collapsed","true");
}
async function answersPane(page:Page) {
  await expect(page.locator(".exam-workspace")).toBeVisible();
  const button=page.getByRole("group",{name:"原卷与作答切换"}).getByRole("button",{name:/我的作答|结果与解析/});
  if(await button.isVisible())await button.click();
}
async function sourcePane(page:Page) {
  await expect(page.locator(".exam-workspace")).toBeVisible();
  const button=page.getByRole("group",{name:"原卷与作答切换"}).getByRole("button",{name:"阅读原卷",exact:true});
  if(await button.isVisible())await button.click();
}

test("真实原卷、阅读30题、键盘作答、提交解析与重新作答",async({page},info)=>{
  test.setTimeout(240000);
  await page.setViewportSize({width:1500,height:980});
  const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
  const {base}=await register(page);await open(page,"阅读");
  await expect(page.locator(".exam-source-text")).toContainText("Part III",{timeout:60000});
  await expect(page.locator(".exam-source-text")).not.toContainText("There has been a rise in attention");
  await expect(page.locator('.exam-choice-list label').filter({has:page.locator('input[value="A"]')})).toContainText("anywhere");
  expect(await page.locator(".exam-source-text").evaluate(e=>getComputedStyle(e).fontSize)).toBe("18px");
  await page.screenshot({path:info.outputPath("reading-source-desktop.png"),fullPage:true});
  await answersPane(page);
  const key="J I D C F K B G A E D I F K B H L E M J A B C D A C B A D D".split(" ");
  for(let i=0;i<key.length;i++){
    await page.getByRole("navigation",{name:"本板块题号"}).getByRole("button",{name:new RegExp(`^第 ${i+26} 题`)}).click();
    const radio=page.locator(`input[name="exam-${i+26}"][value="${i===20?"B":key[i]}"]`);
    if(i===0){await radio.focus();await page.keyboard.press("Space");}else await radio.check();
  }
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  await page.reload();await answersPane(page);
  await expect(page.locator(".exam-submit-bar")).toContainText("30 / 30");
  await page.getByRole("button",{name:"提交本板块",exact:true}).click();
  await expect(page.getByText("答对 29 / 30 题",{exact:true})).toBeVisible();
  const wrong=page.locator(".exam-analysis").filter({has:page.locator("summary>span",{hasText:/^第 46 题$/})});
  await expect(wrong).toContainText("你的答案 B · 参考答案 A");
  await expect(wrong).toContainText("组织生活是背景信息");
  await page.getByLabel("只看错题与未答题").check();
  await expect(page.locator(".exam-analysis")).toHaveCount(1);
  await wrong.getByRole("button",{name:"回到原卷第 10 页核对",exact:true}).click();
  await sourcePane(page);await expect(page.getByLabel("原卷页码",{exact:true})).toHaveValue("10");await answersPane(page);
  await page.screenshot({path:info.outputPath("reading-analysis-desktop.png"),fullPage:true});
  const saved=await(await page.request.get(base+"/reading")).json();
  expect(saved.first.correct).toBe(29);
  await page.getByRole("button",{name:"保留记录，重新作答",exact:true}).click();
  await expect(page.locator(".exam-submit-bar")).toContainText("0 / 30");
  expect((await(await page.request.get(base+"/reading")).json()).history_count).toBe(1);
  expect(errors).toEqual([]);
});

test("手机原卷切换、离线恢复、漏题提交和版本固定的听力答案",async({page,context},info)=>{
  test.setTimeout(240000);await page.setViewportSize({width:390,height:844});
  const {base}=await register(page);await open(page,"听力");
  await expect(page.locator(".exam-source-text")).toContainText("Listening Comprehension",{timeout:60000});
  const audio=page.getByLabel("本套原站听力录音");
  await expect.poll(()=>audio.evaluate((a:HTMLAudioElement)=>a.readyState),{timeout:60000}).toBeGreaterThanOrEqual(1);
  expect(await audio.evaluate((a:HTMLAudioElement)=>a.duration)).toBeGreaterThan(1000);
  await audio.evaluate(async(a:HTMLAudioElement)=>{a.muted=true;await a.play();});
  await expect.poll(()=>audio.evaluate((a:HTMLAudioElement)=>a.currentTime)).toBeGreaterThan(0);
  await audio.evaluate((a:HTMLAudioElement)=>a.pause());
  await answersPane(page);
  await page.getByRole("navigation",{name:"本板块题号"}).getByRole("button",{name:/^第 18 题/}).click();
  await page.locator('input[name="exam-18"][value="B"]').check();
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  await sourcePane(page);await expect(page.getByLabel("原卷页码",{exact:true})).toHaveValue("4");await answersPane(page);
  await expect(page.locator('input[name="exam-18"][value="B"]')).toBeChecked();
  await context.setOffline(true);
  await page.getByRole("navigation",{name:"本板块题号"}).getByRole("button",{name:/^第 1 题/}).click();
  await page.locator('input[name="exam-1"][value="A"]').check();
  await expect(page.locator(".exam-answer-pane .exam-error")).toBeVisible();
  await context.setOffline(false);
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  await page.reload();await answersPane(page);await expect(page.locator(".exam-submit-bar")).toContainText("2 / 25");
  await page.getByRole("button",{name:"提交本板块",exact:true}).click();
  await expect(page.locator("#exam-missing")).toContainText("还有 23 题未作答");
  await page.getByRole("button",{name:"仍然提交本板块",exact:true}).click();
  await expect(page.getByText("答对 1 / 25 题",{exact:true})).toBeVisible();
  const result=await(await page.request.get(base+"/listening")).json();expect(result.first.answers["18"]).toBe("B");
  await page.screenshot({path:info.outputPath("listening-analysis-mobile.png"),fullPage:true});
  await page.setViewportSize({width:320,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath("listening-320.png"),fullPage:true});
});

for (const kind of ["writing","translation"] as const) test(`${kind} 原稿恢复、单次提交和真实反馈或明确不可用状态`,async({page},info)=>{
  test.setTimeout(240000);
  const {base}=await register(page);await open(page,kind==="writing"?"写作":"翻译");
  await sourcePane(page);await expect(page.locator(".exam-source-text")).toContainText(kind==="writing"?"Writing":"Translation",{timeout:60000});
  await expect(page.locator(".exam-source-text")).not.toContainText("Listening Comprehension");await answersPane(page);
  const text=kind==="writing"?"Understanding traditional Chinese culture can help students explain their values with confidence. For example, learning why families celebrate traditional festivals helps us describe these customs clearly to friends from other countries. Confidence also requires curiosity and respect for different experiences.":"Technology improve medical care. Doctors can help patients in remote areas. Artificial intelligence helps doctors identify diseases early, while digital medical records reduce repeated examinations. Online consultations also make medical services more convenient.";
  await page.getByLabel("我的作答",{exact:true}).fill(text);
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  await page.reload();await answersPane(page);await expect(page.getByLabel("我的作答",{exact:true})).toHaveValue(text);
  await page.getByRole("button",{name:"提交本板块",exact:true}).click();
  await expect(page.getByLabel("首次提交的原稿",{exact:true})).toHaveValue(text);
  await expect.poll(async()=>{const result=await(await page.request.get(base+"/"+kind)).json();return result.review?.status;},{timeout:130000}).toMatch(/ready|unavailable|failed/);
  const saved=await(await page.request.get(base+"/"+kind)).json();
  expect(saved.first.text).toBe(text);
  if(process.env.PLAYWRIGHT_REAL_MODE==="1"){
    await info.attach(`${kind}-review`,{body:JSON.stringify(saved.review,null,2),contentType:"application/json"});
    expect(saved.review.status).toBe("ready");
    expect(saved.review.model).toBeTruthy();
    for(const correction of saved.review.content.suggestions)expect(text).toContain(correction.quote);
    await expect(page.getByRole("region",{name:"原稿分析"})).toContainText(saved.review.content.summary);
  }else expect(saved.review.status).toBe("unavailable");
  await page.getByRole("region",{name:"原稿分析"}).scrollIntoViewIfNeeded();
  await page.screenshot({path:info.outputPath(`${kind}-feedback.png`),fullPage:true});
});

test("保存响应丢失后的幂等重试与双窗口冲突保留输入",async({page,context})=>{
  const {base}=await register(page);await open(page,"写作");await answersPane(page);
  let lost=false;
  await page.route("**/cet6/exams/cet6-2026-06-1/writing",async route=>{
    if(route.request().method()==="POST"&&!lost){lost=true;await route.fetch();await route.abort("failed");}
    else await route.continue();
  });
  await page.getByLabel("我的作答",{exact:true}).fill("My first draft has already reached the server.");
  await expect(page.locator(".exam-answer-pane .exam-error")).toBeVisible();
  const acknowledged=await(await page.request.get(base+"/writing")).json();
  await page.getByRole("button",{name:"重试保存／提交",exact:true}).click();
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  expect((await(await page.request.get(base+"/writing")).json()).revision).toBe(acknowledged.revision);
  const other=await context.newPage();await other.goto(page.url());await answersPane(other);
  await page.getByLabel("我的作答",{exact:true}).fill("A newer draft saved in the first window.");
  await expect(page.locator(".exam-save-state")).toContainText("已保存到账号");
  await other.getByLabel("我的作答",{exact:true}).fill("My second window draft must remain available after a conflict.");
  await expect(other.locator(".exam-conflict")).toBeVisible();
  await expect(other.getByLabel("我的作答",{exact:true})).toHaveValue("My second window draft must remain available after a conflict.");
  await other.getByRole("button",{name:"保留本页输入，准备保存",exact:true}).click();
  await expect(other.locator(".exam-save-state")).toContainText("已保存到账号");
  expect((await(await page.request.get(base+"/writing")).json()).text).toBe("My second window draft must remain available after a conflict.");
  await other.close();
});

test("旧年份明确标记原站资料，200%布局与原卷答案区隐藏",async({page},info)=>{
  await page.setViewportSize({width:1440,height:980});await register(page);
  await page.locator(".cet6-main-nav").getByRole("button",{name:"真题练习",exact:true}).click();
  await page.locator(".exam-kind-grid").getByRole("button",{name:/阅读/}).click();
  await page.getByLabel("真题年份").selectOption("2024");
  await expect(page.getByRole("button",{name:"开始作答",exact:true})).toHaveCount(0);
  await expect(page.getByRole("link",{name:"查看原站资料 ↗",exact:true})).toHaveCount(6);
  await page.getByLabel("真题年份").selectOption("2026");await page.getByRole("button",{name:"开始作答",exact:true}).click();
  await sourcePane(page);await page.getByLabel("原卷页码",{exact:true}).selectOption("14");
  await expect(page.locator(".exam-source-text")).toContainText("54.",{timeout:60000});
  await expect(page.locator(".exam-source-text")).not.toContainText("答案速查");
  await page.getByRole("button",{name:"原版排版",exact:true}).click();
  await expect.poll(()=>page.locator(".exam-canvas-scroll canvas").evaluate((c:HTMLCanvasElement)=>c.width)).toBeGreaterThan(100);
  await expect(page.locator(".exam-reader-body")).toHaveAttribute("aria-busy","false");
  await page.screenshot({path:info.outputPath("source-original-page.png"),fullPage:true});
  await page.evaluate(()=>{document.documentElement.style.zoom="2";});
  await answersPane(page);await expect(page.getByRole("button",{name:"提交本板块",exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath("reading-200-percent.png"),fullPage:true});
});
