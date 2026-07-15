"""画像构建智能体(Profile Agent)。

职责:通过多轮自然语言对话 + 学习行为日志,调用星火 Lite/Ultra 抽取并动态更新
≥6 维学习画像,写入数据库,支持"随学随新"(每次交互后增量更新)。
"""
from __future__ import annotations

import logging
import re

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt
from ..services.profile_service import get_profile, merge_profile, recent_events
from .emitter import agent_end, agent_start, emit

log = logging.getLogger("sparklearn.profile")

_STYLE_EVIDENCE = {
    "视觉型": ("看图", "图解", "画图", "可视化", "示意图"),
    "语言型": ("文字讲解", "文字说明", "读文字", "用文字"),
    "动手型": ("动手", "实操", "写代码", "敲代码", "边做边学"),
}
_GOAL_EVIDENCE = {
    "应试": ("考试", "备考", "考研", "期末", "刷题"),
    "竞赛": ("竞赛", "比赛", "算法赛", "软件杯"),
    "工程实践": ("项目", "工程", "开发", "实战", "工作"),
    "兴趣": ("兴趣", "好奇", "想了解"),
}
_DIFFICULTY_EVIDENCE = {
    "循序渐进": ("从零", "零基础", "循序渐进", "由浅入深", "一步一步", "慢一点"),
    "挑战式": ("挑战", "难一点", "进阶", "高难度"),
    "挑战型": ("挑战", "难一点", "进阶", "高难度"),
}
_ERROR_EVIDENCE_RE = re.compile(r"(?:总是|经常|容易|老是).{0,12}(?:错|混淆)|总把.{0,12}弄混")


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _gate_profile_patch(patch: dict, dialog: str, events: list[dict]) -> dict:
    """Only persist profile dimensions supported by explicit or behavioral evidence."""
    if not isinstance(patch, dict):
        return {}
    quiz_evidence = any(str(event.get("etype") or "") == "quiz_eval" for event in events)
    gated: dict = {}

    style = str(patch.get("cognitive_style") or "")
    if style in _STYLE_EVIDENCE and _contains_any(dialog, _STYLE_EVIDENCE[style]):
        gated["cognitive_style"] = style

    goal = str(patch.get("goal") or "")
    if goal in _GOAL_EVIDENCE and _contains_any(dialog, _GOAL_EVIDENCE[goal]):
        gated["goal"] = goal

    difficulty = str(patch.get("difficulty_pref") or "")
    if difficulty in _DIFFICULTY_EVIDENCE and _contains_any(dialog, _DIFFICULTY_EVIDENCE[difficulty]):
        gated["difficulty_pref"] = difficulty

    if quiz_evidence or _ERROR_EVIDENCE_RE.search(dialog):
        if patch.get("error_prone"):
            gated["error_prone"] = patch["error_prone"]
    if quiz_evidence and patch.get("metacognition") is not None:
        gated["metacognition"] = patch["metacognition"]

    if gated and patch.get("evidence"):
        gated["evidence"] = patch["evidence"]
    return gated

async def run(state: dict) -> dict:
    user_id = state.get("user_id", "demo_user")
    await agent_start("profile", "画像构建智能体", "对话+行为日志 → 增量更新 ≥6 维画像(星火 Lite)")

    if state.get("intent") == "generate":
        profile = get_profile(user_id)
        await emit({"type": "profile", "profile": profile})
        dims = [k for k in ("knowledge_mastery", "cognitive_style", "error_prone", "goal",
                            "pace", "difficulty_pref", "resource_pref", "metacognition")
                if k in profile]
        await agent_end("profile",
                        f"画像 v{profile.get('_version')}:{len(dims)} 维在线,生成资源仅读取画像",
                        {"version": profile.get("_version")})
        return {"student_profile": profile}

    dialog = "\n".join(f"{m.get('role')}: {m.get('content','')}"
                       for m in (state.get("messages") or [])[-6:]) or "(无新对话)"
    events = recent_events(user_id, limit=12)
    ev_text = "\n".join(f"- {e['etype']}: {e['payload']}" for e in events) or "(暂无行为日志)"

    patch: dict = {}
    try:
        prompt_call = invoke_learning_prompt("profile.update", dialog=dialog, events=ev_text)
        raw = await llm_complete(
            prompt_call.prompt,
            system=prompt_call.system,
            role="lite",
            temperature=0.2,
            json_mode=True,
        )
        patch = parse_json(raw)
        if not isinstance(patch, dict):
            patch = {}
        for managed_field in ("knowledge_mastery", "pace", "resource_pref"):
            patch.pop(managed_field, None)
        patch = _gate_profile_patch(patch, dialog, events)
    except Exception as e:  # noqa: BLE001
        log.warning("画像抽取失败,保持现状:%s", e)

    profile = merge_profile(user_id, patch) if patch else get_profile(user_id)
    await emit({"type": "profile", "profile": profile})
    dims = [k for k in ("knowledge_mastery", "cognitive_style", "error_prone", "goal",
                        "pace", "difficulty_pref", "resource_pref", "metacognition")
            if k in profile]
    changed = [k for k in patch.keys() if not k.startswith("_")]
    await agent_end("profile",
                    f"画像 v{profile.get('_version')}:{len(dims)} 维在线"
                    + (f",本轮更新 {', '.join(changed[:4])}" if changed else ",本轮无新证据"),
                    {"version": profile.get("_version")})
    return {"student_profile": profile}
