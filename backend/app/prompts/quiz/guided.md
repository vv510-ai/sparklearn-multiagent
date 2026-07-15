TASK=quiz
MODE=guided

请围绕知识点“{{kp}}”恰好生成 5 道零基础巩固题，难度强制控制在 1—2。

题型必须包含 2 道 single（单选，4 个选项）、1 道 judge（判断）、1 道 fill（填空）、1 道 design（一句话问答）。按“定义 → 最小例子 → 一个易错边界”排列，不要突然加入进阶概念。

所有题干、选项、答案和解析只能依据参考资料。single 的 answer 只填 A/B/C/D。每题解析先说明正确理由，再指出易错原因或适用边界，最后给一句简短生活化提示；不要用解析引入资料外的新概念。

只输出 JSON，不要 Markdown 前后缀：

{"questions":[{"type":"single","stem":"...","options":["A...","B...","C...","D..."],"answer":"A","explain":"...","kp":"{{kpid}}","difficulty":1,"error_tags":["概念边界"]}]}

{{source_rules}}

{{beginner_rules}}

参考资料：
{{context}}
