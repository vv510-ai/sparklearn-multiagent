TASK=research_plan

为学习问题“{{question}}”制定一个小而深入的资料检索计划。
只输出 JSON：{"questions":["需要弄懂的子问题","关键机制","适用边界或反例"],"queries":["英文核心概念","英文机制与应用","英文 limitations 或 comparison"]}。
最多三个不同角度的查询，每条不超过120字符，面向百科与学术资料检索。查询不包含个人信息，不包含凭据。
