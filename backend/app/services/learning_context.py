"""Small, attributable context that is already known by the application."""
from __future__ import annotations

import re

from .learning_scope import current_space


def supplemental_context(question: str) -> list[dict]:
    """Never fetch another tenant's sources or pretend to have searched the web."""
    chunks = []
    space = current_space()
    course = (space or {}).get("course") or {}
    reference = course.get("exam_reference") or {}
    if reference and re.search(r"考点|考什么|考试|占分|占比|分值|题型|考纲|六级.*框架", question):
        rows = [f"{part['name']}：分值比例 {part['weight']}%，考试时间 {part['minutes']} 分钟。"
                for part in reference.get("parts", [])]
        text = f"{course.get('title', '')}考试结构记录（核验日期 {reference.get('checked_on', '未记录')}）：\n" + "\n".join(rows)
        text += "\n以上比例描述试卷结构，不能直接当作单题报道分数或提分保证。报名与考试日期需要另行核验。"
        chunks.append({"text": text, "source": "中国教育考试网 · 考试结构记录",
                       "source_id": "course-exam-reference", "source_type": "exam_reference",
                       "url": reference.get("url", ""), "chapter": "试卷结构",
                       "citation": f"中国教育考试网 · 试卷结构（记录核验日期 {reference.get('checked_on', '未记录')}） {reference.get('url', '')}"})
    if re.search(r"(?:网站|平台|小知|LearnLoop|learnloop|你们)[^。！？!?]{0,24}(?:能|功能|帮助|提供|学习方法|怎么用)", question):
        chunks.append({
            "text": "LearnLoop 当前提供：上传并选择自己的学习资料、围绕资料对话答疑、整理笔记与一图看懂、知识框架、练习与作答反馈、根据实际作答安排补救和复测、查找外部网课。生成与媒体功能受模型或服务可用性影响。六级内置内容为原创起点指南和基础训练，并非完整历年真题库；不承诺考试提分。用户尚未作答时不能声称已诊断出其短板。",
            "source": "LearnLoop 产品功能说明", "source_id": "learnloop-capabilities",
            "source_type": "product", "chapter": "当前学习功能",
            "citation": "LearnLoop · 当前学习功能说明（应用内记录）",
        })
    return chunks
