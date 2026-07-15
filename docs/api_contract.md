# SparkLearn 前后端接口契约

本文档是前端、后端、Agent 调试共同遵守的接口说明。后续改接口时，必须先改这里，再改代码。

## 1. 基本约定

- 前端地址：`http://127.0.0.1:3000`
- 后端地址：`http://127.0.0.1:8000`
- 后端 Swagger：`http://127.0.0.1:8000/docs`
- 前端统一通过 `/api/*` 请求后端，由 `frontend/app/api/[...path]/route.ts` 代理到 FastAPI。
- 默认用户：`demo_user`
- JSON 字段使用 `snake_case`，例如 `user_id`、`quiz_resource_id`。
- 流式接口使用 SSE，返回 `Content-Type: text/event-stream`。
- 非流式接口返回普通 JSON。

前端调用封装：

```text
frontend/lib/api.ts
  postSSE(path, body, onEvent, onClose)
  apiGet<T>(path)
  apiPost<T>(path, body)
```

前端类型定义：

```text
frontend/lib/types.ts
```

后端请求模型：

```text
backend/app/schemas/core.py
```

## 2. SSE 事件契约

SSE 每一帧格式：

```text
data: {"type":"agent_start","agent":"profile","detail":"..."}

```

也就是一行 `data: JSON`，后面跟一个空行。

通用事件字段：

```ts
type SparkEvent = {
  type:
    | "agent_start"
    | "agent_end"
    | "agent_token"
    | "token"
    | "resource"
    | "profile"
    | "path"
    | "progress"
    | "citations"
    | "safety"
    | "summary"
    | "trace"
    | "error"
    | "done";
  ts?: string;
  agent?: string;
  label?: string;
  detail?: string;
  summary?: string;
  delta?: string;
  resource?: ResourceItem;
  profile?: StudentProfile;
  path?: PathPlan;
  items?: string[];
  text?: string;
  percent?: number;
  stage?: string;
  level?: string;
  output?: Record<string, unknown>;
  session_id?: string;
  run_dir?: string;
}
```

事件含义：

| type | 什么时候发 | 前端用途 |
| --- | --- | --- |
| `agent_start` | 某个 agent 开始工作 | AgentTrace 节点变为 running |
| `agent_end` | 某个 agent 结束 | AgentTrace 节点变为 done，保存 output 到 trace |
| `token` | 答疑文本流式输出 | Chat 逐字追加回答 |
| `agent_token` | agent 内部 token 输出 | 预留调试用 |
| `resource` | 生成一个资源卡片 | 资源页/聊天页追加 ResourceCard |
| `profile` | 画像更新 | ProfileRadar 刷新 |
| `path` | 路径更新 | PathDag 刷新 |
| `progress` | 长任务进度 | 视频、OCR、媒体生成进度 |
| `citations` | 引用来源 | 展示教材/资料来源 |
| `safety` | 安全或防幻觉提示 | 展示警告或进入 trace |
| `summary` | 本轮生成总结 | 资源页 note / eval summary |
| `trace` | 本次运行调试目录已创建 | 展示 `session_id` 与 `backend/runs/{session_id}` |
| `error` | 后端异常 | 前端展示错误 |
| `done` | SSE 流结束 | 前端停止 loading |

真实 `resource` 事件帧形态以后端为准,资源对象挂在 `resource` 字段下,不要使用 `data` / `payload` 二次包裹:

```text
data: {"type":"resource","resource":{"id":"...","kind":"quiz","kp":"binary_tree","title":"...","payload":{},"citations":[]}}

```

合法 agent id：

```text
profile | orchestrator | planner | path | doc | mindmap | quiz | media | tutor | eval
```

## 3. 核心数据结构

### 3.1 ResourceItem

资源卡片统一结构：

```ts
type ResourceItem = {
  id: string;
  kind: "doc" | "code" | "reading" | "mindmap" | "quiz" | "video" | string;
  kp: string;
  title: string;
  payload: ResourcePayload;
  citations: string[];
  created_at?: string;
}
```

不同资源类型的 `payload`：

| kind | payload 字段 | 前端组件 |
| --- | --- | --- |
| `doc` | `{ markdown, grounded, audio_url?, cover_url?, remediation? }` | Markdown + 星火 TTS 口播 + 可选封面；补救微课带诊断元数据 |
| `code` | `{ markdown, grounded }` | Markdown |
| `reading` | `{ markdown, grounded }` | Markdown |
| `mindmap` | `{ markmap }` | Markmap |
| `quiz` | `{ questions, difficulty }` | QuizPlayer |
| `video` | `{ script, video, manim_code, audio_url, cover_url }` | VideoBlock |

### 3.2 QuizQuestion

```ts
type QuizQuestion = {
  id: string;
  type: "single" | "fill" | "judge" | "design" | "complexity";
  stem: string;
  options: string[];
  answer: string;
  explain?: string;
  kp: string;
  difficulty: number;
  error_tags: string[];
}
```

真实 LLM 可能返回更细的子主题名作为题目 `kp`。后端生成题组时会把每题 `kp` 归一为所属资源的 `kp`,确保 `/api/eval/submit` 更新的是课程知识图谱中的同一个知识点。

### 3.3 StudentProfile

```ts
type StudentProfile = {
  knowledge_mastery: Record<string, number>;
  cognitive_style: string;
  error_prone: string[];
  goal: string;
  pace: string;
  difficulty_pref: string;
  resource_pref: Record<string, number>;
  metacognition: number | string;
  version?: number;
}
```

### 3.4 PathPlan

```ts
type PathPlan = {
  nodes: PathNode[];
  edges: { from: string; to: string }[];
  next_kp: string | null;
  generated_by?: string;
  updated_at?: string;
  remediation?: LearningDiagnosis;
}
```

```ts
type PathNode = {
  id: string;
  name: string;
  mastery: number;
  status: "done" | "ready" | "locked";
  difficulty: number;
  score: number;
  reason: string;
  order?: number;
}
```

## 4. 接口列表

### 4.1 健康检查

```http
GET /api/health
```

返回：

```json
{
  "status": "ok",
  "demo_mode": true,
  "course": "数据结构与算法",
  "llm": "MockEngine(离线演示)",
  "app": "SparkLearn 星火学伴"
}
```

用途：确认后端是否启动。

### 4.2 知识图谱

```http
GET /api/kg
```

返回：

```json
{
  "course": "数据结构与算法",
  "nodes": {
    "binary_tree": {
      "name": "二叉树",
      "difficulty": 3
    }
  },
  "edges": [
    { "from": "array", "to": "binary_tree" }
  ]
}
```

用途：路径页渲染 DAG。

### 4.3 学生画像

```http
GET /api/profile/{user_id}
```

示例：

```http
GET /api/profile/demo_user
```

返回：`StudentProfile`

用途：画像面板、路径规划、资源个性化。

### 4.4 学习对话

```http
POST /api/chat
Content-Type: application/json
Accept: text/event-stream
```

请求：

```json
{
  "user_id": "demo_user",
  "session_id": "s1",
  "message": "我两周后考试，帮我规划二叉树复习"
}
```

返回：SSE 事件流。

典型事件顺序：

```text
agent_start(profile)
profile
agent_end(profile)
agent_start(orchestrator)
agent_end(orchestrator)
...
done
```

如果判定为答疑，还会出现：

```text
agent_start(tutor)
token
citations
agent_end(tutor)
done
```

### 4.5 资源生成

```http
POST /api/resources/generate
Content-Type: application/json
Accept: text/event-stream
```

请求：

```json
{
  "user_id": "demo_user",
  "goal": "两周后期末，希望用可视化方式理解二叉树",
  "knowledge_points": ["binary_tree"],
  "kinds": ["doc", "mindmap", "quiz", "video"],
  "source_ids": ["demo_user_ab12cd34_note"]
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `user_id` | string | 否 | 默认 `demo_user` |
| `goal` | string | 否 | 用户自然语言学习目标 |
| `knowledge_points` | string[] | 是 | 目标知识点 id |
| `kinds` | string[] | 是 | 要生成的资源类型 |
| `source_ids` | string[] | 否 | 指定已上传资料；为空时使用全局知识库 |

返回：SSE 事件流。

典型事件顺序：

```text
agent_start(profile)
profile
agent_end(profile)
agent_start(orchestrator)
agent_end(orchestrator)
agent_start(planner)
agent_end(planner)
agent_start(path)
path
agent_end(path)
agent_start(doc/mindmap/quiz/media)
resource
...
agent_start(eval)
summary
agent_end(eval)
done
```

### 4.6 资源列表

```http
GET /api/resources?user_id=demo_user&kind=quiz&kp=binary_tree&limit=50
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `user_id` | string | 否 | 默认 `demo_user` |
| `kind` | string | 否 | 资源类型过滤 |
| `kp` | string | 否 | 知识点过滤 |
| `limit` | number | 否 | 默认 50 |

返回：

```json
{
  "items": [
    {
      "id": "quiz_binary_tree_xxx",
      "kind": "quiz",
      "kp": "binary_tree",
      "title": "二叉树·智能题组",
      "payload": {
        "questions": []
      },
      "citations": [],
      "created_at": "2026-06-16T00:00:00+00:00"
    }
  ]
}
```

### 4.7 资源详情

```http
GET /api/resources/{rid}
```

返回：单个 `ResourceItem`

错误：

```json
{
  "detail": "resource not found"
}
```

状态码：`404`

### 4.8 视频任务查询

```http
GET /api/resources/video/task/{task_id}
```

返回：

```json
{
  "status": "running",
  "task_id": "xxx",
  "url": "",
  "error": "",
  "reason": ""
}
```

视频 payload 约定：

```ts
video?: {
  status?: "running" | "succeeded" | "failed" | "timeout" | "degraded" | string;
  url?: string;
  task_id?: string;
  error?: string;
  reason?: string;
}
```

前端只读 `video.url` 播放最终视频。

### 4.9 学习路径

```http
GET /api/path?user_id=demo_user
```

返回：`PathPlan`

如果数据库没有路径，后端会根据当前画像即时规划并保存。

### 4.10 主动重排路径

```http
POST /api/path/replan
Content-Type: application/json
```

请求：

```json
{
  "user_id": "demo_user",
  "reason": "评估后重排"
}
```

返回：`PathPlan`

用途：答题后、目标变化后、手动刷新路径。

### 4.11 获取逐题学习支持

```http
POST /api/eval/support
Content-Type: application/json
```

请求必须带上学习者已经写下的尝试，`mode` 可选 `hint` 或 `reveal`：

```json
{
  "user_id": "demo_user",
  "quiz_resource_id": "quiz_binary_tree_xxx",
  "question_id": "q1",
  "mode": "hint",
  "attempt": "A"
}
```

`hint` 只返回不含答案的确定性脚手架；`reveal` 返回参考答案、解析和题目错因标签。空尝试会返回 `400`，资源和题目必须属于当前用户。

### 4.12 提交答题

```http
POST /api/eval/submit
Content-Type: application/json
```

请求：

```json
{
  "user_id": "demo_user",
  "quiz_resource_id": "quiz_binary_tree_xxx",
  "kp": "binary_tree",
  "answers": [
    {
      "question_id": "q1",
      "answer": "A",
      "correct": true,
      "seconds": 12,
      "hint_used": true,
      "revealed": false,
      "misconception": "",
      "confidence": "unsure"
    }
  ],
  "behavior": {
    "dwell_seconds": 120,
    "help_clicked": false
  }
}
```

返回：

```json
{
  "accuracy": 0.8,
  "per_kp": [
    {
      "kp": "binary_tree",
      "name": "二叉树",
      "n": 5,
      "right": 4,
      "mastery_right": 4,
      "supported": 1,
      "confidence_recorded": 5,
      "confident_wrong": 1,
      "uncertain_correct": 1,
      "mastery": 0.72,
      "level": "..."
    }
  ],
  "error_tags": {},
  "suggestions": [],
  "calibration": {
    "recorded": 5,
    "score": 0.66,
    "confident_wrong": 1,
    "uncertain_correct": 1,
    "metacognition_before": 0.5,
    "metacognition_after": 0.54
  },
  "diagnosis": {
    "status": "needed",
    "action": "remediate",
    "blocked_kp": "heap",
    "blocked_name": "堆与优先队列",
    "prerequisite_gap": "binary_tree",
    "prerequisite_name": "二叉树",
    "remediation_kp": "binary_tree",
    "remediation_name": "二叉树",
    "misconception": "父子关系判断错误",
    "reason": "先补二叉树，再回到堆完成无提示复测。",
    "attempt": 1,
    "max_attempts": 3
  },
  "behavior": {}
}
```

后端始终按题组资源重新判分，不信任客户端的 `correct`。`correct` 表示原始判分，`mastery_correct` 表示写入 BKT 的学习证据；题目一旦揭晓，即使答案正确也不会被算作独立掌握，并且提交前必须从白名单中选择一项自评错因。`confidence` 可选 `guess / unsure / confident`，必须在查看提示或结果前记录。信心不会直接修改 BKT；仅独立作答会把信心与真实判分对照，用于识别“自信误判”和“答对但不稳”，并平滑更新 `profiles.metacognition`。使用提示或揭晓的题会保留信心记录，但不进入校准。旧客户端不传该字段时维持原行为。

副作用：

- 写入 `quiz_attempts`
- 更新 `profiles.knowledge_mastery`
- 更新 `profiles.error_prone`
- 有信心证据时更新 `profiles.metacognition`
- 写入 `event_logs`
- 触发路径重排

诊断由后端根据独立作答证据、提示/揭晓、自评错因、知识图谱先修关系和既有掌握度确定。`action` 为 `remediate` 或 `reteach` 时，`path_plan.remediation` 会覆盖下一学习点；首次补救后仍未恢复则转为 `schedule_review`，不无限循环生成微课。

### 4.13 生成补救微课与迁移复测

```http
POST /api/eval/remediation
Content-Type: application/json
```

请求：

```json
{
  "user_id": "demo_user",
  "attempt_id": 42
}
```

返回：

```json
{
  "diagnosis": {
    "status": "needed",
    "action": "remediate",
    "blocked_kp": "heap",
    "remediation_kp": "binary_tree",
    "reason": "先补二叉树，再回到堆完成无提示复测。"
  },
  "resource": {
    "id": "...",
    "kind": "doc",
    "kp": "binary_tree",
    "title": "二叉树·补救微课",
    "payload": {
      "markdown": "...",
      "grounded": true,
      "remediation": {
        "origin_attempt_id": 42,
        "blocked_kp": "heap",
        "prerequisite_gap": "binary_tree",
        "misconception": "父子关系判断错误",
        "next_action": "retest"
      }
    },
    "citations": ["课程讲义 · 二叉树 p.1"]
  },
  "transfer_quiz": {
    "id": "...",
    "kind": "quiz",
    "kp": "heap",
    "title": "堆与优先队列·迁移复测",
    "payload": {
      "questions": ["3 道同概念、不同题面的新题"],
      "transfer_retest": true,
      "origin_attempt_id": 42,
      "origin_quiz_resource_id": "quiz_heap_xxx",
      "source_ids": ["原测验继承的资料 ID"]
    },
    "citations": ["课程讲义 · 堆 p.1"]
  },
  "next_action": "retest",
  "reused": false
}
```

这是普通 JSON 接口，不使用 SSE。它恢复原测验的 `source_ids`，并要求资料正文或元数据明确命中待补概念；没有足够证据时返回 `next_action: "select_source"`，不会用通用知识补写。成功时同时写入补救微课和 3 道迁移新题，迁移题不得复用或近似改写原题题干，重复请求复用同一组资源。资源 ID 会写入 `quiz_attempts.detail.remediation`，前端由 `RemediationPanel` 消费。记录不存在返回 `404`，诊断不需要补救或字段不完整返回 `409`，资料归属错误返回 `400`，生成失败返回 `503`。

### 4.14 无提示恢复/迁移复测

```http
POST /api/eval/retest
Content-Type: application/json
```

首轮 `/api/eval/submit` 会返回 `attempt_id` 和 `retest`：没有触发补救诊断时，答错或已经揭晓、因而没有形成独立掌握证据的原题会进入 `eligible_question_ids`。若触发补救诊断，则先调用 `/api/eval/remediation`，再把返回的 `transfer_quiz.id` 作为 `quiz_resource_id`，一次提交其中全部新题。

```json
{
  "user_id": "demo_user",
  "quiz_resource_id": "quiz_binary_tree_xxx",
  "attempt_id": 42,
  "answers": [
    {
      "question_id": "q2",
      "answer": "n+1",
      "seconds": 8,
      "confidence": "confident"
    }
  ]
}
```

复测规则：

- 必须一次提交该答题记录的全部待恢复题。
- 迁移复测资源必须由该 `attempt_id` 的补救接口生成并登记，不能替换为任意测验。
- 不允许提示或揭晓，所有答案由后端重新判分。
- 同一个 `attempt_id` 只能完成一次复测，重复提交返回 `409`。
- 独立答对会作为新的 BKT 证据更新掌握度，并再次触发画像、脑图标签和路径重排。

返回的 `retest` 示例：

```json
{
  "status": "completed",
  "eligible": 2,
  "recovered": 1,
  "remaining": 1
}
```

复测明细保存在原 `quiz_attempts.detail.retest` 中，便于后续展示恢复轨迹，不会伪装成一次新的首轮成绩。

### 4.15 今日间隔复习队列

```http
GET /api/eval/review-queue?user_id=demo_user&limit=10
```

返回今天已经到期的题目以及队列统计。题目对象只包含题干、选项、类型、难度和知识点，**不会返回答案或解析**。

```json
{
  "items": [
    {
      "id": 7,
      "quiz_resource_id": "quiz_binary_tree_xxx",
      "question_id": "q2",
      "kp": "binary_tree",
      "kp_name": "二叉树",
      "stage": 1,
      "due_at": "2026-07-16T08:00:00+00:00",
      "reason": "遍历性质混淆",
      "question": {
        "id": "q2",
        "type": "single",
        "stem": "...",
        "options": ["..."],
        "difficulty": 2
      }
    }
  ],
  "summary": {
    "due": 1,
    "upcoming": 3,
    "mastered": 2,
    "next_due_at": "2026-07-18T08:00:00+00:00",
    "interval_days": [1, 3, 7, 14, 30]
  }
}
```

### 4.16 提交今日复习

```http
POST /api/eval/review
Content-Type: application/json
```

```json
{
  "user_id": "demo_user",
  "items": [
    {
      "review_item_id": 7,
      "answer": "B",
      "seconds": 9,
      "confidence": "unsure"
    }
  ]
}
```

后端会校验题目确实属于当前用户且已经到期，然后重新判分并写入 BKT。连续独立答对按 `1 → 3 → 7 → 14 → 30` 天推进；答错会重置到 1 天并增加 `lapse_count`。完成全部间隔阶段后状态变为 `mastered`。

### 4.17 学习证据账本

```http
GET /api/eval/evidence?user_id=demo_user&limit=12
```

按时间倒序返回首次作答、无提示复测和间隔复习的证据轮次。接口不会返回学生答案或参考答案，只展示解释掌握度变化所需的聚合字段。`raw_correct` 是原始判对数，`mastery_correct` 是真正进入 BKT 的答对证据；两者不同通常表示学生在揭晓答案后答对，不能据此判定已经掌握。

```json
{
  "items": [
    {
      "phase": "retest",
      "answers": 1,
      "raw_correct": 1,
      "mastery_correct": 1,
      "supported": 0,
      "calibration": {
        "recorded": 1,
        "score": 0.9,
        "confident_wrong": 0,
        "uncertain_correct": 0,
        "metacognition_before": 0.5,
        "metacognition_after": 0.6
      },
      "knowledge_points": [
        {
          "kp": "binary_tree",
          "name": "二叉树",
          "mastery_before": 0.42,
          "mastery_after": 0.66,
          "mastery_delta": 0.24
        }
      ]
    }
  ],
  "summary": {
    "rounds": 3,
    "answers": 4,
    "raw_correct": 3,
    "mastery_correct": 2,
    "supported": 1,
    "independent": 3,
    "confidence_recorded": 3,
    "confident_wrong": 1,
    "uncertain_correct": 1,
    "calibration_score": 0.57,
    "by_phase": { "initial": 1, "retest": 1, "spaced_review": 1 }
  }
}
```

历史变化由已有 `quiz_eval` 事件从旧到新重建，因此升级后可以直接解释过去的评估记录，无需迁移数据库。

### 4.18 学情报告

```http
GET /api/eval/report?user_id=demo_user
```

返回：

```json
{
  "profile": {},
  "radar": [
    { "kp": "binary_tree", "name": "二叉树", "mastery": 0.72 }
  ],
  "weakest": [],
  "strongest": [],
  "attempts": {
    "total": 3,
    "accuracy": 0.8
  },
  "events": [
    {
      "etype": "quiz_eval",
      "payload": {},
      "ts": "2026-06-16T00:00:00+00:00"
    }
  ]
}
```

### 4.19 多模态答疑

```http
POST /api/tutor
Content-Type: application/json
Accept: text/event-stream
```

请求：

```json
{
  "user_id": "demo_user",
  "question": "为什么 Dijkstra 不能处理负权边？",
  "image_base64": "",
  "want": "auto"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | string | 用户 id |
| `question` | string | 文本问题 |
| `image_base64` | string/null | 预留拍照搜题/OCR |
| `want` | `"text" | "diagram" | "video" | "auto"` | 希望的回答形态 |

返回：SSE 事件流，常见事件为 `agent_start`、`progress`、`token`、`citations`、`safety`、`agent_end`、`done`。

### 4.20 调试报告

```http
GET /api/debug/runs/{session_id}
```

返回：

```json
{
  "session_id": "5b4d27cd",
  "run_dir": "C:\\Users\\26054\\Desktop\\sparklearn-multiagent\\backend\\runs\\5b4d27cd",
  "debug_report": "# SparkLearn Debug Report\n...",
  "summary": {},
  "state": {},
  "agent_status": {},
  "resources": [],
  "timeline": []
}
```

用途：资源页根据 SSE 的 `trace.session_id` 拉取本次调试包,展示事件统计、资源列表和 `debug_report.md`。

### 4.21 知识资料入库

上传学习资料并立即重建本地向量索引：

```http
POST /api/knowledge/upload
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | File | 是 | 支持 `.txt`、`.md`、`.pdf`、`.png`、`.jpg`、`.jpeg`，单文件最大 8MB；图片在上传时 OCR 一次并缓存到 sidecar |
| `user_id` | string | 否 | 默认 `demo_user` |
| `kp` | string | 否 | 资料对应知识点，例如 `binary_tree` |
| `title` | string | 否 | 展示标题，不填则使用文件名 |

返回：

```json
{
  "source": {
    "id": "demo_user_ab12cd34_note",
    "user_id": "demo_user",
    "title": "二叉树课堂笔记",
    "filename": "note.txt",
    "kp": "binary_tree",
    "source_type": "uploaded_text | uploaded_pdf | uploaded_image",
    "bytes": 1024,
    "chunk_count": 3,
    "status": "indexed",
    "status_detail": "索引已完成，可以参与回答和学习资源生成",
    "selectable": true,
    "degraded": false,
    "created_at": "2026-06-17T12:00:00+00:00",
    "updated_at": "2026-06-17T12:00:03+00:00",
    "indexed_at": "2026-06-17T12:00:03+00:00"
  },
  "vector_count": 120,
  "sample": [
    {
      "text": "片段预览...",
      "citation": "二叉树课堂笔记 p.1"
    }
  ]
}
```

列出已上传资料：

```http
GET /api/knowledge/sources?user_id=demo_user
```

资料生命周期统一为：

| `status` | `selectable` | 含义 |
| --- | --- | --- |
| `processing` | `false` | 文件已接收，正在解析或建立索引 |
| `indexed` | `true` | 索引完成，可参与回答与资源生成 |
| `degraded` | `true` | 使用了降级 OCR/解析，可使用但应核对引用 |
| `failed` | `false` | 解析或索引失败 |
| `quarantined` | `false` | 因内容范围或治理规则被隔离 |
| `inactive` | `false` | 已停用 |

前端只能根据 `selectable` 决定资料能否被选择，不得自行推断状态；具体原因展示 `status_detail`。

验证检索：

```http
GET /api/knowledge/search?query=二叉树中序遍历&kp=binary_tree&limit=5
```

返回：

```json
{
  "items": [
    {
      "text": "命中的资料片段...",
      "citation": "二叉树课堂笔记 p.1",
      "source": "二叉树课堂笔记",
      "source_id": "demo_user_ab12cd34_note",
      "source_type": "uploaded_text",
      "kp": "binary_tree",
      "score": 0.82
    }
  ]
}
```

存储位置：上传原文和元数据只保存在本机 `backend/app/data/uploaded_sources/`，该目录被 `.gitignore` 忽略，不提交到 GitHub。

图片资料的 OCR 文本物化在同名 `.meta.json` 的 `ocr` 字段中。索引重建和后续检索只读取该缓存，不会重复调用 OCR；OCR 失败时上传返回可读的 `400 detail`，并清理未完成文件。

## 5. 前后端对齐规则

### 5.1 后端为准

接口字段以后端返回为准。前端如果需要新增展示字段，先在本文件补契约，再改后端，再改前端。

### 5.2 SSE 必须有 done

所有 SSE 流最后必须发送：

```json
{ "type": "done" }
```

前端依靠它停止 loading。

### 5.3 错误必须有 detail

错误事件统一：

```json
{
  "type": "error",
  "detail": "可读错误说明"
}
```

HTTP 错误也尽量使用：

```json
{
  "detail": "resource not found"
}
```

### 5.4 ResourceCard 不猜字段

前端资源卡片只按 `kind` 判断 payload：

- `mindmap` 必须给 `payload.markmap`
- `quiz` 必须给 `payload.questions`
- `video` 必须给 `payload.script` 或 `payload.video`
- 其他文本类资源必须给 `payload.markdown`

### 5.5 视频 URL 统一叫 url

后端、数据库、前端统一使用：

```json
{
  "video": {
    "url": "https://..."
  }
}
```

不要再使用 `video_url`。

## 6. 调试检查清单

### 6.0 自动契约测试

每次改 SSE 事件、ResourceItem、题目结构、视频 payload、路径字段后,先跑：

```powershell
cd C:\Users\26054\Desktop\sparklearn-multiagent\backend
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe tests\test_api_contract.py
```

这个测试会按本文件契约校验：

```text
1. SSE type 是否都在白名单内
2. agent id 是否合法
3. resource 是否包含 id/kind/kp/title/payload/citations
4. doc/code/reading 是否有 payload.markdown
5. mindmap 是否有 payload.markmap
6. quiz 是否有 payload.questions
7. video 是否有 payload.script/video/manim_code
8. 所有 SSE 是否以 done 结束
9. trace 是否包含 session_id/run_dir
```

### 6.1 前端页面没反应

检查：

```text
http://127.0.0.1:3000
http://127.0.0.1:8000/api/health
```

然后打开浏览器 Network 面板，看 `/api/...` 请求是否：

- 状态码不是 200
- SSE 没有 `done`
- 返回字段和本契约不一致

### 6.2 资源生成了但页面不显示

按顺序查：

1. SSE 是否收到 `resource`
2. `resource.kind` 是否合法
3. `resource.payload` 是否有对应字段
4. 数据库 `resources.payload` 是否保存完整
5. 前端 `ResourceCard` 是否支持该 kind

### 6.3 最终效果差但不知道哪里错

查看：

```text
backend/runs/{session_id}/
```

重点文件：

```text
request.json
events.jsonl
profile.output.json
planner.output.json
path.output.json
resources/
agent_end/
final_state.json
summary.json
```

## 7. 新增接口前必须补齐的内容

新增接口时，在本文件补：

```text
1. URL 和 method
2. 请求 JSON
3. 返回 JSON
4. 是否 SSE
5. 会写哪些数据库表
6. 前端由哪个组件消费
7. 失败时返回什么
```

没有写进契约的字段，前端不要依赖。
