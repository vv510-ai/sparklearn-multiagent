# 对话优先界面：本地验收

## 状态

已按用户确认的融合稿完成本地实现和验收，尚未推送或部署到线上。

本地预览：<http://127.0.0.1:13000/>。使用独立本地 Demo 数据库，需本地注册或登录，不与线上账号数据共用。此地址只能在当前电脑访问，不能直接在另一台手机上使用。

## 本轮变化

- 手机只保留一行顶部导航，移除重复标题、目标说明条和常驻三项底栏。
- 点击课程名管理课程与资料；输入区加号提供资料、工坊、笔记和回答依据设置。
- 有资料时显示紧凑来源行；无资料时不占空间。“仅依据资料”始终可见，并允许取消最后一份资料。
- 白底正文、浅灰用户消息、折叠引用；输入文字独占整行，下方放工具按钮，保留自动增高及全屏编辑。
- 资料与工坊使用可退出、恢复焦点的对话框。平板双栏、电脑三栏及侧栏宽度调整继续可用。
- 修复关闭的依据面板仍给正文投射阴影的问题，精简空会话中的重复功能卡片。
- 没有改动后端评分、模型路由及学习规则；原有专注作答流程保留。

## 结果

- `npm run build`、`npm run typecheck`：通过。
- Chromium：31 项通过，其中新增 4 项融合稿验收、相关回归 27 项。
- 屏宽覆盖 320、360、390、430、640、768、900、1024、1280、1440、1920。
- 已验证资料取消与严格来源请求、工具打开、焦点返回、引用、复制、练习请求、新对话。
- 长消息和草稿恢复、中文输入、触屏换行、失败重试、账号隔离、练习提示和复盘、测评滚动、公式及引用回归通过。
- 视觉验收见根目录 `design-qa.md`，包含同图对照、修复记录及允许的差异。

## 截图

以下均为本地浏览器实际渲染。词汇对话与来源元数据为固定测试样例，不代表真实模型输出质量。

- 手机：`../.tmp/conversation-first-delivery/phone.png`
- 平板：`../.tmp/conversation-first-delivery/tablet.png`
- 电脑：`../.tmp/conversation-first-delivery/desktop.png`
- 全屏输入：`../.tmp/conversation-first-delivery/expanded-input.png`
- 专注作答：`../.tmp/conversation-first-delivery/focused-answer.png`
- 定稿对照：`../.tmp/conversation-first-delivery/comparison.png`

## 手动验收

1. 打开课程，确认没有重复标题和底栏，长课程名不挤走新对话与菜单。
2. 点击课程名选择或取消资料；在加号菜单切换为仅依据资料，核对可见状态。
3. 输入多行文字，展开编辑、返回、刷新，检查草稿；发送后展开引用原文。
4. 打开工坊再返回；进入练习，检查答案、提示和复盘仍可用。
5. 平板、电脑分别调整及收起侧栏，确认正文和发送按钮不被遮挡。

## 未覆盖

真实 iOS Safari、Android 系统键盘、微信浏览器、系统级大字体、生产模型及线上部署仍未验收。模拟视口缩短不等同于真机键盘，本地草稿不等同于跨设备草稿同步。

本轮没有后端改动，未重跑整套后端单元测试，没有把历史测试数计入本轮。发布需明确授权后另行验证生产版本与真实链路。

## 复跑

已启动本地前后端时，在 `frontend` 执行：

```powershell
$env:PLAYWRIGHT_BASE_URL = 'http://127.0.0.1:13000'
npx playwright test e2e/conversation-first.spec.ts e2e/responsive-workspace.spec.ts e2e/math-rendering.spec.ts e2e/generation-progress.spec.ts e2e/assessment-scroll.spec.ts e2e/citation-rendering.spec.ts e2e/automatic-learning.spec.ts e2e/learning-guidance.spec.ts --reporter=list
npm run build
npm run typecheck
```
