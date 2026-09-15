# 模型API与GitHub复用决策

核验日：2026-09-15。目标：在现有FastAPI/LangGraph、Next.js与ECS架构内，升级课程问答、图像、视觉、转写、语音、视频和PPT，同时保留学习证据闭环及已有数据。

## 决策及边界

“最强”按课程事实正确性、资料约束、中文图文、可编辑性、稳定性、成本与真实学习任务衡量。现阶段选择官方旗舰候选与可核验接口；未完成同题盲评，不能声称本项目实测世界第一。GitHub项目解决接入、编排与文件生成，闭源模型权重不因有SDK而变成开源。

| 能力 | 首选及备选 | 选择理由与代价 | 官方依据 |
| --- | --- | --- | --- |
| 文本/推理 | GPT-6 Astra；已有DeepSeek V4 Pro兼容 | Astra用于复杂讲解和质量核对，保留中央入口。高推理档成本和延迟更高，短辅助调用降到low；不对学生答案中途拼接另一模型 | [Astra模型](https://developers.openai.com/api/docs/models/gpt-6-astra)、[DeepSeek V4 Pro正式发布](https://api-docs.deepseek.com/news/news260813/) |
| 一图看懂 | GPT-Image-2.5 Sunburst；Flare可配置 | Sunburst为精确生成/编辑的质量优先候选；Flare偏快速反馈。绘图不替代可读正文、结构图和引用 | [Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)、[图像API](https://developers.openai.com/api/docs/guides/image-generation) |
| 图片理解 | Astra视觉；本地OCR兼容 | 可识别公式与版面关系；标记不可辨认内容，不把图片中的命令当作系统指令 | [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) |
| 转写 | GPT Transcribe | 官方转写接口；浏览器raw PCM先封装WAV，24MiB本地上限 | [Speech to text](https://developers.openai.com/api/docs/guides/speech-to-text) |
| 中文旁白 | OpenAI gpt-4o-mini-tts、marin；Eleven v3可选 | OpenAI为当前已有密钥的接入路线，官方推荐marin/cedar；Eleven v3表达丰富，但需独立账户与授权音色，不能把未配置服务说成已启用。中文自然度需盲听 | [OpenAI TTS](https://developers.openai.com/api/docs/guides/text-to-speech)、[ElevenLabs模型](https://elevenlabs.io/docs/overview/models) |
| 概念视频 | Ark `doubao-seedance-2-5-260628`；已有小云雀兼容 | 官方模型目录返回该ID。异步提交一次、保存任务ID、轮询并持久化MP4；纯文本输入，保持水印，旁白走独立TTS。算法正确性仍靠确定性动画与资料校验 | [创建任务](https://www.volcengine.com/docs/82379/1520757)、[官方SDK任务实现](https://github.com/volcengine/volcengine-python-sdk/blob/master/volcenginesdkarkruntime/resources/content_generation/tasks.py) |
| 可编辑PPT | 统一文本主脑 + python-pptx | 幻灯片要点先校验，输出原生文本框，可修改；避免把图像拼接当成可编辑PPT。排版为稳定课程复习模板 | [python-pptx](https://github.com/scanny/python-pptx) |

音频、图片设模型和租户缓存；OpenAI Responses设置`store=false`，这不等于供应商零留存承诺。公开讲解支持可读降级，真实服务失败有错误状态；不会把离线样例标为新模型产物。

## GitHub候选与实际吸收

核验官方README、仓库元数据、许可入口与相关实现。星标数易变且不证明质量，本报告不据此排名。

| 候选 | 核验与取舍 | 本轮实际使用边界 |
| --- | --- | --- |
| [openai/openai-python](https://github.com/openai/openai-python) | 官方Python SDK，Apache-2.0；本机2.41.1，依赖约束2.41至3以下 | **直接依赖**：Responses、Images、Transcriptions、Speech；未复制源码 |
| [volcengine/volcengine-python-sdk](https://github.com/volcengine/volcengine-python-sdk) | 任务实现列出`/contents/generations/tasks`、create/get、content、duration等字段，Apache-2.0来源标记 | **接口参考**：用既有requests编写小型适配器，未复制SDK实现或安装大型SDK |
| [HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor) | Apache-2.0；多智能体学习、知识与练习工具的架构参照 | **设计参考**：对照本项目闭环与资料约束；没有搬入其代码、数据或宣称其效果 |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | 模型路由能力全面，但新代理增加运维与安全面；检查[官方安全公告](https://github.com/BerriAI/litellm/security/advisories)，许可需按具体目录版本复核 | **未引入**：现有统一网关足够本轮任务，不新增代理服务 |
| [docling-project/docling](https://github.com/docling-project/docling) | MIT；复杂文档理解可用于后续表格与版面增强；部署体积及模型依赖需评估 | **备选未安装**：当前保留原解析器和本地OCR，增加视觉API入口，不冒充已完成Docling迁移 |
| [elevenlabs/elevenlabs-python](https://github.com/elevenlabs/elevenlabs-python) | MIT；官方SDK/REST协议清晰，Eleven v3需要相应音色 | **REST对接**：适配完成，密钥/音色未配置，真实听测未完成 |
| [scanny/python-pptx](https://github.com/scanny/python-pptx) | MIT，稳定文件格式库；本轮固定1.0.2；更新频率不等于文件生成正确性 | **直接依赖**：输出可编辑幻灯片，经重开PPTX验证；未复制代码 |
| [ManimCommunity/manim](https://github.com/ManimCommunity/manim) | MIT；数学/算法动画可表达精确状态转移 | **保留原有实现**：不是本轮新增原创。生成式视频不替代确定性过程验证 |

没有采用需要导入用户Cookie轮换、未公开网页逆向接口或不明转售服务的项目。学校/参赛团队应在真实提交前按锁定依赖版本保留许可证清单，检查课程材料与自有改动的权属。

## 调研覆盖记录

- 本地：仓库AGENTS、代码结构、网关、媒体任务、提示词、事件、学习证据、依赖及测试；确认实际源码位于桌面仓库，原工作目录不是完整项目。
- 官方：OpenAI模型/图像/音频文档，DeepSeek发布说明，ElevenLabs模型与接口，火山官方SDK和文档。火山页面需JavaScript，web正文抓取失败后使用其公开文档API读取；创建文档更新时间2026-09-09。
- GitHub：官方SDK、学习智能体、统一网关、文档理解、语音、PPT及确定性动画；读取许可入口和当前维护元数据。
- 反证：API版本与字段、余额/权限、流式中断、缓存串租户、错误返回、语音格式、生成重试计费和平台安全公告。
- 关键词涵盖中文学习/一图看懂/视频API与英文tutor、Responses、image generation、transcription、content generation；查阅了近期模型目录与上游更新。
- 本轮是**针对现有架构的定向决策**。未完成全球候选饱和搜索，未进行独立模型排行榜复测，也没有验证所有备选模型的中文教育质量；这些限制不包装成已完成“全面最强测评”。

## 可行性实测与成本

本地现有OpenAI项目密钥可读取模型目录，但生成请求返回HTTP429 `credit_balance_exhausted`。因此API协议、缓存与失败处理经SDK MockTransport验证，真实生成仍需余额恢复。模型目录可见、拥有密钥与真实生成成功是三个不同状态。

火山官方模型列表返回Seedance 2.5 ID；是否开通该模型生成、实际完成耗时与费用另见验收记录。生产服务器直接OpenAI请求存在网络连接失败，需在目标服务器验证连通性；不能仅凭开发机可访问推断生产可用。

定价采用供应商当日账单/控制台，不能用“免费”“无限量”或固定单次金额承诺。当前设置生成请求不自动重试、视频10秒、图片n=1、文本输出预算，减少重复付费。录音/视频供应商返回成功才记作真实结果，失败不计入效果比较。
