"""编排智能体(Orchestrator/Supervisor):星火 X2 意图识别 + 任务规划,
决定调用哪些下游智能体、串行还是并行;路由结果写入 state.intent 供条件边分发。"""
from __future__ import annotations

import logging

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt
from .emitter import agent_end, agent_start

log = logging.getLogger("sparklearn.orchestrator")

_VALID = {"learn", "summary", "generate", "tutor", "eval", "chat"}
_LEARN_HINTS = ("我想学", "想学习", "从零", "零基础", "入门", "教我", "带我学", "开始学")
_SUMMARY_HINTS = (
    "总结本次", "整理本次", "对话笔记", "整理成笔记", "总结成笔记", "保存成笔记",
    "学习对话整理", "整理成一份", "个人笔记", "可复习、可继续使用",
)
_GENERATE_HINTS = ("规划", "计划", "学习路径", "复习路径", "复习计划", "学习资源", "生成资源", "全套学习")
_TUTOR_HINTS = ("是什么", "为什么", "怎么", "如何", "讲讲", "解释", "区别", "举例", "代码", "算法", "？", "?")
_EVAL_HINTS = ("测试", "测一测", "考考我", "出题", "练习题", "做题", "评估")


async def run(state: dict) -> dict:
    await agent_start("orchestrator", "编排智能体", "意图识别与任务分发(星火 X2)")
    msg = (state.get("messages") or [{}])[-1].get("content", "") or state.get("learning_goal", "")
    intent = state.get("intent") or ""
    reason = "调用方显式指定"
    if intent not in _VALID:
        if any(k in msg for k in _SUMMARY_HINTS):
            intent, reason = "summary", "命中学习对话总结关键词"
        elif any(k in msg for k in _LEARN_HINTS):
            intent, reason = "learn", "命中零基础/开始学习关键词"
        elif any(k in msg for k in _GENERATE_HINTS):
            intent, reason = "generate", "命中学习规划/资源生成关键词"
        elif any(k in msg for k in _EVAL_HINTS):
            intent, reason = "eval", "命中测试/做题关键词"
        elif any(k in msg for k in _TUTOR_HINTS):
            intent, reason = "tutor", "命中答疑关键词"
        else:
            try:
                prompt_call = invoke_learning_prompt(
                    "orchestrator.intent",
                    message=msg,
                    goal=state.get("learning_goal", "") or "（无）",
                )
                raw = await llm_complete(
                    prompt_call.prompt,
                    system=prompt_call.system,
                    role="reasoner",
                    temperature=0,
                    json_mode=True,
                )
                data = parse_json(raw)
                intent = str(data.get("intent", "chat"))
                reason = str(data.get("reason", ""))
            except Exception as e:  # noqa: BLE001
                log.warning("意图识别失败,回退 chat:%s", e)
                intent, reason = "chat", f"识别异常回退:{e}"
        if intent not in _VALID:
            intent = "chat"
    plan_hint = {"learn": "由浅入深讲解 → 小图 → 基础练习 → 后续追问",
                 "summary": "完整对话 → 可复用个人学习笔记",
                 "generate": "并行 fan-out:Doc/Mindmap/Quiz/Media → Eval 质检汇总",
                 "tutor": "Tutor Agent 多模态答疑", "eval": "Eval Agent 学习效果评估",
                 "chat": "轻量对话"}[intent]
    await agent_end("orchestrator", f"意图={intent}({reason})→ {plan_hint}",
                    {"intent": intent})
    return {"intent": intent}


def route_task(state: dict) -> str:
    """LangGraph 条件边函数:按 intent 分发。chat 并入 tutor 轻量直答。"""
    intent = state.get("intent", "chat")
    return {
        "learn": "learn",
        "summary": "summary",
        "generate": "generate",
        "tutor": "tutor",
        "eval": "eval",
        "chat": "tutor",
    }[intent]
