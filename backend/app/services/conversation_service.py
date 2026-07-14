"""学习对话持久化：让多轮追问与阶段性笔记不依赖进程内 checkpoint。"""
from __future__ import annotations

from ..models.db import session
from ..models.entities import ConversationMessage


def append_message(user_id: str, session_id: str, role: str, content: str) -> None:
    text = str(content or "").strip()
    if not text:
        return
    safe_role = role if role in {"user", "assistant"} else "assistant"
    with session() as s:
        s.add(ConversationMessage(
            user_id=user_id,
            session_id=session_id,
            role=safe_role,
            content=text[:20000],
        ))
        s.commit()


def get_session_messages(user_id: str, session_id: str, *, limit: int = 24) -> list[dict]:
    with session() as s:
        rows = (
            s.query(ConversationMessage)
            .filter(
                ConversationMessage.user_id == user_id,
                ConversationMessage.session_id == session_id,
            )
            .order_by(ConversationMessage.id.desc())
            .limit(max(1, min(limit, 80)))
            .all()
        )
    rows.reverse()
    return [{"role": row.role, "content": row.content} for row in rows]
