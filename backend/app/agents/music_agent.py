"""Memory-song agent: turns the current topic into a mnemonic song (kind ``song``)."""
from __future__ import annotations

import uuid

from ..rag.citation import build_context
from ..rag.retriever import retrieve
from ..services import memory_song
from ..services.knowledge_graph import resolve_topic
from .doc_agent import _conversation_text, _persona
from .emitter import agent_end, agent_start, emit


async def run(state: dict) -> dict:
    if "song" not in (state.get("kinds") or []):
        return {}
    kp, name, _custom = resolve_topic(state.get("knowledge_points"), state.get("learning_goal"), state.get("topic_label"))
    scope = state.get("one_page_scope") or {}
    if scope.get("topic") and not scope.get("missing"):
        kp, name = scope.get("kp") or kp, scope["topic"]
    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    profile = state.get("student_profile") or {}
    await agent_start("music", "记忆歌曲智能体", "要点 → 口诀 → 曲风决策 → 歌词核对 → AI 演唱")
    chunks = retrieve(f"{state.get('learning_goal') or ''}\n当前主题：{name}", final_k=6, source_ids=source_ids,
                      kp=None, user_id=state.get("user_id", "demo_user")) if source_ids else []
    context, citations = build_context(chunks)
    conversation = _conversation_text(state, limit=4000)
    material = "\n\n".join(part for part in (
        f"所选资料：\n{context}" if context else "",
        f"最近学习对话（用于确定重点，不能当作事实来源）：\n{conversation}" if conversation else "",
    ) if part)
    song = await memory_song.generate(name, goal=str(state.get("learning_goal") or ""), persona=_persona(profile),
                                      context=material, job_key=str(state.get("job_id") or state.get("run_id") or uuid.uuid4().hex))
    status = song.get("status")
    flags = [] if status == "ready" else [{"agent": "music", "kind": "song", "type": "song_degraded",
                                           "detail": song.get("error", "音乐未生成")}]
    resource = {
        "id": uuid.uuid4().hex[:12],
        "kind": "song",
        "kp": kp,
        "title": f"{name}·记忆歌曲",
        "payload": {
            "song": song,
            "template": "memory_song",
            "topic_label": name,
            "source_ids": source_ids,
            "generation_mode": "unavailable" if status in {"failed", "blocked"} else "model",
            "source_evidence": citations if chunks else [],
        },
        "citations": [item["citation"] for item in citations] if chunks else [],
    }
    await emit({"type": "resource", "resource": resource})
    summary = {"ready": f"已生成「{song.get('title', name)}」（{(song.get('plan') or {}).get('genre', '')}）",
               "lyrics_only": "已生成口诀与歌词，音乐未生成"}.get(status, "记忆歌曲未生成")
    await agent_end("music", summary, {"status": status})
    return {"generated_resources": {resource["id"]: resource}, "safety_flags": flags}
