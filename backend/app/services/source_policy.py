"""Keep retrieval scope separate from permission to supplement an explanation."""
from __future__ import annotations

import re

_STRICT = re.compile(
    r"(?:只|仅|严格)(?:能|可|允许|根据|依据|使用|用|按|基于|参考|围绕|限于){0,3}"
    r"[^。！？!?\n]{0,12}(?:资料|材料|课件|讲义|教材|原文|附件|(?:提供|上传|这份)的?内容|PDF|文档)|"
    r"(?:不要|不得|不允许|禁止|不能|不许)[^。！？!?\n]{0,8}(?:资料外|材料外|课外|外部|补充|扩展|扩写)",
    re.IGNORECASE,
)
_SUPPLEMENT = re.compile(
    r"(?:可以|允许|需要|请|帮我)[^。！？!?\n]{0,8}(?:补充|拓展|扩展)(?:知识|背景|解释|例子|内容)?|"
    r"(?:不必|不用|不要|无需)(?:只|仅|局限|限制)[^。！？!?\n]{0,12}(?:资料|材料|课件|原文)"
)


def _explicit_policy(message: str) -> str:
    # Only the learner's instruction can change the scope, never quoted material.
    text = re.split(r"\n\s*(?:参考资料|资料原文|附件内容|原文|题目|我的原稿|我的译文)\s*[:：]", str(message or ""), maxsplit=1)[0]
    text = re.sub(r"```[\s\S]*?```|[“「][^”」]*[”」]", "", text)
    # Discussing a policy is not an instruction to adopt it. Still inspect
    # separate clauses so an actual restriction after the question is honored.
    text = "，".join(clause for clause in re.split(r"[，,。！？!?；;\n]", text)
                    if not re.match(r"\s*(?:为什么|为何|什么叫)(?:只按|仅依|严格|资料范围)", clause))
    relaxed = re.search(r"(?:不必|不用|不要|无需)(?:只|仅|局限|限制)[^。！？!?\n]{0,12}(?:资料|材料|课件|原文)", text)
    strict_text = text[:relaxed.start()] + text[relaxed.end():] if relaxed else text
    supplement = _SUPPLEMENT.search(text)
    strict = _STRICT.search(strict_text)
    # A negative permission (不要补充) always remains strict. An explicit
    # "不用只按资料" is an affirmative relaxation, not a strict substring.
    if supplement and not strict:
        return "supplement"
    return "strict" if strict else ""


def resolve_source_policy(value: str, question: str, conversation: list[dict] | None = None) -> str:
    """Explicit current instructions, explicit UI choice, then user history."""
    explicit = _explicit_policy(question)
    if explicit:
        return explicit
    if value in {"strict", "supplement"}:
        return value
    for item in reversed(conversation or []):
        if item.get("role") == "user":
            explicit = _explicit_policy(str(item.get("content") or ""))
            if explicit:
                return explicit
    return "supplement"


def allows_supplement(state: dict) -> bool:
    # Older internal evidence-bound jobs do not opt into teaching supplements.
    return state.get("source_policy") == "supplement"
