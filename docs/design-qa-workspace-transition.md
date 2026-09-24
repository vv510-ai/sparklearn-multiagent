# SparkLearn 首页到学习工作台转场 Design QA

- source visual truth:
  - `C:\Users\26054\AppData\Local\Temp\codex-clipboard-b23692e3-ae01-4513-84b8-a3085b7cbd7c.png`
  - `C:\Users\26054\AppData\Local\Temp\codex-clipboard-e79e7d95-6c87-402c-ae4c-cf4303adde02.png`
- implementation screenshots:
  - `C:\Users\26054\AppData\Local\Temp\sparklearn-design-qa\landing.png`
  - `C:\Users\26054\AppData\Local\Temp\sparklearn-design-qa\transition.png`
  - `C:\Users\26054\AppData\Local\Temp\sparklearn-design-qa\workspace.png`
- combined comparison evidence: `C:\Users\26054\AppData\Local\Temp\sparklearn-design-qa\comparison.png`
- viewport: 1280 × 720
- state: 学生身份；输入“我想系统掌握递归与分治”；从首页进入工作台

## Full-view comparison evidence

组合图左侧为用户参考图，右侧为本地浏览器实现。首页保留了同一星空视频、暖光书桌、衬线标题、玻璃输入框、人物头像和底部身份卡；工作台保留白色三栏结构、浅灰页面底色和学习工坊的六张柔和彩色卡片。实现截图进入后显示真实生成内容，而参考图显示空状态，这是既有产品行为差异，不是布局漂移。

## Focused comparison evidence

本次新增部分是全屏转场，因此使用 `transition.png` 检查白色学习纸面从首页输入区域附近展开、品牌状态文案居中、星空背景退后，以及工作台落位时的淡入。无需额外局部裁图：文字、图标和卡片细节均沿用已验证的现有组件，新变化只发生在全屏运动与挂载时序。

## Findings

- 没有 P0、P1 或 P2 问题。
- Fonts and typography: 首页继续使用 Instrument Serif，正文与工作台继续使用 Inter/中文系统字体；转场状态文案保持 13px、700 字重，不抢主标题层级。
- Spacing and layout rhythm: 转场表面从圆角输入区域展开至全屏，820ms 后工作台落位；1280 × 720 下无裁切、重叠或持久控件位移。
- Colors and visual tokens: 过渡纸面使用 `#F3F5FA`，与工作台浅灰背景一致；星芒继续使用现有暖金/绿色状态逻辑。
- Image quality and asset fidelity: 继续复用原星空视频与三张角色头像，没有新增占位图、CSS 插画或低清替代资产。
- Copy and content: “正在铺开你的学习工作台”描述当前状态，短且可在转场完成前读完。
- Interaction and accessibility: 提交后身份、上传与开始按钮会暂时禁用，避免重复提交；根节点设置 `aria-busy`；`prefers-reduced-motion: reduce` 时跳过动画并在约 40ms 内进入工作台。
- Browser evidence: 首页输入、提交、工作台落位和真实生成链路均通过；浏览器控制台 error 数为 0。

## Comparison history

- Pass 1: 对照首页、转场中帧与工作台落位截图；未发现需要修复的 P0/P1/P2 差异，因此没有进入第二轮修复。

## Implementation checklist

- [x] 星空首页内容分层退场
- [x] 白色学习纸面从输入区域展开
- [x] 三栏工作台淡入落位
- [x] 防重复提交
- [x] 减少动态效果支持
- [x] 浏览器交互与控制台检查

## Follow-up polish

- P3: 后续若提供明确的 Figma 动效时间轴，可进一步对齐缓动曲线和逐帧节奏。

final result: passed
