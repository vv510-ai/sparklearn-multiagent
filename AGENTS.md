# SparkLearn 星火学伴 · Codex 工作指南(AGENTS.md)

> 本文件每次会话都会被 Codex 读取,请保持稳定、精简(中途大改会让缓存前缀失效)。
> **改动任何代码前,先读本文件与 `docs/代码结构说明.md`;不要臆造文件路径,落笔前用文件树/检索确认真实路径再动手。**

## 项目是什么

基于讯飞星火的多智能体个性化学习系统。后端 **FastAPI + LangGraph**(含 `MiniGraph` 兜底)编排 10 个智能体:`profile / orchestrator / planner / path / doc / mindmap / quiz / media / tutor / eval`;前端 **Next.js 16 + React 19**(App Router + TypeScript)。当前课程为「数据结构与算法」。RAG 走「课程知识图谱 + 种子语料 + 上传资料 + 向量检索 + 引用溯源」。

## 运行与测试

- **后端测试**(离线可跑,基于 `backend/tests/_stubs.py`):通常 `cd backend && pytest`。任何后端改动后必须跑通。
- **前端构建**:`cd frontend && npm run build`。前端改动后必须通过。
- **全链路**:`docker compose up -d --build`(PostgreSQL / Redis / 前后端)。
- **运行模式**:无 `.env` 时 `app/config.py` 自动判定 `demo_mode=True`,LLM 走 `MockEngine` 离线引擎,**无需任何密钥即可跑测试与演示**。真实服务(星火 / OCR / TTS / 文生图 / 小云雀视频)需在 `.env` 填密钥后启用;密钥不入库、不写进代码。

## 不可破坏的铁律(违反会静默损坏并行 / 事件 / Mock 三件套)

1. **LLM 访问只允许经 `llm_complete()` / `llm_stream()`**(`backend/app/llm/spark_client.py`)。新增任何智能体都不得自建客户端——互备、Mock、计量都集中在这一层生效。
2. **事件一律经 `emitter.emit()` 发出**,以 `type` 字段区分种类。新增事件类型必须**同步**更新前端 `frontend/lib/types.ts` 与 `frontend/components/agent/AgentTrace.tsx` 的归约逻辑,否则前端遥测看不到。
3. **State 中任何可能被并行节点写入的字段,必须在 `backend/app/agents/state.py` 带 reducer 注解**。漏掉会导致并行写入互相覆盖(静默丢数据)。
4. **JSON 列(`payload` / `citations` / `safety` / `data`)直接存取 Python dict / list,严禁手工 `json.dumps` / `loads`**。
5. **资源 `kind` → 生成节点的映射集中在 `backend/app/agents/graph.py` 的 `_KIND2NODE`**;并行生成类节点同时要登记进 `_GEN_NODES`。

## 一次「生成请求」的数据流(便于定位)

`POST /api/resources/generate`(经前端 BFF `frontend/app/api/[...path]/route.ts` 透传)→ `backend/app/api/resources.py` 组装初始 State,交给 `graph.run_with_events()`(建请求级队列 + 把 emitter 写入 contextvar + 后台跑图 + 逐条 `data:` 回写 SSE)→ `profile` 更新画像 emit `profile` → `orchestrator` 路由 → `planner` 出资源计划 → `path` 重算 emit `path` → `doc / mindmap / quiz / media` 四节点并发(各自 retrieve→生成→校验→emit `resource`)→ `eval` 汇总 safety、批量落 `resources` 表、emit `summary` → 补发 `done`。

## 目录速览

- `backend/app/agents/`:多智能体层(每个 agent 一个文件 + `state.py` + `emitter.py` + `graph.py` + `orchestrator.py`)。
- `backend/app/llm/`:星火封装与多模态网关(`spark_client.py` 是**唯一** LLM 入口;另有 `spark_tts / spark_image / spark_ocr / xiaoyunque_client / signing`)。
- `backend/app/rag/`:`ingest / embedding / vector_store / retriever / citation`。
- `backend/app/services/`:`bkt`(贝叶斯知识追踪)/ `knowledge_graph` / `profile_service` / `path_service`。
- `backend/app/safety/`:`grounding`(答案-证据一致性)/ `guard`(敏感词 + 审核挂接 + PII 脱敏)。
- `backend/app/data/`:`knowledge_graph.json` / `seed_corpus/`(种子讲义)/ `seed_quiz.json` / `extra_sources/`。
- `backend/app/api/`:`chat / resources / path / tutor / evaluate / meta`(SSE 手写协议见 `sse.py`)。
- `backend/app/models/`:`db.py` + `entities.py`(6 张表)。
- `frontend/app/`:`page`(对话)/ `resources` / `path` / `eval` 页面 + `api/[...path]/route.ts` BFF 代理。
- `frontend/components/`:`agent/AgentTrace.tsx`(遥测面板)/ `resource/*`(`ResourceCard / QuizPlayer / Markmap / VideoBlock`)/ `path/PathDag.tsx` / `profile/ProfileRadar.tsx`。

## 何时用专门的 skill

仓库 `.agents/skills/` 下已有针对常见扩展的 skill,遇到对应任务时**按其步骤执行,不要自由发挥**:

- **换课程**(替换知识图谱 / 语料 / 题库 + 前端知识点名称映射)→ `sparklearn-swap-course`
- **新增一个智能体节点** → `sparklearn-add-agent`

## 提交与自动部署

- **唯一主生产网站是阿里云香港 ECS `https://47.76.129.100`**。当前主生产链路为:`GitHub main → ECS 每 2 分钟只读检查 → 新提交自动构建 → 健康检查 → 成功切换/失败回滚`。实现与运维说明见 `ALIYUN_DEPLOYMENT.md`；Vercel、Render、本地开发地址和其他服务器都不算本项目的最终部署结果。
- **部署是代码任务的强制完成条件,不是可选收尾。** 凡本轮因“修改、修复、新增、优化、继续”等要求实际改变了代码、Prompt、前端样式、部署配置或运行逻辑,必须执行:`运行相关测试 → 只暂存本轮改动 → commit → push origin main → 等待 ECS 自动部署 → 验证 https://47.76.129.100 → 验证本轮真实核心链路`。用户无需每次重复要求提交和部署；没有完成线上验证,不得声称任务已完成。
- 每次部署完成后必须在最终回复中报告:`已部署的 commit → 生产地址 → 首页/健康检查结果 → 本轮关键功能实测结果`。如果自动部署失败,应继续排查或明确报告阻塞,不能用“代码已写好”代替部署结果。
- 服务器上的临时热修复只能用于恢复故障,不能作为最终交付。故障恢复后必须把对应修改同步回仓库 `main`,重新走自动部署并确认线上运行版本来自该提交,避免下一次发布覆盖修复。
- 不得把仅存在于本地或服务器临时目录的代码当作已部署。应用代码、Compose、Nginx 与自动部署脚本必须先进入仓库 `main`;服务器仅保留 `.env`、数据库、上传资料、生成文件与部署密钥等运行时私有数据。
- Vercel / Render 暂时只作为迁移期回退入口,在阿里云完成最终验收前不要擅自删除;验收时以阿里云公网入口为准,不能只看构建成功。
- 纯问答、解释、只读摸底和诊断没有文件改动时不触发空部署。用户要求分阶段停下等待确认、测试失败、缺少平台认证或用户明确说“不提交/不部署”时,不得自动推送;应保留现场并说明阻塞。
- 工作区可能有用户或其他任务留下的改动。每次提交前先看 `git status` 和 diff,只提交当前任务确实涉及且已验证的文件,不得顺带提交、覆盖或回滚其他改动。
- `.env`、`.env.local`、API Key、Token、数据库、日志、缓存和本地运行产物永不提交。阿里云生产密钥只存 `/opt/sparklearn/shared/.env`,GitHub 部署私钥只存服务器 `/root/.ssh/`。

## 修改纪律

所有改动都必须能通过测试且可人工审查。AI 辅助生成的代码须经人工审查、重构、测试后再合入(符合赛题的 AI 辅助开发声明)。不确定文件路径或约定时,先读 `docs/代码结构说明.md` 与现有代码,再动手。
