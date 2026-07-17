---
name: sparklearn-live-integration
description: 把 SparkLearn 从离线 demo 模式切到真实服务并逐项验证时使用——填 .env、关闭 demo_mode,对讯飞星火文本、OCR、TTS、文生图、小云雀视频逐个跑真实 smoke test,确认没有静默降级回 Mock,并在 docker 全链路上复验。只要任务涉及「真实密钥联调 / 填 .env / 关 demo / 上线前验证 / 答辩前真机验证 / 验证星火或 OCR 或 TTS 或文生图或小云雀真实调用 / docker 全链路复验」,就使用本 skill,即使用户没说「联调」也要触发。仅用于真实服务接入与验证;离线开发、加功能、跑单元测试请保持 demo 模式,不需要本 skill。
---

# 真实服务联调与冒烟验证(SparkLearn Live Integration)

把系统从离线 `demo_mode`(`MockEngine`)切到真实外部服务,逐项确认每个模态都能真实返回,并确保**没有静默降级**(`spark_client` 有互备 + MockEngine,`embedding` 有三级降级——一次调用即使真实服务挂了也可能"成功"返回兜底结果,所以验证要看引擎/档位指标,而不是只看 HTTP 200)。

> 这是真机联调,会消耗真实额度且依赖网络;**与离线单元测试分开**(默认 `pytest` 仍应离线可跑,不要把真实调用塞进默认测试集)。

## 开始前(必读)

1. **拿真实变量名,不要臆造**:读 `.env.example` 与 `backend/app/config.py`,枚举出每个服务实际需要的环境变量(以这两份为准)。各模态的 auth 形态可能不同(见下)。
2. **安全纪律**:密钥只进 `.env`;确认 `.env` 在 `.gitignore` 内,**不入库、不写进代码、不打印完整密钥到日志**。提交前 `git status` 确认没有 `.env`。
3. **准备测试素材**:一张题目图片(给 OCR / tutor)、一段待合成文本(给 TTS)、一个出题或视频主题(给生成链路)。

## 凭据清单(具体变量名以 `.env.example` / `config.py` 为准)

| 服务 | 对应模块 | auth 形态(参考) |
| --- | --- | --- |
| 星火文本大模型(核心 LLM) | `llm/spark_client.py` | OpenAI 兼容客户端,通常一个 API key |
| 语音合成 TTS(WebSocket) | `llm/spark_tts.py` + `llm/signing.py` | 讯飞三元组(APPID / APIKey / APISecret)+ HMAC 签名 |
| 拍照识题 OCR | `llm/spark_ocr.py` + `llm/signing.py` | 讯飞三元组 + HMAC |
| 文生图 | `llm/spark_image.py` + `llm/signing.py` | 讯飞三元组 + HMAC |
| 小云雀视频(异步) | `llm/xiaoyunque_client.py` | Bearer Access Key |
| (可选)向量化讯飞档位 | `rag/embedding.py` | 视配置;否则降级到 BGE-M3 / 哈希 |
| (可选)Milvus 向量库 | `rag/vector_store.py` | 连接串;否则用内存后端 |

## 步骤

### 1. 切到真实模式
按上表把密钥填入 `.env`(从 `.env.example` 复制起步)。`config.py` 会**自动判定** `demo_mode=False`。

**确认切换成功**:重启后端,调用健康 / 元信息接口(`backend/app/api/meta.py`)——引擎应不再是 `MockEngine`,而是真实星火引擎。这一步过不了,后面别测,先排查密钥 / config 读取。

### 2. 逐服务冒烟(建议按此顺序,从便宜到昂贵)

每条都给出"怎么触发"和"通过判据",并特别确认**没有降级**。建议在 `backend/` 下写一个独立冒烟脚本(如 `backend/scripts/smoke_live.py`),逐个直连各网关模块 + 跑一次端到端生成,**用密钥是否存在做开关,不并入默认 `pytest`**。

1. **星火文本(核心)**:发一次对话 / 生成请求,返回真实(非 Mock)文本。判据:健康接口显示真实引擎;返回内容不是 Mock 固定串。
2. **OCR**:把测试题目图喂给拍照识题(或 `tutor` 链路),返回识别文本。判据:文本与图片内容相符。
3. **TTS**:合成一段短文本(WebSocket),拿到音频。判据:音频可播放、时长合理。
4. **文生图**:生成一张图。判据:返回真实图片 URL / 字节,可打开。
5. **小云雀视频(异步)**:提交视频任务 → **轮询**至完成 → 拿到视频。判据:任务状态走到完成、视频可播且 `provider=xiaoyunque`;注意它是异步任务,要处理排队 / 超时;失败时系统会降级到 Manim+TTS,要能区分"真实小云雀成功"与"走了降级"。
6. **(可选)embedding 档位**:若配了讯飞向量化,确认实际走的是讯飞档而非哈希兜底(`embedding.py` 是 BGE-M3 → 讯飞 → 哈希三级降级)。
7. **(可选)Milvus**:若用 Milvus,确认连接成功而非回退内存后端。

### 3. 内容审核(已知 TODO,按需接入)
`backend/app/safety/guard.py` 目前是「本地敏感词 + 讯飞审核挂接点」,线上合规审核尚未真正接通。若本轮要补:在该挂接点接入讯飞内容审核 API,并验证一条敏感输入会被拦截 / 标记;否则在交付说明里明确"线上审核为预留挂接,当前以本地敏感词 + PII 脱敏为准"。

### 4. Docker 全链路复验
先在本地(非容器)跑通上面的冒烟以隔离"密钥问题",再 `docker compose up -d --build`,确认 PostgreSQL / Redis / 后端 / 前端容器都健康,然后**对容器化栈重跑一遍第 2 步冒烟**,确认没有环境差异(容器内网络、环境变量注入、卷挂载)。

## 通过判据(checklist)

- [ ] 健康 / 元信息接口显示 `demo_mode=False` 且引擎为真实星火(非 MockEngine)。
- [ ] 文本 / OCR / TTS / 文生图 / 小云雀五项各自返回真实产物,且确认**未静默降级**。
- [ ] 默认 `pytest` 仍离线全过(没被真实调用污染)。
- [ ] `docker compose up -d --build` 后容器健康,容器内冒烟同样通过。
- [ ] `git status` 无 `.env`;日志无完整密钥。

## 失败回退 / 现场预案

- 真机联调受网络 / 额度影响易抖动:**删除或重命名 `.env` 即可自动回到 `demo_mode` 离线演示**,保证有一条稳定可演示的链路。
- 建议在真实模式跑通后**录屏 + 截图留底**(画像更新 → 资源四件套 → 路径变化 → 做题评估 → AgentTrace 点亮),防现场翻车;答辩可在 demo 模式现演 + 真实模式录屏佐证。

## 常见坑

- 只看 HTTP 200 不看引擎 / 档位 → 把"降级到 Mock / 哈希 / Manim 兜底"误判成"真实服务通了"。
- 凭据变量名照搬本文表格而非 `.env.example` → 填错 key 名,真实服务连不上却静默走兜底。
- 真实调用混进默认 `pytest` → CI / 离线环境因缺密钥或额度而红。
- 本地通了直接上 docker → 容器内环境变量没注入、网络不通,问题被掩盖到答辩现场。
- `.env` 不小心被提交 → 密钥泄露;务必先确认 `.gitignore`。
