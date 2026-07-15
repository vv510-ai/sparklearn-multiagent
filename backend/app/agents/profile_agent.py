"""画像构建智能体(Profile Agent)。

职责:通过多轮自然语言对话 + 学习行为日志,调用星火 Lite/Ultra 抽取并动态更新
≥6 维学习画像,写入数据库,支持"随学随新"(每次交互后增量更新)。
"""
from __future__ import annotations

import logging

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt
from ..services.profile_service import get_profile, merge_profile, recent_events
from .emitter import agent_end, agent_start, emit

log = logging.getLogger("sparklearn.profile")

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
