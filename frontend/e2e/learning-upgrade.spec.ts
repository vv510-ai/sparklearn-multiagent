import { expect, test } from "@playwright/test";
import { parseAnswerChoices } from "../components/chat/AnswerChoices";
test.use({actionTimeout: 30_000});

test("选项解析保留题目顺序并排除已揭晓答案和代码", () => {
  expect(parseAnswerChoices("请选择：\nA. 左边\nB. 右边\nC. 两边\nD. 都不是").map(x => x.label)).toEqual(["A", "B", "C", "D"]);
  expect(parseAnswerChoices("请选择：\nA. 左边\nB. 右边\n答案：B")).toEqual([]);
  expect(parseAnswerChoices("请选择：\nA. 对 **数** 求导\nB. 对 **式** 求导\n**正确答案：B**")).toEqual([]);
  expect(parseAnswerChoices("```\nA. 左边\nB. 右边\n```")).toEqual([]);
  expect(parseAnswerChoices("功能列表\nA. 笔记\nB. 视频")).toEqual([]);
});

test("双平台课程、英语点击作答与离线研究状态", async ({page}, info) => {
  test.setTimeout(180_000);
  const marker = Date.now();
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.setViewportSize({width: 1512, height: 982});
  await page.emulateMedia({reducedMotion: "reduce"});
  const registration = await page.request.post("/api/auth/register", {data: {email:`upgrade-${marker}@example.test`, password:"Upgrade-e2e-2026!", name:"升级验收"}});
  expect(registration.status()).toBe(201);
  expect((await page.request.post("/api/onboarding", {data:{skipped:true}})).ok()).toBeTruthy();
  await page.goto("/");
  await page.getByRole("button", {name:"跳过引导",exact:true}).click();
  await expect(page.getByRole("button", {name:"模型设置",exact:true})).toHaveCount(0);

  await page.getByRole("button",{name:/推荐网课.*按知识点/}).click();
  await expect(page.locator(".course-card").first()).toBeVisible();
  await expect(page.locator(".course-card img").first()).toBeVisible();
  await page.getByLabel("视频来源").selectOption("youtube");
  await expect(page.locator(".course-card")).toHaveCount(1);
  await expect(page.getByRole("link",{name:/去 YouTube 观看/})).toHaveAttribute("href", /youtube\.com\/watch/);

  await page.getByRole("button",{name:/英语场景学习.*影视字幕/}).click();
  await page.getByRole("combobox",{name:"学习目标",exact:true}).selectOption("雅思");
  await page.getByRole("button",{name:"生成场景笔记"}).click();
  await expect(page.getByRole("alert").filter({hasText:"需要可用模型"})).toBeVisible();
  // Rendering/interaction fixture only. Real model evidence is recorded separately.
  await page.route("**/api/learning/english/scene", route => route.fulfill({json:{title:"周末计划",provenance:"原创教学场景，非真实影视台词",notes:"## figure out\n\n通过思考弄明白。",lines:[{speaker:"A",text:"We can figure it out.",translation:"我们能想明白的。",timestamp:""}],vocabulary:[{word:"figure out",meaning:"弄明白",usage:"figure it out",memory:"",contrast:""}],question:{stem:"figure out 在本句中表示什么？",options:["弄明白","离开","画画","迟到"],answer:"A",explanation:"指通过思考找到办法。"}}}));
  await page.getByRole("button",{name:"生成场景笔记"}).click();
  await expect(page.getByRole("group",{name:"英语练习选项"})).toBeVisible();
  await expect(page.getByRole("button",{name:"确认答案"})).toBeDisabled();
  await page.getByRole("button",{name:"A. 弄明白",exact:true}).click();
  await page.getByRole("button",{name:"确认答案"}).click();
  await expect(page.getByText("回答正确 · 答案 A",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"显示中文"}).click();
  await expect(page.getByText("我们能想明白的。",{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath("english-desktop.png"),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath("english-mobile.png"),fullPage:true});
  await page.setViewportSize({width:1512,height:982});
  await page.getByRole("button",{name:/深度研究.*检索真实/}).click();
  await page.getByLabel("想深入研究什么？").fill("间隔重复为什么帮助记忆");
  await page.getByRole("button",{name:"开始研究"}).click();
  await expect(page.getByText("离线演示 · 仅展示计划",{exact:true})).toBeVisible();
  await expect(page.getByRole("heading",{name:"可核对的来源 · 0"})).toBeVisible();
  await page.getByRole("button", {name:"返回", exact:true}).click();
  const question = "单选题：figure out 在本句中表示什么？\nA. 弄明白\nB. 离开\nC. 画画\nD. 迟到";
  const chatRequests: {message:string;display_message:string}[] = [];
  await page.route("**/api/chat", async route => {
    chatRequests.push(route.request().postDataJSON());
    const text = chatRequests.length === 1 ? question : "回答正确，figure out 表示通过思考弄明白。";
    await route.fulfill({contentType:"text/event-stream",body:[{type:"token",delta:text},{type:"done"}].map(e=>`data: ${JSON.stringify(e)}\n\n`).join("")});
  });
  await page.getByLabel("学习目标输入").fill("给我一道英语单选题");
  await page.getByRole("button", {name:"发送",exact:true}).click();
  await page.getByRole("group",{name:"点击选择答案"}).getByRole("button",{name:"A. 弄明白",exact:true}).click();
  await expect(page.getByText("回答正确，figure out 表示通过思考弄明白。",{exact:true})).toBeVisible();
  expect(chatRequests[1].message).toContain(question);
  expect(chatRequests[1].display_message).toBe("A. 弄明白");
  expect(errors).toEqual([]);
});
