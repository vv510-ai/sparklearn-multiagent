"""Small, explainable routing policy; never classifies system text as user intent.

Task capabilities already come from the intent/resource workflow. Conversation
answers additionally use the actual question and retrieved material size. This
does not add a second model request or silently retry a failed answer.
"""
from __future__ import annotations

import re


def deep_task_reason(task: dict | None) -> str:
    task = task or {}
    question = str(task.get("question") or "").strip()
    # A source excerpt is data, not an instruction to change provider.
    instruction = re.split(r"\n\s*(?:资料|原文|附件|教材|我的原稿)\s*[:：]", question, maxsplit=1)[0]
    clauses = re.split(r"[。！？!?；;，,\n]", instruction)
    active = " ".join(c for c in clauses if not re.search(r"不要|无需|不用|不需要|不必", c))
    if task.get("semantic_depth") == "deep":
        return "意图理解判定需要深入分析"
    if re.search(r"(?:严谨|严格|完整|逐步|详细).{0,12}(?:证明|推导|论证)|(?:证明|推导).{0,24}(?:定理|公式|复杂度|收敛)|(?:用|运用)(?:数学归纳法|反证法)", active):
        return "严谨推导或多步论证"
    if re.search(r"(?:综合|整合|对照|比较|交叉|对比).{0,24}(?:资料|论文|文献|证据|教材|文章)|(?:研究报告|文献综述|系统分析|教学设计)", active):
        return "资料综合或研究分析"
    if len(question) >= 2400:
        return "长材料理解"
    material_chars = max(0, int(task.get("material_chars") or 0))
    if material_chars >= 12000:
        return "长篇参考材料"
    if int(task.get("source_count") or 0) >= 2 and re.search(r"综合|异同|矛盾|共同点|对照|对比|比较|总结", active):
        return "多来源对照"
    return ""
