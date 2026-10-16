TASK=quiz
MODE=remediation-transfer

请围绕知识点“{{kp}}”恰好生成 {{target_questions}} 道无提示迁移复测题，难度档={{difficulty}}（1 易—5 难）。

这不是原题重做。请保持考查概念与资料边界不变，但必须更换题面、例子、数值或提问角度，用新情境检验学习者能否独立迁移。针对诊断误区“{{misconception}}”设置至少一道辨析题，但不要在题干中提示误区或正确答案。

禁止复用、近似改写或引用以下原题题干：
{{forbidden_stems}}

题型优先包含 single、judge、fill；若资料不适合，可使用 complexity 或 design。所有题干、选项、答案和解析只能依据参考资料。single 以及带选项的 complexity 的 answer 只填 A/B/C/D。解析只在提交后展示，先说明正确理由，再指出易错边界。

题干、选项、答案和解析均不得出现源码、伪代码、函数定义或程序语句；算法题改用对象、操作次数、状态变化和输入输出关系描述。

出题质量：
- 单选的每个错误选项都对应一种学习者真实会犯的错误思路（概念混淆、条件遗漏、方向弄反、以偏概全），长度和语气与正确项相当；不用“以上都对/都不对”和一眼可排除的选项。
- 输出前逐题自检：题干条件足以唯一确定答案；单选恰有一个正确项；判断题不含“可能/一般”等使对错含糊的词；解析与答案一致。

只输出 JSON，不要 Markdown 前后缀：

{"questions":[{"type":"single","stem":"...","options":["A...","B...","C...","D..."],"answer":"A","explain":"...","kp":"{{kpid}}","difficulty":{{difficulty}},"error_tags":["迁移边界"]}]}

{{source_rules}}

{{beginner_rules}}

参考资料：
{{context}}
