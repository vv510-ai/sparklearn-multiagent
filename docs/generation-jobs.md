# 持久生成任务

## 范围与入口

`GENERATION_JOBS_ENABLED=true` 时，`POST /api/chat`、`POST /api/resources/generate` 先保存请求再返回 SSE。`request_id` 在同一账户内唯一，相同编号和不同内容返回 409；重复相同请求返回原任务。清空对话、列资料等直接操作仍同步执行；题图 OCR 在入队前完成。独立英语场景接口、测评和研究接口不在这次持久队列范围内。

`GET /api/jobs?notebook_id=...` 返回本账户最近 20 项，`GET /api/jobs/{id}` 返回状态，`GET /api/jobs/{id}/events?after=...` 从游标继续。请求需要登录；其他账户读取返回 404。课程被撤回时不重放受影响内容。

## 存储与调度

- `generation_jobs`：请求、课程快照、阶段结果及其事件 outbox、状态。
- `generation_events`：可重放事件，按递增 ID 去重。恢复删除部分阶段事件，发 reset，再重放已完成阶段；SQLite 使用 AUTOINCREMENT，避免游标复用。
- `generation_effects`：模型调用状态/结果和外部任务编号。完成的文本与流式结果可复用；未确认提交不重新发送。
- `generation_tickets`：仅用户编号、执行租约、时间、状态的内部调度索引，不含 Prompt 或结果，不对外暴露。其余三张任务表加入 PostgreSQL RLS；后台领取 ticket 后先绑定用户再读任务。

PostgreSQL 用短事务 advisory lock；SQLite 测试用 BEGIN IMMEDIATE。网络调用不持锁。每次领取分配独立 token，租约 30 秒，每 5 秒续期，旧执行者不能再保存。每人最多 1 项执行，最多 3 项等待/执行，全局最多 100 项等待/执行；超过容量返回 429。代码默认执行 4 项，生产 Compose 设为 2 项。可通过 GENERATION_MAX_RUNNING / GENERATION_USER_PENDING / GENERATION_MAX_PENDING 调整，先实测容量。

## 恢复和失败

阶段结果和该阶段的事件在同一事务保存。恢复复用已完成阶段，保留错误状态；回答入库有幂等标记。图执行结束后才发最终 done。清空对话使相关未完成任务的租约失效，避免旧回答回写。

外部调用分三种：完成结果直接复用；小云雀已有任务编号继续查询/下载；没有确认编号或未保存完成的付费请求转 needs_review，不自动重复提交。临时查询/下载失败或者一轮查询未完成时，5 秒后重新排队，让其他用户有机会执行。供应商明确失败按失败结果展示。

单轮执行上限 900 秒，任务创建 1800 秒后再次领取会暂停（GENERATION_MAX_AGE_SECONDS）；不会无限自动重试。此总期限是领取时检查，当前一轮可能继续至本轮超时。需要人工核对的任务保留过程记录，不自动新建付费请求。“停止等待”只断开前端连接。

图片与语音分别使用线程池，避免 2 个慢生图任务占满语音线程。恢复操作不能撤回已发送给供应商的请求，也不承诺供应商级 exactly-once。

## 部署与运行

生产使用独立 `python -m app.job_worker` 容器，在后端健康后启动，避免并发建表。worker 与 backend 共享上传资料、生成文件、trace volume；worker 每次领取真实任务前增量刷新自身资料索引。worker 心跳健康检查纳入自动部署 --wait。当前 ECS 内存较小，因此生产执行上限设 2，worker 内存上限 900 MB；没有完成大规模压测，不能宣传支持某个在线人数。

开发/测试可用内嵌 worker：GENERATION_JOBS_ENABLED=true，GENERATION_WORKER_MODE=embedded。关闭开关保留旧的直接生成路径。回滚需同时停止/关闭新 worker；待处理任务仍在数据库中，恢复新版本后再处理，不能把回滚当成队列已清空。

每次运行日志写 `runs/run_<uuid>/`，request/state.summary 保存原 conversation/session ID 和用户。读取 debug API 使用 run_id；同一对话不再删除历史日志。Prompt 元信息保存实际 system+prompt 的 SHA-256。数据库和 trace volume 应纳入现有备份与磁盘容量管理；本次没有添加自动删除用户记录策略。

## 验收命令与口径

- 后端：`python -m pytest -q`，新增 `tests/test_generation_jobs.py` 覆盖并发领取、幂等、不同账户、断开、阶段 outbox、实际子进程 os._exit 后恢复、已知小云雀编号续查、查询/下载故障、让位/期限、清空对话、日志保留。
- 前端：`npm run build`。
- 浏览器：开启 GENERATION_JOBS_ENABLED=true 后运行 `generation-jobs.spec.ts`，检查高数、物理、英语的刷新找回和结果入口；普通 UI 进度测试 `generation-progress.spec.ts`。
- 生产：使用 scripts/acceptance.py 的 ReleaseLease 锁定当前提交，再以 PLAYWRIGHT_REAL_MODE=1 运行同一浏览器测试，检查小云雀图片在页面加载。接口/浏览器通过不等于文字与公式质量合格；质量结论单列。

单元测试的供应商响应是故障注入；只有生产浏览器验收调用真实供应商。进程重启验收在本地子进程执行，不为了测试中断线上用户。

## 本次本地验收记录

2026-09-25：完整后端回归 650 项通过；前端生产构建通过；浏览器 8 项主流程加 1 项双账户并发共 9 项通过。覆盖高数/物理/英语任务刷新取回、请求重发不新增任务、其他账户无法读取、结果入口、阶段进度、严格资料边界，以及已有英语三课播放和不可播放时的文字学习。生产 Compose 配置在目标 ECS 只读校验通过。

这些本地结果使用 Mock 文本/图片响应，不代表真实小云雀或图片质量验收；实际进程退出和状态恢复、浏览器播放及账户隔离使用真实本地进程/数据库/浏览器。生产实测记录放在本次维护的 `.tmp/jobs-live/production-*/report.json` 与同目录 browser 成品证据中，最终交付须核对该报告和线上 release。
