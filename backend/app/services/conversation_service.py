"""学习对话持久化：让多轮追问与阶段性笔记不依赖进程内 checkpoint。"""
from __future__ import annotations

from ..models.db import session
from ..models.entities import ConversationMessage


def append_message(user_id: str, session_id: str, role: str, content: str, *, source_evidence: list[dict] | None = None, course_release_id: str | None = None) -> None:
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
            source_evidence=source_evidence or [],
            course_release_id=_course_release_id() if course_release_id is None else course_release_id,
        ))
        s.commit()


def clear_session_messages(user_id: str, session_id: str) -> int:
    """Delete only the authenticated user's current notebook conversation."""
    from .generation_jobs import transaction, cancel_in_session
    with transaction() as s:
        cancel_in_session(s, user_id, session_id)
        deleted = (
            s.query(ConversationMessage)
            .filter(
                ConversationMessage.user_id == user_id,
                ConversationMessage.session_id == session_id,
            )
            .delete(synchronize_session=False)
        )
        s.commit()
        return int(deleted or 0)


def get_session_messages(user_id: str, session_id: str, *, limit: int = 120) -> list[dict]:
    with session() as s:
        rows = (
            s.query(ConversationMessage)
            .filter(
                ConversationMessage.user_id == user_id,
                ConversationMessage.session_id == session_id,
            )
            .order_by(ConversationMessage.id.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
    rows.reverse()
    from .course_library import public_message
    return [public_message(row) for row in rows]


def current_topic_messages(
    messages: list[dict] | None,
    focus: str | None,
) -> list[dict]:
    """Return only the turn anchored to the current learning question.

    Studio artifacts are intentionally narrower than conversation summaries.  A
    notebook can contain several unrelated questions, so passing the whole chat
    to a note, flashcard, audio, or video prompt lets older topics leak into the
    new artifact.  When the current question is not yet persisted, keep a
    synthetic user turn instead of silently falling back to stale history.
    """

    history = [dict(item) for item in (messages or []) if isinstance(item, dict)]
    target = " ".join(str(focus or "").split())
    if target:
        for index in range(len(history) - 1, -1, -1):
            item = history[index]
            content = " ".join(str(item.get("content") or "").split())
            if item.get("role") == "user" and content == target:
                scoped = [item]
                for followup in history[index + 1:]:
                    if followup.get("role") == "user":
                        break
                    scoped.append(followup)
                return scoped
        return [{"role": "user", "content": str(focus).strip()}]

    for index in range(len(history) - 1, -1, -1):
        if history[index].get("role") != "user":
            continue
        scoped = [history[index]]
        for followup in history[index + 1:]:
            if followup.get("role") == "user":
                break
            scoped.append(followup)
        return scoped
    return []


def _course_release_id() -> str:
    from .learning_scope import current_space
    return str((current_space() or {}).get("course", {}).get("course_release_id") or "")
