# 个人普通 Chat「一图看懂」接入

本次按用户要求保留普通 Chat 网页生图，不切换图片 API，不增加管理面板。接入默认关闭，只为一个已经核实的 LearnLoop 账号启用；其他客户继续使用现有图片服务。

## 使用流程

本机运行接入程序并保持 Chrome 登录 ChatGPT。用户在 LearnLoop 点原有「一图看懂」：网站准备并核对知识底稿 → 持久任务排队 → 本机新建普通 Chat 对话 → 发送一次提示 → 等图片完成 → 点击原生下载 → 按页面与下载 GUID 核对原图 → 自动回传 → 网站保存图片、核对结果和文字版。正常流程不需要复制提示词或手动上传。

程序运行期间复用专用 CLI 连接，退出、单次验证结束或出现异常时断开；不关闭用户 Chrome，不安装开机启动。首次连接可能需要在 Chrome 中允许调试。电脑关机、睡眠、断网或程序未运行时不能代替本机生成。

## 改动范围

- `services/personal_image.py`、`api/personal_image.py`、`PersonalImageJob`：账号绑定、一次一项领取、租约、提交前确认、超时和有界原图接收。
- 统一多模态网关与 `one_page_image.py`：仅绑定账号使用 `chatgpt_web`，禁止失败后转用图片 API；沿用现有文字、公式、关系检查，检查失败最多按现有规则修正一次。
- BFF 与认证中间件：独立配对令牌仅能访问图片接入接口，不能作为网站登录凭据；远程传输要求 HTTPS。
- `StudyArtifactBlocks.tsx`、评估摘要及生成状态：显示原图、未完成/待核对提示与文字版。图片返回成功不等于内容正确。
- `personal_chat_image_worker.py`、配对和启动脚本：官方 Chrome DevTools CLI 操作可见页面，Chrome 下载事件绑定当前对话与文件；不读取 Cookie、账号令牌或调用 ChatGPT 私有接口。

## 配置

服务器私有环境文件设置：

```dotenv
PERSONAL_CHAT_IMAGE_ENABLED=true
PERSONAL_CHAT_IMAGE_OWNER_ID=<已核实的 LearnLoop user_id>
PERSONAL_CHAT_IMAGE_WORKER_TOKEN_SHA256=<本机配对工具生成的 SHA-256>
```

同时需要原有真实模式、图片功能及持久任务配置启用：`DEMO_MODE=false`、`MM_IMAGE_ENABLED=true`、`GENERATION_JOBS_ENABLED=true`。后端与 generation-worker 使用一致的上述环境。

在本机已安装 Python 依赖及官方 Chrome DevTools CLI 后，用 `scripts/pair_personal_chat_image.py --help` 查看参数。指定网站 HTTPS origin、已核实账号 ID、Node/CLI 路径、Chrome 实际下载目录和用户私有状态目录。工具生成随机配对令牌，仅将明文保存在本机 `worker.json`，输出给服务器的只有哈希。拒绝覆盖已有配对，避免静默换令牌。配对文件与状态目录不得提交到 Git。

启动：`scripts/start_personal_chat_image.ps1 -Config <本机 worker.json 路径>`。首次可附加 `-CheckBrowser` 只检查登录和连接；`-Once` 完成一项后断开退出；另开命令附加 `-Stop` 可要求当前程序结束等待、断开浏览器并退出。连续模式在无任务时低频轮询，不自动点击重试。停止程序后服务器仍保留已完成图片。

## 故障与安全边界

- 登录失效、验证码、浏览器授权、额度限制或页面改版时停止，交由本人处理。没有账号池、代理轮换或规避限额机制。
- 发送前持久确认；发送结果不明确时停止，防止自动重复消耗额度。过期任务不发送，旧心跳不能影响新任务。
- 已完成图片上传可幂等重试，但不同图片不能覆盖同一任务。仅接受有效 PNG/JPEG/WebP、20 MB 以内、非动画及受限像素数；原图归属绑定到本人，另一账号不能读取。
- 配对令牌不是 ChatGPT 令牌，不授予聊天、课程、账号设置等业务 API 权限。撤销时关闭服务端开关并停止本机程序；泄露时重新生成配对并更新服务端哈希。
- 原生网页路线依赖页面结构和 Chrome 状态，不是 OpenAI 提供的受支持后台图片 API。普通 Chat 页面已实测生图；尚未对账证明具体额度扣减，不能承诺全天候稳定或其他用户可共用订阅。

## 验证记录（持续补齐）

- 2026-10-15：普通 Chat 的真实请求已生成 1672×941 PNG；原生下载按页面 frame 与下载 GUID 匹配成功，原图 1,546,661 字节，SHA-256 `ce0ce12497fa576903ef63cc2b3b8757d76f41a9b30421f2bebc909162361bb0`。
- 人工看图发现队列示例被画成“1、2、1”，而底稿是“1、2、3”，因此本图不能标为内容通过。自动回传后必须保留现有核对边界。
- 账号隔离、错误令牌、不可跨业务 API、领取竞争、发送后失联不重发、上传验证、幂等上传、取消、关闭后回到原服务、临期任务、旧心跳、延迟图片状态与并发下载归属：25 项针对性测试通过。
- 合入生产站 `64f4e71b` 词典更新后，完整后端测试 912 项通过，前端正式构建及 16,020 个单词音频校验通过。
- 随后以预核对底稿完成真实队列 → 普通 Chat → 下载 → 上传 → 资源保存 → 浏览器展示。返回图 SHA-256 `18c9492bb1e678aa79043a04771d86af28c95b9ac07189d6da3e6c64d8058cd8`；原图已人工查看，关键出入顺序与循环队列公式正确。图片理解服务不可用，网站实际显示“图片已生成，仍需核对”，保留文字版；第二账号访问原图返回 404。测试程序已通过停止指令正常退出并断开 Chrome。
- 首次本地网站点击流程在原有星火底稿生成阶段超时，未进入生图；不能把固定底稿运输测试当作完整点击验收。生产上线与正式账号的原有按钮流程尚待完成。

源码依据：[Chrome DevTools 官方 CLI](https://github.com/ChromeDevTools/chrome-devtools-mcp)、[Chrome 下载事件与 GUID](https://chromedevtools.github.io/devtools-protocol/tot/Browser/)、[ChatGPT 图片说明](https://learn.chatgpt.com/docs/image-generation)。浏览器协议中的 `filePath` 为可选字段，本程序缺失时停止，绝不按公共下载目录里的相似文件名猜测归属。
