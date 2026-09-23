# 反馈 02：能对话，但“一图看懂”误报资料不足

## 本次问题与修复范围

反馈原句为“选词有没有记忆点”，课程为大学英语六级，未上传个人资料。修复前在生产版本 `ced33a7512ef7ba9a59fba572ace4917bbf8f989` 创建独立验收账号，实际完成课程准备、发送该原句、点击“一图看懂”：聊天正常回答，生成接口却返回 `generation_mode=unavailable`，并把错误文字包装为资料摘录图。对应浏览器回归在 `not.toBe("unavailable")` 处失败。

本次处理这条生成链路及失败反馈；其他反馈项继续逐项处理。

## 从现象找到原因

1. 六级当前课程确实有相关资料，原文包含“不要只凭一个熟悉的中文释义选词”。“绑定 0 份上传资料”不等于没有内置课程资料。
2. `topic_scope.topic_terms()` 未识别“有没有”问法，把整句当作需要出现在资料里的主题词；向量检索后的相关片段被字面过滤丢弃。
3. 接口和文档智能体已经传递当前主题的对话，但 `doc/one-page.md` 未使用 conversation 变量，模型看不到刚才的讲解。
4. 没有资料时仍调用 `_one_page_visual()`，错误说明因此变成图中节点；评估节点只要收到资源就宣称完成。

修复分别对应以上证据：提取“有没有”前的主题；把当前主题对话传入提示词，同时保留事实来自参考资料的限制；没有证据时不构造图；区分资料不足、图片失败、部分成功和成功。前端也根据已有 generation_mode 隐藏无效图和成功式介绍，兼容之前保存的失败资源。

这没有放宽上传资料、课程或用户的检索范围，没有把聊天记录当成经过核验的新事实，也没有更换模型提供方。

## 可复现的验证

后端回归文件：`backend/tests/test_one_page_feedback.py`。

- 修复前 5 项断言失败：自然问题过滤、缺失对话、六级生成被阻止、错误被画成图、图片失败仍报成功。
- 修复后新增 6 项回归通过，包括部分图片失败状态；相关旧测试及提示词测试通过。
- 使用新的独立 SQLite 数据库执行全部后端测试：397 passed。首次使用本机旧数据库时有 7 项模型配置测试因缺少 model_preferences.revision 字段失败；未修改该数据库或为此改变业务逻辑。
- 前端生产构建通过，包括 TypeScript。首次构建指出原有 generation_mode 字段未在前端类型中声明，已补齐类型。
- 本地浏览器两种场景全部通过（2 passed，23.4 秒）。

在 backend 目录运行（为 DATABASE_URL 指定一个新的、本地测试用数据库路径）：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:DATABASE_URL='sqlite:///D:/Desktop/知行循证LearnLoop/LearnLoop-multiagent/.tmp/feedback-02/pytest-recheck.db'
.venv/Scripts/python.exe -m pytest tests -q
```

在 frontend 目录运行：

```powershell
npm run build
$env:PLAYWRIGHT_PRODUCTION='true'
npm run test:e2e -- e2e/one-page-feedback.spec.ts --reporter=list
```

浏览器测试创建独立账号，真实操作课程准备、聊天、点击工坊按钮，读取真实生成接口。离线版使用 demo 模型，并在问题末尾加问号以命中离线答疑路由；它只能证明链路和证据传递，不证明真实生图能力。生产版使用原句，不拦截或伪造聊天/生成响应，还检查实际图片的加载尺寸：

```powershell
$env:PLAYWRIGHT_BASE_URL='https://47.121.24.54'
npm run test:e2e -- e2e/one-page-feedback.spec.ts --reporter=list
```

另一个场景在六级课程中询问“量子纠缠有没有记忆点”，必须明确未生成、无知识图节点、无成功式介绍。图片服务失败及多页部分失败由可控单元测试覆盖；未主动关闭生产图片服务。

本机证据保存在 `.tmp/feedback-02/`：before 为修复前，local 为本地浏览器结果，production 为部署后实际结果。生产完成状态以该目录实际结果和本轮最终报告为准，不能以构建成功代替上线成功。

## 你可以这样复核

1. 刷新生产网站，选择大学英语六级，提问“选词有没有记忆点”。
2. 等回答完成，点击工坊“一图看懂”，检查能否看到实际图片。
3. 展开“查看文字版与出处”，确认内容谈选词、引用六级指南。
4. 在同一课程询问课程资料没有的主题，再点“一图看懂”：应明确提示未生成，而不是将错误文字排成图。

回滚使用本次提交的 `git revert`，再按仓库要求测试、推送、部署和验收。
