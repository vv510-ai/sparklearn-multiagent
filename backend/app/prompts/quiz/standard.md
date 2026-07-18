TASK=quiz
MODE=standard

请围绕知识点“{{kp}}”恰好生成 8 道由浅入深的习题，难度档={{difficulty}}（1 易—5 难）。

题型至少包含 3 道 single（单选，4 个选项）、1 道 fill、1 道 judge、1 道 complexity、1 道 design，剩余 1 道自选。先检验理解，再检验应用和边界。

所有题干、选项、答案和解析只能依据参考资料。single 以及带选项的 complexity 的 answer 只填 A/B/C/D。每题解析先说明正确理由，再指出易错原因或适用边界，最后给一句简短生活化提示；不要用解析引入资料外的新概念。
题干必须是独立、清楚的一道题，不得把整段教材、题库原文、多个小题、选项列表、答案或解析复制进题干。资料中若已带“答案/解析”，只提炼知识点后重新命题，绝不能让答案在提交前泄露。题干不超过 120 个汉字。

只输出 JSON，不要 Markdown 前后缀：

{"questions":[{"type":"single","stem":"...","options":["A...","B...","C...","D..."],"answer":"A","explain":"...","kp":"{{kpid}}","difficulty":{{difficulty}},"error_tags":["边界条件"]}]}

{{source_rules}}

{{beginner_rules}}

参考资料：
{{context}}
