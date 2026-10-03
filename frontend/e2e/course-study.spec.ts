import { expect, test, type Page } from "@playwright/test";

async function register(page: Page) {
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  await page.getByPlaceholder("怎么称呼你").fill("章节学习验收");
  await page.getByPlaceholder("you@example.com").fill(`study-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.test`);
  await page.getByPlaceholder("至少 8 位").fill("Study-Journey-QA-2026!");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "新建课程" })).toBeVisible();
}
async function createCourse(page: Page, key: string) {
  const catalogue = await (await page.request.get("/api/notebooks/learning/catalogue")).json();
  const title = catalogue.items.find((c: { id: string }) => c.id === key).title;
  const dialog = page.getByRole("dialog", { name: "新建课程" });
  await dialog.getByRole("radio", { name: title, exact: true }).check();
  const created = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/notebooks");
  await dialog.getByRole("button", { name: "创建并进入", exact: true }).click();
  const id = (await (await created).json()).id;
  await expect(dialog).not.toBeVisible();
  if (key === 'cet6') {
    await expect(page.getByRole('heading', { name: '六级备考中心' })).toBeVisible();
    await page.goto(`/?notebook=${id}&cet6=references`);
  }
  await expect(page.locator('.course-study-card h1')).toBeVisible();
  const result = await (await page.request.get(`/api/notebooks/${id}/study`)).json();
  return { id, ...result };
}
async function pickSide(page: Page, unit: { title: string; group: string }) {
  const path = page.locator('.course-source-path:visible');
  const outline = path.locator('details').first();
  if (await outline.getAttribute('open') === null) await outline.locator(':scope > summary').click();
  const group = outline.locator('details').filter({ has: page.locator('summary', { hasText: unit.group }) }).first();
  if (await group.getAttribute('open') === null) await group.locator(':scope > summary').click();
  await group.getByRole('button', { name: unit.title, exact: true }).click();
}

test('五门课程直接进入章节，来源明确、右侧工具齐全、入口合并', async ({ page }, info) => {
  await page.setViewportSize({ width: 1560, height: 980 });
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await register(page);
  const counts: Record<string, number> = { cet6: 28, python: 10, ds_algo: 14, calculus: 14, english: 6 };
  for (const [key, count] of Object.entries(counts)) {
    if (key !== 'cet6') await page.getByRole('button', { name: '新建课程', exact: true }).click();
    const course = await createCourse(page, key);
    expect(course.path.units).toHaveLength(count);
    await expect(page.locator('.course-study-card h1')).toHaveText(course.path.units[0].title);
    await expect(page.getByRole('link', { name: '打开本节材料' })).toHaveAttribute('href', course.path.units[0].source.url);
    await expect(page.locator('.notebook-topbar a[href="/materials"], .notebook-topbar a[href="/library"]')).toHaveCount(0);
    await expect(page.locator('.course-study-card')).not.toContainText('小知六级指南');
    await expect(page.locator('.course-source-path')).toContainText(`${key === 'cet6' ? '备考参考' : '学习章节'} · ${count} 节`);
    if (key === 'cet6') {
      for (const title of ['互动讲解', '一图看懂', '框架导图', '学习笔记', '易错易混', '巩固测验', '记忆闪卡', '学习信息图', '知识数据表', '复习PPT', '讲解视频'])
        await expect(page.locator('.studio-tile').filter({ has: page.locator('strong', { hasText: title }) })).toBeVisible();
      await page.screenshot({ path: info.outputPath('course-study-desktop.png'), fullPage: true });
      await page.getByRole('button', { name: '打开起点测评', exact: true }).click();
      await page.getByText('查看已有测评记录', { exact: true }).click();
      await expect(page.getByText('这门课还没有历史测评记录。请继续当前章节学习。', { exact: true })).toBeVisible();
      await expect(page.locator('.entry-question-card')).toHaveCount(0);
      const unchanged = await (await page.request.get(`/api/notebooks/${course.id}/learning`)).json();
      expect(unchanged.course.kind).toBe('cet6');
      await page.locator('.course-source-path').getByRole('button', { name: '继续课程学习' }).click();
      await page.goto(`/?notebook=${course.id}&cet6=references`);
      await page.getByText('本课更多教材与真题', { exact: true }).click();
      await expect(page.locator('.course-study-more details')).toHaveCount(33);
    }
    if (key === 'python') {
      await page.getByText('直接阅读相关 Python 官方原文', { exact: true }).click();
      await expect(page.locator('.course-study-excerpts')).toContainText('PSF');
    }
    if (key === 'english') {
      await page.setViewportSize({ width: 390, height: 844 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath('course-study-mobile.png'), fullPage: true });
      await page.getByRole('button', { name: '学习来源', exact: true }).click();
      await pickSide(page, course.path.units[2]);
      await expect(page.locator('.course-study-card h1')).toHaveText(course.path.units[2].title);
    }
  }
  expect(errors).toEqual([]);
});

test('保存、完成下一节、刷新恢复、冲突草稿与失败时章节导航', async ({ page }, info) => {
  await page.setViewportSize({ width: 1560, height: 980 });
  await register(page);
  const course = await createCourse(page, 'cet6');
  const units = course.path.units;
  const notes = page.getByLabel('题号、学习结果或还不懂的地方');
  await notes.fill('核对官方考试结构；下一步练习选词。');
  await page.getByLabel('下次复习', { exact: true }).fill('2026-01-01');
  await page.getByRole('button', { name: '保存进度', exact: true }).click();
  await expect(page.locator('.course-study-notice')).toContainText(/进度已保存|已记录本节完成/);
  await page.reload();
  await expect(notes).toHaveValue('核对官方考试结构；下一步练习选词。');
  for (const label of ['已读 / 已听材料', '已完成本节任务', '已核对与订正']) await page.getByLabel(label, { exact: true }).check();
  await page.getByRole('button', { name: '完成本节，继续下一节', exact: true }).click();
  await expect(page.locator('.course-study-card h1')).toHaveText(units[1].title);
  await expect(page.locator('.course-study-top')).toContainText('已完成 1 / 28 节');
  await page.reload();
  await expect(page.locator('.course-study-card h1')).toHaveText(units[1].title);
  await pickSide(page, units[0]);
  await expect(page.locator('.course-study-card h1')).toHaveText(units[0].title);
  await expect(page.getByLabel('已核对与订正', { exact: true })).toBeChecked();
  await page.getByLabel('下次复习', { exact: true }).fill('2026-01-02');
  await page.getByRole('button', { name: '保存进度', exact: true }).click();
  await expect(page.locator('.course-study-notice')).toContainText(/进度已保存|已记录本节完成/);
  await expect(page.locator('.course-study-top')).toContainText('已完成 1 / 28 节');
  await notes.fill('我当前还没保存的订正');
  const saved = await (await page.request.get(`/api/notebooks/${course.id}/study`)).json();
  const other = await page.request.post(`/api/notebooks/${course.id}/study/${units[0].id}`, { data: { ...saved.progress.units[units[0].id], notes: '另一页面已保存的订正', revision: saved.progress.revision, version: saved.path.version } });
  expect(other.ok()).toBeTruthy();
  await page.getByRole('button', { name: '保存进度', exact: true }).click();
  await expect(page.locator('.course-study-error')).toContainText('另一页面已更新进度');
  await expect(notes).toHaveValue('我当前还没保存的订正');
  await page.getByRole('button', { name: '重新加载进度，保留草稿' }).click();
  await expect(page.locator('.course-study-notice')).toContainText('已读取服务器进度');
  await page.getByRole('button', { name: '放弃草稿，恢复已保存记录' }).click();
  await expect(notes).toHaveValue('另一页面已保存的订正');
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const studyURL = `**/api/notebooks/${course.id}/study/${units[0].id}`;
  await page.route(studyURL, async route => { await waiting; await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '保存暂不可用' }) }); });
  await notes.fill('失败后仍保留的草稿');
  await page.getByRole('button', { name: '保存进度', exact: true }).click();
  await pickSide(page, units[2]);
  release();
  await expect(page.locator('.course-study-card h1')).toHaveText(units[2].title);
  await page.unroute(studyURL);
  await pickSide(page, units[0]);
  await expect(notes).toHaveValue('失败后仍保留的草稿');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('.course-study-record').scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('course-progress-mobile.png'), fullPage: true });
});
