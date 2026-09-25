# SparkLearn Trace 调试手册

这份文档说明如何使用 `backend/runs/{run_id}/` 里的中间产物定位问题。

## 1. Trace 是什么

Trace 是一次多智能体运行的完整调试包。每次调用下面这些流式接口时，后端都会自动记录：

```text
POST /api/chat
POST /api/resources/generate
POST /api/tutor
```

输出目录：

```text
backend/runs/{run_id}/
```

`run_id` 每次执行随机生成，原 `session_id` 仍记录在请求和摘要中用于关联对话；重试与同一对话的下一轮各自保留目录，不覆盖历史。
前端资源页会在本次生成区显示 `TRACE {run_id}` 与完整 `run_dir`，可以直接按这个编号打开对应目录。
也可以点击资源页里的“查看报告”，它会读取：

```text
GET /api/debug/runs/{run_id}
```

## 2. 最先看哪个文件

优先顺序：

```text
1. debug_report.md
2. summary.json
3. timeline.json
4. state.summary.json
5. events.jsonl
```

### debug_report.md

给人看的总览。重点看：

```text
route
resources
errors
safety_warnings
Agent Status
```

如果只是想快速知道“这次跑到哪一步、有没有资源、有没有错误”，先看它。

### summary.json

给程序或进一步分析看的总览。重点看：

```text
event_counts
route
resources
state
files
```

### timeline.json

按顺序列出每个关键事件。适合排查：

```text
哪个 agent 没启动
哪个 agent 没结束
resource 是什么时候产生的
progress 卡在哪个 stage
error 出现在第几个事件
```

### state.summary.json

最终状态的精简版。适合看：

```text
intent 是否正确
knowledge_points 是否正确
kinds 是否正确
path.next_kp 是什么
生成了几个 resources
retrieval/citations/safety 数量是否异常
```

### events.jsonl

原始 SSE 事件流，一行一个 JSON。适合和前端 Network 面板对照。

## 3. 常见问题怎么查

### 页面没有新资源

按顺序看：

```text
timeline.json
events.jsonl
resources/index.json
final.resources.json
```

判断：

```text
如果没有 resource 事件：生成 agent 没产出，查 agent_end 和 final_state。
如果有 resource 事件但前端不显示：查 resource.kind 和 payload 是否符合 docs/api_contract.md。
如果资源有但数据库没有：查 eval agent 或落库逻辑。
```

### 最终内容很差

先不要直接改 UI。按顺序查：

```text
request.json
profile.output.json
planner.output.json
path.output.json
retrieval.output.json
resources/
agent_end/
eval.output.json
```

判断：

```text
profile 错：改 profile_agent prompt 或画像合并逻辑。
planner 错：改 planner_agent prompt 或输入字段。
path 错：改 path_service / path_agent。
retrieval 错：改 RAG 数据源、embedding、reranker。
resource 错：改 doc/quiz/mindmap/media agent。
eval 错：改 eval_agent 质检规则。
前面都对但页面错：改 frontend 组件。
```

### 视频不显示

看：

```text
resources/video_*.json
events_by_type/progress_*.json
```

重点字段：

```text
payload.video.status
payload.video.task_id
payload.video.url
payload.manim_code
payload.cover_url
```

约定：

```text
前端只用 payload.video.url 播放视频。
没有真实小云雀 Access Key 时，应该降级到 manim_code / script，不应该报错中断。
```

### 答题后画像没变

看：

```text
POST /api/eval/submit 的返回
backend/runs/{run_id}/profile.output.json
backend/runs/{run_id}/state.summary.json
```

同时查数据库：

```text
profiles
quiz_attempts
event_logs
```

### 前端 `/api/*` 返回 500

先判断是不是后端问题：

```powershell
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:3000/api/health
```

如果 8000 正常、3000 报错，说明问题在前端代理或 Next 开发服务。今天实测遇到过：

```text
Cannot find module './379.js'
Require stack:
frontend/.next/server/webpack-runtime.js
```

这是 `.next` 开发缓存损坏，不是业务接口坏。处理方式：

```powershell
cd C:\Users\26054\Desktop\sparklearn-multiagent\frontend
# 停掉占用 3000 的旧 npm/next 进程
Remove-Item .next -Recurse -Force
npm run dev
```

重启后再跑：

```powershell
cd C:\Users\26054\Desktop\sparklearn-multiagent\backend
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe scripts\debug_api_flow.py --base-url http://127.0.0.1:3000
```

如果这条通过，说明浏览器 → Next BFF → FastAPI → SSE 的前后端链路是通的。

## 4. 文件说明

```text
request.json
```

本次请求进入图之前的初始状态。

```text
events.jsonl
events.json
```

完整 SSE 事件。`events.jsonl` 适合逐行排查，`events.json` 适合程序读取。

```text
timeline.json
```

压缩后的关键事件时间线。

```text
debug_report.md
```

人类可读的调试报告。

```text
agent_status.json
```

每个 agent 的开始、结束、状态、摘要。

```text
state.summary.json
```

最终状态精简摘要。

```text
final_state.json
```

完整最终状态，字段最多。

```text
profile.output.json
planner.output.json
path.output.json
eval.output.json
```

关键阶段输出。

```text
resources/
```

每个资源单独保存一份 JSON，并带 `index.json`。

```text
agent_end/
```

每个 agent 的 `agent_end` 原始事件。

```text
agent_outputs/
```

有非空 output 的 agent 输出。

```text
retrieval.output.json
citations.output.json
safety_flags.output.json
progress_events.output.json
```

最终状态中的检索、引用、安全、进度数据。

```text
events_by_type/
citations/
```

按事件类型拆出的辅助文件。

## 5. 给队友的调试要求

队友反馈 bug 时，至少给这三个文件：

```text
debug_report.md
summary.json
events.jsonl
```

如果是资源质量问题，再给：

```text
resources/
profile.output.json
planner.output.json
path.output.json
retrieval.output.json
```

如果是前端展示问题，再对照：

```text
docs/api_contract.md
frontend/lib/types.ts
frontend/components/resource/ResourceCard.tsx
```
