"""Safe, source-grounded learning templates distilled from prompt.docx."""
from __future__ import annotations

from string import Formatter


_COMMON_RULES = """
通用约束：
1. 只能使用“参考资料”中的事实，不补充外部知识；资料不足时明确指出缺口。
2. 按知识逻辑重组，不照抄资料顺序；完整覆盖、合并重复内容，并保留独有的概念、例子、数据、公式和代码。
3. 先给结论再解释。概念说明“是什么、为什么、怎么用、与相邻概念的关系”。
4. 适合比较的内容使用 Markdown 表格；适合流程或层级的内容使用可渲染的 Mermaid。
5. 公式说明变量、适用条件和推导关键步；代码说明整体目标、模块职责、参数、返回值、数据流和边界条件。
6. 不添加外部链接。事实性表述用 [^n] 标注资料编号。
""".strip()


PROMPT_TEMPLATES: dict[str, str] = {
    "complete_notes": """
TASK=doc
请围绕“{topic}”制作一份适合复习的完整学习笔记。
用户目标：{goal}
学生画像：{persona}

建议结构：
# 标题
## 30 秒结论
## 知识框架
## 核心概念与关系
## 原理与关键步骤
## 公式或代码（资料中存在时）
## 例子与边界条件
## 易错点与易混对照
## 3 分钟回顾

{common_rules}

参考资料：
{context}
""".strip(),
    "one_page": """
TASK=doc
请把“{topic}”整理为一份真正可在一页内快速理解的复习页。
用户目标：{goal}
学生画像：{persona}

必须包含：直接结论、全局框架、学习路径、核心概念、运行机制、关键方法，
以及资料中实际出现的公式/代码、1—3 个例子、3—6 个易错点和一个记忆抓手。
内容过密时优先压缩措辞，不得通过删掉关键条件来变短。

{common_rules}

参考资料：
{context}
""".strip(),
    "error_confusion": """
TASK=doc
请围绕“{topic}”整理易错点与易混概念，不要生成新的练习题。
用户目标：{goal}
学生画像：{persona}

对每个易错点说明：错误表现、根本原因、正确做法、适用边界、反例或识别信号。
对每组易混概念使用表格比较定义、触发条件、关键差异、常见陷阱和记忆抓手。
最后给出一份考前快速复核清单。

{common_rules}

参考资料：
{context}
""".strip(),
}

DEFAULT_TEMPLATE = "complete_notes"


def supported_template(value: str) -> str:
    key = str(value or "").strip().lower()
    return key if key in PROMPT_TEMPLATES else DEFAULT_TEMPLATE


def render_learning_prompt(
    template_key: str,
    *,
    topic: str,
    goal: str,
    persona: str,
    context: str,
) -> str:
    """Render an allow-listed template; arbitrary user format strings are never executed."""
    key = supported_template(template_key)
    values = {
        "topic": topic,
        "goal": goal or f"系统学习{topic}",
        "persona": persona,
        "context": context or "（没有检索到可用资料）",
        "common_rules": _COMMON_RULES,
    }
    required = {name for _, name, _, _ in Formatter().parse(PROMPT_TEMPLATES[key]) if name}
    missing = required - values.keys()
    if missing:
        raise ValueError(f"prompt template is missing values: {sorted(missing)}")
    return PROMPT_TEMPLATES[key].format_map(values)
