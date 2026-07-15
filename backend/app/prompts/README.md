# SparkLearn Prompt Skill

这里是 SparkLearn 唯一的运行时 Prompt 文案目录。Python 代码只负责按 `manifest.json` 的能力名读取文件、替换变量并调用模型。

## 维护方式

1. 软件级身份与通用底线只改 `system.md`，它不绑定课程，也不区分学生、老师或教研角色。
2. 某个功能的输出方式只改对应目录下的 `.md` 文件，例如：
   * 零基础讲解：`tutor/guided.md`
   * 完整笔记：`doc/complete-notes.md`
   * 对话转笔记：`doc/conversation-notes.md`
   * 巩固测验：`quiz/guided.md`
3. 多个功能共用的规则放在 `shared/`，模块模板通过 `{{source_rules}}` 等变量引用。
4. 模板变量统一写成 `{{variable_name}}`。加载器会拒绝缺少变量的调用，普通 JSON 花括号不受影响。
5. 修改现有 `.md` 文案后无需改 Python；运行时每次都会重新读取文件。新增全新能力时，才需要同时登记 `manifest.json` 并在调用方选择该能力名。

## 规则取舍

原始 `prompt.docx` 是一套混合规范，存在“不要生成新题”和“生成母题/练习题”等冲突。本目录按功能拆开：

* `doc/question-review.md` 只复盘已有题，不造新题。
* `quiz/*.md` 明确负责生成练习题。
* `doc/complete-notes.md` 可以附基础检查题。

威胁性措辞、成人化记忆法、强制暴露内部推理等内容不进入运行时。资料引用与来源边界优先于原文中“不要显示来源”的冲突要求。
