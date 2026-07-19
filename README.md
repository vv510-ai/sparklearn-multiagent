# SparkLearn 星火学伴 · 基于讯飞星火的多智能体个性化学习系统

第十五届"中国软件杯"大学生软件设计大赛 **A3 赛题**参赛作品。
面向《数据结构与算法》课程,以 **LangGraph 编排的 10 个核心智能体 + 2 个任务型节点**为核心,
实现"**对话建画像 → 规划学习路径 → 并行生成多模态资源 → 引用溯源防幻觉 → 答题评估闭环**"的完整个性化学习系统。

## 一图看懂架构

```mermaid
flowchart TD
    U[学生 · Web 前端 Next.js] -->|SSE 事件流| API[FastAPI 后端]
    API --> G{{LangGraph 编排图}}
    G --> PRF[画像智能体\n8 维随学随新]
    PRF --> ORC[编排器\n规则优先 / 星火 X2 兜底]
    ORC -->|generate| PLN[资源规划] --> PTH[路径规划\nBKT+知识图谱]
    PTH --> DOC[文档智能体\nRAG 引用]
    PTH --> MAP[思维导图\nmarkmap]
    PTH --> QUZ[题库智能体]
    PTH --> MED[媒体智能体\n小云雀/Manim+TTS]
    DOC & MAP & QUZ & MED --> EVL[评估智能体\n质检+落库]
    ORC -->|tutor| TUT[答疑导师\nOCR+流式+图解]
    EVL & TUT --> U
    DOC -.检索.-> KB[(教材向量库\nFastEmbed / 讯飞 / 哈希)]
    DOC -.溯源.-> GRD[grounding 校验\n星火 X2]
```

## 核心特性

1. **多智能体 DAG 编排**:LangGraph 条件路由 + 四资源节点真并行 fan-out/fan-in;前端 AgentTrace 遥测面板实时点亮每个智能体,过程全透明。
2. **8 维动态学生画像**:掌握度(BKT)、认知风格、易错点、目标、节奏、难度偏好、资源偏好、元认知;每次对话与答题"随学随新"。
3. **个性化路径规划**:课程知识图谱(17 节点 19 先修边)拓扑排序 + 掌握度阈值解锁 + 难度偏好打分,答题后自动重排。
4. **引用溯源防幻觉双层校验**:RAG 检索教材语料,正文 [^n] 脚注;星火 X2 做"答案-证据一致性"判定 + 版本化本地敏感词表。讯飞内容审核为预留挂接点,当前版本不发起远程审核。
5. **多模态资源**:图文教程、交互脑图、智能题组、代码练习、讲解视频(小云雀文生视频,失败自动降级为内置教学动画 + 讯飞 TTS 旁白)。
6. **学习闭环**:答题 → 提示/揭晓与错因复盘 → 无提示恢复测 → 1/3/7/14/30 天间隔复习 → BKT 更新掌握度 → 证据账本解释变化 → 路径重排。
7. **离线演示模式**:不配任何密钥也能完整跑通五大功能(MockEngine 模拟流式输出,内容标注演示数据),评委一键体验。

## 快速开始

### 方式一:Docker 一键部署(推荐)

```bash
cp .env.example .env        # 按需填写讯飞/小云雀密钥;留空 = 离线演示模式
docker compose up -d --build
# 前端 http://localhost:3000   后端文档 http://localhost:8000/docs
# 如需 Milvus 向量库:docker compose --profile vector up -d
```

### 方式二:本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端(另开终端)
cd frontend
npm install
npm run dev                 # http://localhost:3000
```

### 跑测试

```bash
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe tests\acceptance_rag_grounding.py
```

## 目录结构(摘要)

```
├── backend/                 FastAPI + LangGraph 多智能体后端
│   ├── app/agents/          10 个核心智能体 + 2 个任务型节点 + 编排图/事件总线
│   ├── app/rag/             语料切片 / 三级降级 Embedding / 向量库 / 检索引用
│   ├── app/safety/          grounding 一致性校验 + 内容安全过滤
│   ├── app/services/        BKT / 知识图谱 / 画像 / 路径规划
│   ├── app/llm/             星火统一封装 / TTS / 文生图 / OCR / 小云雀视频
│   ├── app/api/             SSE 接口层(chat / resources / path / tutor / eval)
│   └── app/data/            17 节点知识图谱 + 12 分节讲义 + 49 题种子题库
├── frontend/                Next.js 14 前端(深空蓝黑 · AgentTrace 遥测面板)
├── docs/                    五份赛事文档(开发/测试/环境/教程/代码结构)
└── docker-compose.yml       一键部署编排
```

## 文档索引

| 文档 | 说明 |
| --- | --- |
| [docs/开发说明书.md](docs/开发说明书.md) | 需求分析 · 系统设计 · 技术实现 · 创新点 |
| [docs/测试说明书.md](docs/测试说明书.md) | 功能/集成/性能/防幻觉测试用例与结果 |
| [docs/环境搭建指南.md](docs/环境搭建指南.md) | 密钥申请 · 依赖安装 · 部署与排错 |
| [docs/使用教程.md](docs/使用教程.md) | 五大功能完整操作流程(配截图位) |
| [docs/代码结构说明.md](docs/代码结构说明.md) | 模块职责 · 扩展指南 · 开源组件清单 |
| [docs/AI辅助开发说明.md](docs/AI辅助开发说明.md) | AI 工具使用范围 · 人工复核 · 能力状态声明 |

## 致谢与声明

- 核心学习问答优先使用讯飞星火模型族；编排器先走确定性规则，仅在规则未命中时由星火 X2 兜底。文生图仅使用讯飞能力，小云雀视频只在显式请求相应产物时调用。
- 开发过程以讯飞 iFlyCode 为主要 AI 辅助编码工具，也使用 Codex 等工具做代码审查、测试与文档校对；所有 AI 生成内容均经人工审查、重构与自动化测试，详见 [AI 辅助开发说明](docs/AI辅助开发说明.md)。

| 主要第三方组件 | 用途 | 许可证 |
| --- | --- | --- |
| FastAPI / LangGraph / SQLAlchemy | 后端与多智能体编排 | MIT |
| Next.js / React | Web 前端 | MIT |
| FastEmbed / ONNX Runtime | 默认本地向量化 | Apache-2.0 / MIT |
| Milvus / pymilvus（可选） | 向量库 | Apache-2.0 |
| NumPy / requests / httpx | 数值与网络访问 | BSD-3 / Apache-2.0 / BSD-3 |

完整依赖与许可证清单见 [docs/代码结构说明.md](docs/代码结构说明.md)。
