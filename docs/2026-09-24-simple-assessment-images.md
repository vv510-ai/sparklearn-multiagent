# 简化测评与图片提问（2026-09-24）

本轮对应两项反馈：测评/计划首屏信息过多，聊天输入区缺少错题与知识点图片入口。

- 首屏先显示当前状态与一项可开始的任务。完整计划、作答复盘、学习资料和资料来源默认收起，保留原有评分、题量、导出与续答规则。
- 初步测评覆盖为 0 时显示“先学一步，再逐步了解你”，明确现有作答不足以判断掌握情况。
- 输入框旁新增“上传图片”，加号菜单也保留同一入口。支持单张 JPG/PNG/WebP、最大 4 MB，支持粘贴、缩略预览、移除，以及图片附带文字或单独发送。
- 图片经现有多模态网关识别，再进入当前账户/书本的聊天答疑。无效图片、超限、空识别或服务故障直接报错；发送失败保留当前图片和输入以便重试。
- 识别内容作为学习材料，与问题一起保存到当前会话，刷新后可继续追问。原始图片和未发送图片只保留在当前页面内存中；此入口不把原图长期存档为学习来源。需要归档的资料仍使用“添加学习资料”。
- 不新增模型服务、密钥、依赖或数据库字段。主代码：`frontend/components/assessment/AssessmentPanel.tsx`、`frontend/components/chat/Chat.tsx`、`backend/app/api/chat.py`。

验证入口：

```text
python -m pytest backend/tests -q
cd frontend
npm run build -- --webpack
npx playwright test e2e/simple-assessment-images.spec.ts e2e/assessment-scroll.spec.ts e2e/entry-assessment.spec.ts e2e/responsive-workspace.spec.ts
```

附加回归覆盖教材新题、重新打开详情、跨课程隔离和首次引导。离线图片链路使用演示识别/回答；它证明接口与界面流程，不证明真实 OCR 或回答准确性。真实验收需要在相同生产版本锁内上传原创题目图片，检查识别原文、讲解、追问和刷新后的会话内容。截图中的任意手写、复杂图形、遮挡文字不能由单张简单样例推断全部支持。
