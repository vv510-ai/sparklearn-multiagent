"""编排智能体(Orchestrator/Supervisor)：先用确定性规则识别意图并路由；
仅在规则未命中时调用统一文本主脑的 reasoner 路径，结果写入 state.intent 供条件边分发。
文本主脑由部署配置决定；DeepSeek 路径不可用且配置星火时，reasoner 降级到讯飞星火 X2。"""
from __future__ import annotations

import logging
import re

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt
from .emitter import agent_end, agent_start

log = logging.getLogger("sparklearn.orchestrator")

_VALID = {"learn", "summary", "generate", "tutor", "eval", "chat"}
_LEARN_HINTS = ("我想学", "想学习", "从零", "零基础", "入门", "教我", "带我学", "开始学")
_STRATEGY_HINTS = ("怎么学", "如何学", "从哪学", "学习顺序", "学习路线", "学习路径", "学习计划", "复习计划", "规划")
_SUMMARY_HINTS = (
    "总结本次", "整理本次", "对话笔记", "整理成笔记", "总结成笔记", "保存成笔记",
    "学习对话整理", "整理成一份", "个人笔记", "可复习、可继续使用",
)
_TUTOR_HINTS = ("是什么", "为什么", "怎么", "如何", "讲讲", "解释", "区别", "举例", "代码", "算法", "？", "?")
_EVAL_HINTS = ("评估", "学习报告", "掌握情况", "错因")
_RESOURCE_KIND_HINTS = {
    "doc": ("学习笔记", "整理笔记", "一图看懂", "一页看懂", "讲解文档"),
    "mindmap": ("思维导图", "知识导图", "框架导图", "脑图", "导图"),
    "quiz": ("出题", "练习题", "题目", "测验", "测一测", "考考我", "做题"),
    "video": ("讲解视频", "视频脚本", "视频", "讲稿"),
    "ppt": ("复习ppt", "学习ppt", "生成ppt", "制作ppt", "复习课件", "演示文稿"),
}
_ALL_RESOURCE_HINTS = ("全套学习", "全部资源", "所有资源", "整套资源")
_CHAT_RE = re.compile(
    r"^(?:你好|您好|嗨|哈喽|hello|hi|hey|在吗|谢谢|感谢|再见|拜拜)[!！?？。,.，]*$",
    re.IGNORECASE,
)
_CHAT_HELP_HINTS = ("你能做什么", "可以做什么", "怎么用", "如何使用", "使用说明", "help")


def _is_lightweight_chat(message: str) -> bool:
    compact = re.sub(r"\s+", "", str(message or "")).strip().lower()
    return bool(
        not compact
        or _CHAT_RE.fullmatch(compact)
        or (len(compact) <= 24 and any(hint in compact for hint in _CHAT_HELP_HINTS))
    )


def requested_resource_kinds(message: str) -> list[str]:
    """只把用户明确点名的产物交给生成链路，避免模型擅自扩展成全套资源。"""
    if _is_draft_feedback(message):
        return []
    compact = re.sub(r"\s+", "", str(message or "")).lower()

    def affirmed(hint: str) -> bool:
        if hint not in compact:
            return False
        negated = re.search(
            rf"(?:不需要|不要|不用|无需|别(?:再)?(?:生成|给|做)?|不想要|不是要)[^。！？!?，,；;]{{0,16}}{re.escape(hint)}",
            compact,
        )
        return negated is None

    if any(affirmed(hint) for hint in _ALL_RESOURCE_HINTS):
        return ["doc", "mindmap", "quiz", "video"]
    return [
        kind
        for kind, hints in _RESOURCE_KIND_HINTS.items()
        if any(affirmed(hint) for hint in hints)
    ]


def _is_draft_feedback(message: str) -> bool:
    """An attached writing task is context for feedback, not a request for a quiz."""
    text = str(message or "")
    instruction = re.split(r"\n\s*(?:题目|我的原稿|我的译文|我的作文|原稿|译文)\s*[:：]", text, maxsplit=1)[0][:240]
    return bool(re.search(r"(?:批改|点评|反馈|检查|修改)[^\n。]{0,24}(?:作文|写作|译文|翻译|原稿)", instruction)
                and re.search(r"(?:我的原稿|我的译文|我的作文|原稿|译文|作文)\s*[:：]\s*\S", text))


async def run(state: dict) -> dict:
    await agent_start("orchestrator", "编排智能体", "规则优先意图识别；未命中时由统一文本主脑的 reasoner 路径兜底")
    msg = (state.get("messages") or [{}])[-1].get("content", "") or state.get("learning_goal", "")
    intent = state.get("intent") or ""
    caller_selected_kinds = [str(kind) for kind in (state.get("kinds") or []) if str(kind).strip()]
    caller_fixed_intent = intent in _VALID
    requested_kinds = requested_resource_kinds(msg)
    reason = "调用方显式指定"
    if intent not in _VALID:
        if _is_lightweight_chat(msg):
            intent, reason = "chat", "命中轻量对话规则"
        elif _is_draft_feedback(msg):
            intent, reason = "tutor", "学习者提交原稿请求反馈，题目与原稿作为答疑上下文"
        elif any(k in msg for k in _SUMMARY_HINTS):
            intent, reason = "summary", "命中学习对话总结关键词"
        elif requested_kinds:
            intent, reason = "generate", f"用户明确点名产物：{'、'.join(requested_kinds)}"
        elif any(k in msg for k in _STRATEGY_HINTS):
            intent, reason = "learn", "用户询问学习方法或路线，采用最小充分回答"
        elif any(k in msg for k in _LEARN_HINTS):
            intent, reason = "learn", "命中零基础/开始学习关键词"
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
        if intent == "generate" and not requested_kinds:
            intent = "learn"
            reason = "未明确点名资源类型，改为先回答当前学习需求"
    selected_kinds = caller_selected_kinds if caller_fixed_intent and intent == "generate" else requested_kinds
    plan_hint = {"learn": "判断是路线还是概念 → 只回答当前需求 → 产物按需生成",
                 "summary": "完整对话 → 可复用个人学习笔记",
                 "generate": f"仅生成用户点名的资源：{'、'.join(selected_kinds)}",
                 "tutor": "Tutor Agent 多模态答疑", "eval": "Eval Agent 学习效果评估",
                 "chat": "轻量对话"}[intent]
    await agent_end("orchestrator", f"意图={intent}({reason})→ {plan_hint}",
                    {"intent": intent, "kinds": selected_kinds})
    output = {"intent": intent, "artifact_policy": "on_demand"}
    if selected_kinds:
        output["kinds"] = selected_kinds
    return output


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
