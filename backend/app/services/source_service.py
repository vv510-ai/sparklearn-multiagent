"""Tenant-safe descriptions of the source scope selected for a learning turn."""
from __future__ import annotations

import json

from ..config import UPLOAD_SOURCES_DIR
from ..rag.ingest import COURSE_SCOPE_ID, chunks_for_source, source_status


def selected_source_summaries(
    user_id: str,
    source_ids: list[str],
    notebook_id: str = "",
) -> list[dict]:
    selected = list(dict.fromkeys(
        str(source_id).strip() for source_id in source_ids if str(source_id).strip()
    ))
    if not selected:
        return []

    metas: dict[str, dict] = {}
    if UPLOAD_SOURCES_DIR.exists():
        for path in UPLOAD_SOURCES_DIR.rglob("*.meta.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(meta, dict) or not meta.get("id"):
                continue
            if str(meta.get("user_id") or "") != user_id:
                continue
            if notebook_id and str(meta.get("notebook_id") or "") != notebook_id:
                continue
            metas[str(meta["id"])] = meta

    items: list[dict] = []
    for source_id in selected:
        if source_id == COURSE_SCOPE_ID:
            from .learning_scope import current_space
            book = (current_space() or {}).get("course", {}).get("textbook") or {}
            items.append({
                "id": source_id,
                "title": book.get("title", "课程知识库"),
                "filename": "",
                "chunk_count": None,
                "status": "indexed",
                "source_type": "course",
            })
            continue
        meta = metas.get(source_id)
        if not meta:
            continue
        chunk_count = len(chunks_for_source(source_id, user_id=user_id))
        items.append({
            "id": source_id,
            "title": str(meta.get("title") or meta.get("filename") or "未命名资料"),
            "filename": str(meta.get("filename") or ""),
            "chunk_count": chunk_count,
            "status": source_status(meta, chunk_count),
            "source_type": str(meta.get("source_type") or "upload"),
        })
    return items
