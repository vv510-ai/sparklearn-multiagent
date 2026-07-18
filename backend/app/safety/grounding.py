"""防幻觉第一层:答案-证据一致性校验(grounding check)。

用星火深度推理 X2 judge 答案中每个论断是否能在检索资料中找到出处,
输出 {grounded, unsupported[], verdict};不通过则 Doc/Tutor Agent 触发重写或加"待核实"标注。
"""
from __future__ import annotations

import logging

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt

log = logging.getLogger("sparklearn.grounding")

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
