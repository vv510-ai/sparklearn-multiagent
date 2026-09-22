# Kimi 接入与模型选择（2026-09-22）

LearnLoop 复用原有 DeepSeek 与小云雀配置，新增 Kimi K3 承担资料整合、深度研究和复杂教学内容设计。开启服务端“智能搭配”后，无须用户填 API 或逐次选择：问答、英语、练习走现有 DeepSeek；笔记、研究、动画内容设计和知识图内容设计走 K3。图片、视频和语音服务保持现有配置；这里的 K3 文本路由不代表新增 Kimi 图片识别或 Kimi-Audio 服务。

模型设置提供三个一键保存方案：“智能搭配”“日常学习”“全程 K3”。个人模型与密钥表单收进可展开的自定义区域。已有账户显式选择优先于服务器默认搭配，未配置对应服务时按钮禁用并提示管理员连接。另保留 K2.6 作为可选模型及单供应商默认路由，已验证其文本、JSON 与流式协议。

这是根据产品任务、官方能力和费用作出的工程选择，没有做学习效果排名或跨模型质量基准。当天官方模型列表包括 K2.6、K2.7 Code、K2.7 Code Highspeed 和 K3；K2.5 已下线。K2.7 Code 主要面向编程，不作为通用学习默认模型。

## 官方依据

- [当前模型列表](https://platform.kimi.com/docs/models)
- [模型参数约束](https://platform.kimi.com/docs/api/models-overview)
- [K2.6 接口](https://platform.kimi.com/docs/guide/kimi-k2-6-quickstart)
- [K3 接口与权限](https://platform.kimi.com/docs/guide/kimi-k3-quickstart)
- [官方定价](https://platform.kimi.com/docs/pricing/chat)

中国站当日价格：K2.6 输入 ¥6.50 / 输出 ¥27 / 缓存命中输入 ¥1.10；K3 输入 ¥20 / 输出 ¥100 / 缓存命中输入 ¥2。单位均为每百万 token，K3 缓存写入另外按平台规则收费；后续以官方实时价格为准。K3 始终思考且需充值解锁，模型列表可见本身不代表实际调用可用。

## 配置

只在本地被 Git 忽略的 `.env` 或生产 `/opt/sparklearn/shared/.env` 配置：

```dotenv
# 保留原来的 DeepSeek 默认项与全部媒体配置，仅新增以下 Kimi 项。
KIMI_API_KEY=<平台密钥，仅保存于私密环境>
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=kimi-k2.6
KIMI_THINKING=disabled
KIMI_REASONING_EFFORT=high
KIMI_TIMEOUT_S=150
KIMI_SMART_ROUTING=true
```

“智能搭配”需要现有 DeepSeek 密钥与新增 Kimi 密钥都可用，并处于真实模式。无需改动 DeepSeek 或小云雀密钥。也可在账户“模型设置”一键启用“全程 K3”，只影响本账户。

单供应商部署仍可显式指定 `LLM_PROVIDER=kimi` 与 `KIMI_MODEL`；`auto` 保持现有 OpenAI、DeepSeek 优先级，然后选择 Kimi、Spark。文本接入不改变独立的图片生成、语音、视频供应商。

## 调用与失败行为

所有业务仍通过 `llm_complete()` / `llm_stream()`。复用现有 OpenAI SDK 和账户模型传输层，没有新增 SDK 依赖。

- K2.6 使用 `thinking` 与 `max_tokens`；K3 使用顶层 `reasoning_effort` 与 `max_completion_tokens`，不混用参数、不发送不受支持的 temperature。
- K3 小请求或显式关闭深度思考时使用 `low`（K3 无法完全关闭思考）；较大请求使用配置的 `high` / `max`，输出预算计入推理 token。
- Kimi 流式请求直接消费 SSE，只展示答案增量，不展示推理内容。空响应、截断或未正常结束均报错；输出一部分后失败也不会拼接其他模型或 Mock 内容。
- 严格 JSON 调用启用 `json_object`。只要求 JSON 文本的旧调用仍允许顶层数组。业务继续执行原有 schema 与来源校验。
- API 自动重试关闭，错误只记录安全类别与 HTTP 状态，避免请求正文或密钥出现在错误中。

## 验证与发布

`backend/tests/test_kimi_models.py` 覆盖默认路由、短请求预算、K3 参数、严格 JSON、真实 SSE 协议、推理隐藏、空输出/截断、额度错误、账户覆盖和离线模式。

真实验收使用合成学习内容：统一网关 JSON 问答、流式栈讲解，以及英语场景接口的模型生成 → schema 校验 → 原字幕对齐 → 数据库存储。测试使用独立数据库，密钥与原始环境文件不进入证据产物或版本库。

本次本地验证：后端 363 项通过，前端生产构建通过，浏览器 3 个用例通过（含方案保存、刷新持久化、手机布局和原有自定义设置）。K2.6 与 K3 分别完成上述三项真实调用；流式答案均分多段到达，英语场景均通过原字幕校验并保存为 `live` 资源。调用时长为单次样本，不用作性能或教学效果排名。

生产发布按 `ALIYUN_DEPLOYMENT.md` 执行。代码发布与生产密钥配置是独立步骤，Git 自动部署不携带 `.env`。必须复核生产版本、健康状态与实际 Kimi 业务请求，才能认定线上已启用搭配。停用默认搭配只需将 `KIMI_SMART_ROUTING=false` 并重建后端，账户显式选择仍按各账户配置生效。
