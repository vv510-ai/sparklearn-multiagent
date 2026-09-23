"""Durable subject notebooks and their tenant-scoped chat sessions."""
from __future__ import annotations

import datetime as dt
import json
import uuid
from collections import Counter

from fastapi import HTTPException

from ..config import UPLOAD_SOURCES_DIR
from ..models.db import session
from ..models.entities import ConversationMessage, Notebook


_EMOJIS = ("📘", "🧮", "🧪", "🧠", "💻", "📐", "🌍", "📝")


def _clean_title(title: str) -> str:
    value = " ".join(str(title or "").strip().split())
    if not value:
        raise HTTPException(400, "请输入书本名称或科目")
    return value[:120]


def _emoji_for(title: str) -> str:
    return _EMOJIS[sum(ord(char) for char in title) % len(_EMOJIS)]


def _source_counts(user_id: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not UPLOAD_SOURCES_DIR.exists():
        return counts
    for path in UPLOAD_SOURCES_DIR.rglob("*.meta.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(meta, dict) or str(meta.get("user_id") or "") != user_id:
            continue
        notebook_id = str(meta.get("notebook_id") or "")
        if notebook_id:
            counts[notebook_id] += 1
    return counts


def _serialize(row: Notebook, *, source_count: int = 0, message_count: int = 0) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "title": row.title,
        "emoji": row.emoji or "📘",
        "session_id": row.session_id,
        "source_count": source_count,
        "message_count": message_count,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def create_notebook(user_id: str, title: str) -> dict:
    clean_title = _clean_title(title)
    notebook_id = f"nb_{uuid.uuid4().hex}"
    row = Notebook(
        id=notebook_id,
        user_id=user_id,
        title=clean_title,
        emoji=_emoji_for(clean_title),
        session_id=f"book-{uuid.uuid4().hex[:16]}",
    )
    with session() as db:
        db.add(row)
        db.commit()
    return _serialize(row)


def list_notebooks(user_id: str) -> list[dict]:
    source_counts = _source_counts(user_id)
    with session() as db:
        rows = (
            db.query(Notebook)
            .filter(Notebook.user_id == user_id)
            .order_by(Notebook.updated_at.desc(), Notebook.created_at.desc())
            .all()
        )
        message_counts = Counter(
            message.session_id
            for message in db.query(ConversationMessage)
            .filter(ConversationMessage.user_id == user_id)
            .all()
        )
        return [
            _serialize(
                row,
                source_count=source_counts.get(row.id, 0),
                message_count=int(message_counts.get(row.session_id, 0)),
            )
            for row in rows
        ]


def get_notebook(user_id: str, notebook_id: str, *, include_messages: bool = False) -> dict:
    source_counts = _source_counts(user_id)
    with session() as db:
        row = db.get(Notebook, notebook_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(404, "notebook not found")
        message_rows = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.user_id == user_id,
                ConversationMessage.session_id == row.session_id,
            )
            .order_by(ConversationMessage.id.asc())
            .limit(120)
            .all()
        )
        result = _serialize(
            row,
            source_count=source_counts.get(row.id, 0),
            message_count=len(message_rows),
        )
        if include_messages:
            result["messages"] = [
                {"role": message.role, "content": message.content, "source_evidence": message.source_evidence or []}
                for message in message_rows
            ]
        return result


def start_new_conversation(user_id: str, notebook_id: str) -> dict:
    """Rotate a notebook to a clean chat while preserving its sources and archive."""

    source_counts = _source_counts(user_id)
    with session() as db:
        row = db.get(Notebook, notebook_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(404, "notebook not found")
        row.session_id = f"book-{uuid.uuid4().hex[:16]}"
        row.updated_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        db.refresh(row)
        result = _serialize(
            row,
            source_count=source_counts.get(row.id, 0),
            message_count=0,
        )
        result["messages"] = []
        return result


def ensure_notebook_owner(user_id: str, notebook_id: str) -> Notebook:
    if not str(notebook_id or "").strip():
        raise HTTPException(400, "请选择一本书后再继续")
    with session() as db:
        row = db.get(Notebook, notebook_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(404, "notebook not found")
        return row


def touch_notebook(user_id: str, notebook_id: str) -> None:
    if not str(notebook_id or "").strip():
        return
    with session() as db:
        row = db.get(Notebook, notebook_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(404, "notebook not found")
        row.updated_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
