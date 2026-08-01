# Agent Teams、LangChain 文档 MCP 与 HITL 能力校准

检查日期：2026-08-02
适用项目：SparkLearn 星火学伴

> 课程截图曾把文件名写成 `agnet_teams_langchain_mcp_setup.md`。`agnet` 是 `agent` 的拼写残留，本项目采用正确文件名 `agent_teams_langchain_mcp_setup.md`，不复制错误拼写。

## 1. 一页结论

- 当前 Codex 环境具备多 Agent 协作能力，但本轮没有启动子 Agent：任务规模小、修改集中在同一组前端测试文件，并行编辑会增加冲突，收益不够。
- 当前环境可以正常调用 LangChain 官方文档 MCP。2026-08-02 的真实查询已返回 LangGraph `interrupt`、`Command(resume=...)` 与 checkpointer 的官方说明。
- **LangChain 的文档 MCP 主要负责获取官方最新的文档规范，不等于业务运行时本身。** SparkLearn 线上请求不经过这个 MCP。
- 课程语音中的 “Interpreter” 是误识别；人机协作这里对应的是 LangGraph `interrupt`（中断），不是“解释器”。
- SparkLearn 当前没有“必须等待教师批准才能继续”的产品阻塞点，因此本轮不把 HITL 强行加入学生学习主链路。

## 2. 检查过程与结果

| 检查项 | 怎么检查 | 实际结果 | 证据强度 |
| --- | --- | --- | --- |
| 多 Agent 协作能力 | 检查当前 Codex 会话暴露的协作工具与项目规则 | 协作能力可用；本轮按任务边界选择单 Agent 执行 | 强：当前运行环境直接可见 |
| LangChain 文档 MCP 是否存在 | 检查当前可调用工具 | 存在 `search_docs`、文档文件系统查询和反馈工具 | 强：当前工具清单直接可见 |
| MCP 是否真的连通 | 查询 “LangGraph Python interrupt human-in-the-loop Command resume checkpointer” | 返回官方 HITL、interrupt、resume、checkpointer 页面与示例 | 强：真实调用成功并返回官方页面 |
| SparkLearn 是否依赖该 MCP 运行 | 检查后端依赖、启动方式和请求链路 | 业务运行使用 FastAPI + LangGraph；没有请求经过文档 MCP | 强：当前仓库与运行链路 |
| 当前是否需要 HITL | 对照学生主链路与课程的人工审批场景 | 当前是即时学习，不存在强制教师审批门；暂不实现 | 中强：当前产品流程和代码，未来需求可能改变 |

本次连通性验证命中的官方文档：

- [LangChain Human-in-the-loop：Responding to interrupts](https://docs.langchain.com/oss/python/langchain/human-in-the-loop#responding-to-interrupts)
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers#why-use-checkpointers)

## 3. 三个概念分别是什么

### 3.1 Agent Teams：开发时的协作方式

通俗理解：像临时组建一个开发小组，把“调研、后端、前端、测试”等互不覆盖的工作分给不同成员。

它解决的是开发过程的并行分工，不是 SparkLearn 线上十个学习智能体的运行框架。只有任务能独立拆分、文件边界清楚、结果能分别验证时才值得使用。

### 3.2 LangChain 文档 MCP：开发时的官方说明书入口

通俗理解：像一本会自动更新的官方电子说明书。它告诉开发者最新 API 怎样写、参数怎样传、旧写法是否变了。

它不会替学生回答问题，不会替 LangGraph 编排节点，也不会自动把功能“接进”项目。查到文档之后仍要由开发者修改代码并运行最小实验。

### 3.3 HITL / `interrupt`：业务运行时的人机审批

通俗理解：自动流水线走到高风险步骤时先踩刹车，把信息交给人审核；人选择批准、拒绝或修改后，流程从原位置继续。

正式实现通常至少需要：

1. `interrupt(...)` 暂停图执行并给出待审信息；
2. checkpointer 保存暂停时的状态；
3. 稳定的 `thread_id` 找回同一次执行；
4. 审核界面展示 approve / reject / edit；
5. `Command(resume=...)` 携带人工决策恢复执行；
6. 审批人、时间、原内容和修改内容写入审计记录。

## 4. 对 SparkLearn 的采用边界

| 能力 | 当前决定 | 将来什么时候重新评估 |
| --- | --- | --- |
| Agent Teams | 不作为项目依赖；仅在明确并行研发任务中临时使用 | 至少有两个独立模块、不同文件所有权、各自验收标准明确 |
| LangChain 文档 MCP | 保留为按需开发工具，不写入生产请求链 | 升级 LangGraph、实现 `interrupt`、迁移 checkpointer 或遇到版本 API 不确定时 |
| HITL | 暂不进入学生即时学习链路 | 教师必须批准学习材料发布、敏感内容、付费/删除等高风险动作时 |
| 教师审核界面 | 当前不是已交付管理端 | 产品明确教师角色、审核对象、权限和审计要求后 |

## 5. 最小验证实验与过关标准

本轮的最小实验不是编写一个假的 HITL Demo，而是验证“开发工具边界”本身：

1. 从当前环境调用 LangChain 文档 MCP；
2. 搜索 `interrupt` 与 `Command(resume=...)`；
3. 必须返回官方页面和可识别的暂停/恢复说明；
4. 核对 SparkLearn 运行配置，确认生产不依赖该 MCP；
5. 把查询日期、结果和暂不采用理由写入本文件。

结果：通过。MCP 已真实连通；HITL 只完成概念和采用条件校准，没有冒充已实现业务功能。

## 6. 你应该学会的工程原则

1. “工具可用”不等于“项目需要”。先找问题，再选工具。
2. “文档说能做”不等于“项目已经做成”。还要有代码、运行和用户路径证据。
3. 开发期工具、业务运行时和产品功能是三层，不要因为名字里都有 Agent 就混为一谈。
4. 人工审批会增加状态保存、权限、审计和恢复成本，只在风险值得时引入。
5. 配置成功只是一半，真实查询返回结果才算连通性验证。
