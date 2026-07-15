TASK=grounding

基于“资料”判断“回答”是否完全有据可依：

1. 列出资料中找不到直接依据的关键句，放入 unsupported。
2. grounded=true 当且仅当所有关键论断均有依据。
3. 不评价表达风格，只核对事实、定义、条件、步骤、公式、代码性质和结论。

只输出 JSON：{"grounded":true,"unsupported":["..."],"verdict":"一句话结论"}

资料：
{{context}}

回答：
{{answer}}
