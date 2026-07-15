TASK=quiz
MODE=standard

请围绕知识点“{{kp}}”恰好生成 8 道由浅入深的习题，难度档={{difficulty}}（1 易—5 难）。

题型至少包含 3 道 single（单选，4 个选项）、1 道 fill、1 道 judge、1 道 complexity、1 道 design，剩余 1 道自选。先检验理解，再检验应用和边界。

所有题干、选项、答案和解析只能依据参考资料。single 以及带选项的 complexity 的 answer 只填 A/B/C/D。每题解析先说明正确理由，再指出易错原因或适用边界，最后给一句简短生活化提示；不要用解析引入资料外的新概念。

只输出 JSON，不要 Markdown 前后缀：

{"questions":[{"type":"single","stem":"...","options":["A...","B...","C...","D..."],"answer":"A","explain":"...","kp":"{{kpid}}","difficulty":{{difficulty}},"error_tags":["边界条件"]}]}

{{source_rules}}

{{beginner_rules}}

参考资料：
{{context}}
