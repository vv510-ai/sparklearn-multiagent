"""防幻觉第一层:答案-证据一致性校验(grounding check)。

用星火深度推理 X2 judge 答案中每个论断是否能在检索资料中找到出处,
输出 {grounded, unsupported[], verdict};不通过则 Doc/Tutor Agent 触发重写或加"待核实"标注。
"""
from __future__ import annotations

import logging
import re

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt

log = logging.getLogger("sparklearn.grounding")


def grounding_check_local(
    answer: str,
    contexts: list[str],
    *,
    question: str = "",
    allow_supplement: bool = False,
) -> dict:
    """Fast, deterministic guard for the live tutor stream.

    It validates citation bounds and catches a common definition mismatch
    without adding a second provider request after every answer. The remote
    judge remains available for offline audits and document generation.
    """
    text = str(answer or "").strip()
    if not text:
        return {"grounded": False, "unsupported": ["空回答"], "verdict": "回答为空"}
    usable_contexts = [str(item or "").strip() for item in contexts if str(item or "").strip()]
    citations = [int(value) for value in re.findall(r"\[\^(\d+)\]", text)]
    invalid = [value for value in citations if value < 1 or value > len(usable_contexts)]
    if invalid:
        return {
            "grounded": False,
            "unsupported": [f"无效引用 [^{value}]" for value in invalid[:5]],
            "verdict": "引用编号超出当前资料范围",
        }
    if allow_supplement:
        return {"grounded": False, "accepted": True, "verification": "citation_only",
                "unsupported": [], "verdict": "仅完成引用编号检查；通用补充未逐项核实"}
    if not usable_contexts:
        return {"grounded": True, "unsupported": [], "verdict": "通用知识回答，无资料引用声明"}

    compact_question = re.sub(r"\s+", "", str(question or ""))
    subject_match = re.search(
        r"(?:什么是([\u4e00-\u9fffA-Za-z0-9]{1,12})|"
        r"([\u4e00-\u9fffA-Za-z0-9]{1,12})是什么)",
        compact_question,
    )
    subject = next((value for value in (subject_match.groups() if subject_match else ()) if value), "")
    if subject and subject not in text:
        return {
            "grounded": False,
            "unsupported": [f"没有回答“{subject}”的定义"],
            "verdict": "回答对象与当前定义问题不一致",
        }

    if citations:
        return {"grounded": True, "unsupported": [], "verdict": "本地引用边界校验通过"}

    # Short explanations sometimes omit a citation marker. Require a modest
    # lexical overlap with the selected material instead of inventing a
    # citation or failing closed because a remote judge is unavailable.
    def han_bigrams(value: str) -> set[str]:
        han = "".join(re.findall(r"[\u4e00-\u9fff]", value))
        return {han[index:index + 2] for index in range(max(0, len(han) - 1))}

    overlap = han_bigrams(text).intersection(han_bigrams(" ".join(usable_contexts)))
    if len(overlap) >= 2:
        return {"grounded": True, "unsupported": [], "verdict": "本地资料关键词校验通过"}
    return {
        "grounded": False,
        "unsupported": ["未找到资料关键词或有效引用"],
        "verdict": "回答与当前资料缺少可核对联系",
    }


async def grounding_check(answer: str, contexts: list[str]) -> dict:
    ctx = "\n---\n".join(contexts) if contexts else "(无)"
    try:
        prompt_call = invoke_learning_prompt(
            "safety.grounding", context=ctx, answer=answer,
        )
        raw = await llm_complete(
            prompt_call.prompt,
            system=prompt_call.system,
            role="reasoner",
            temperature=0,
            json_mode=True,
            # The judge only returns a tiny JSON object.  Keeping this below
            # the DeepSeek thinking threshold makes it a fast verification
            # call instead of a second long reasoning pass after every answer.
            max_tokens=600,
            allow_mock_fallback=False,
        )
        data = parse_json(raw)
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        if not isinstance(data, dict):
            data = {}

        grounded = data.get("grounded", False)
        if isinstance(grounded, str):
            grounded = grounded.lower() in {"1", "true", "yes", "on"}

        unsupported = data.get("unsupported", [])
        if isinstance(unsupported, str):
            unsupported = [unsupported]
        if not isinstance(unsupported, list):
            unsupported = []

        return {"grounded": bool(grounded),
                "unsupported": unsupported[:5],
                "verdict": str(data.get("verdict", ""))}
    except Exception as e:  # noqa: BLE001
        log.warning("grounding 校验失败:%s", e)
        return {"grounded": False, "unsupported": [], "verdict": f"校验服务异常:{e}"}
