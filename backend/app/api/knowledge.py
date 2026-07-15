"""Knowledge source APIs for upload, indexing, and retrieval checks."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from ..config import UPLOAD_SOURCES_DIR
from ..llm import multimodal_gateway
from ..rag.ingest import (
    IMAGE_UPLOAD_SUFFIXES,
    chunks_for_source,
    ingest_corpus,
    source_is_selectable,
    source_sha256,
    source_status,
    supported_upload_suffixes,
    upload_meta_path,
)
from ..rag.retriever import retrieve
from ..rag.vector_store import get_store
from ..services.profile_service import ensure_user

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_UPLOAD_BYTES = 4 * 1024 * 1024


def _safe_stem(name: str) -> str:
    stem = Path(name or "source").stem.lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", stem).strip("-")
    return stem[:40] or "source"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _source_response(meta: dict[str, Any], chunk_count: int) -> dict[str, Any]:
    status = source_status(meta, chunk_count)
    detail = str(
        meta.get("status_detail")
        or meta.get("failure_reason")
        or meta.get("quarantine_reason")
        or meta.get("inactive_reason")
        or meta.get("degraded_reason")
        or {
            "processing": "正在解析资料并建立索引",
            "indexed": "索引已完成，可以参与回答和学习资源生成",
            "degraded": "已使用降级解析，建议核对引用片段",
            "failed": "资料解析或索引失败，请检查文件后重新上传",
            "quarantined": "资料已隔离，不会参与当前知识库检索",
            "inactive": "资料已停用",
        }.get(status, "资料状态未知")
    )
    return {
        "id": meta.get("id", ""),
        "user_id": meta.get("user_id", ""),
        "title": meta.get("title", ""),
        "filename": meta.get("filename", ""),
        "kp": meta.get("kp", ""),
        "source_type": meta.get("source_type", ""),
        "bytes": meta.get("bytes", 0),
        "chunk_count": chunk_count,
        "status": status,
        "status_detail": detail,
        "selectable": source_is_selectable(meta, chunk_count),
        "degraded": status == "degraded",
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at") or meta.get("indexed_at") or meta.get("created_at", ""),
        "indexed_at": meta.get("indexed_at", ""),
    }


def _uploaded_metas() -> list[tuple[Path, dict[str, Any]]]:
    if not UPLOAD_SOURCES_DIR.exists():
        return []
    rows: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(UPLOAD_SOURCES_DIR.glob("*.meta.json")):
        meta = _read_json(path)
        if meta.get("id"):
            rows.append((path, meta))
    return rows


def _chunk_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    store = get_store()
    metas = getattr(store, "meta", None) or []
    for chunk in metas:
        source_id = str(chunk.get("source_id") or "")
        if source_id:
            counts[source_id] = counts.get(source_id, 0) + 1
    return counts


def _stored_source_path(meta_path: Path) -> Path:
    return meta_path.with_name(meta_path.name.removesuffix(".meta.json"))


def _duplicate_source(digest: str) -> dict[str, Any] | None:
    for meta_path, meta in _uploaded_metas():
        stored = _stored_source_path(meta_path)
        if not stored.exists():
            continue
        try:
            if source_sha256(stored, meta) == digest:
                return meta
        except OSError:
            continue
    return None


@router.post("/upload")
async def upload_source(
    file: UploadFile = File(...),
    user_id: str = Form("demo_user"),
    kp: str = Form(""),
    title: str = Form(""),
):
    ensure_user(user_id)
    filename = file.filename or "source.txt"
    suffix = Path(filename).suffix.lower()
    if suffix not in supported_upload_suffixes():
        allowed = ", ".join(sorted(supported_upload_suffixes()))
        raise HTTPException(400, f"unsupported file type, allowed: {allowed}")

    max_bytes = MAX_IMAGE_UPLOAD_BYTES if suffix in IMAGE_UPLOAD_SUFFIXES else MAX_UPLOAD_BYTES
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise HTTPException(413, f"file too large, max {max_mb}MB")
    if not data:
        raise HTTPException(400, "empty file")

    UPLOAD_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    duplicate = _duplicate_source(digest)
    if duplicate:
        raise HTTPException(
            409,
            f"duplicate source already exists: {duplicate.get('title') or duplicate.get('filename') or duplicate.get('id')}",
        )
    source_id = f"{user_id}_{uuid.uuid4().hex[:8]}_{_safe_stem(filename)}"
    stored = UPLOAD_SOURCES_DIR / f"{source_id}{suffix}"
    stored.write_bytes(data)

    meta = {
        "id": source_id,
        "user_id": user_id,
        "title": (title or Path(filename).stem).strip(),
        "filename": filename,
        "kp": kp,
        "source_type": (
            "uploaded_image"
            if suffix in IMAGE_UPLOAD_SUFFIXES
            else "uploaded_pdf" if suffix == ".pdf" else "uploaded_text"
        ),
        "bytes": len(data),
        "sha256": digest,
        "status": "processing",
        "status_detail": "文件已接收，正在解析并建立索引",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = upload_meta_path(stored)
    _write_json(meta_path, meta)

    if suffix in IMAGE_UPLOAD_SUFFIXES:
        ocr = await multimodal_gateway.ocr_image(
            data,
            hint="请完整转写这份课程讲义,保留标题、公式、代码和列表层级。",
            purpose="ingest",
            trace_id=f"upload-{source_id}",
        )
        if not ocr["ok"]:
            stored.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            raise HTTPException(
                400,
                "图片识别未配置或失败,请上传清晰的 PNG/JPG 讲义照片,"
                "也可以改用 TXT/MD/PDF 文本资料。",
            )
        ocr_data = ocr["data"]
        meta["ocr"] = {
            "text": str(ocr_data.get("text") or ""),
            "pages": 1,
            "chars": int(ocr_data.get("chars") or 0),
            "elapsed_ms": int(ocr.get("elapsed_ms") or 0),
            "engine": str(ocr_data.get("engine") or "spark_image_understanding"),
            "trace_id": str(ocr.get("trace_id") or ""),
            "degraded": bool(ocr.get("degraded")),
        }
        if meta["ocr"]["degraded"]:
            meta["degraded_reason"] = str(ocr.get("error") or "图片使用降级 OCR 引擎完成解析")
        _write_json(meta_path, meta)

    try:
        vector_count = ingest_corpus(force=True)
        chunks = chunks_for_source(source_id)
        if not chunks:
            stored.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            ingest_corpus(force=True)
            raise HTTPException(400, "no readable text extracted from file")
        meta["chunk_count"] = len(chunks)
        meta["indexed_at"] = datetime.now(timezone.utc).isoformat()
        meta["updated_at"] = meta["indexed_at"]
        meta["status"] = "degraded" if meta.get("ocr", {}).get("degraded") else "indexed"
        meta["status_detail"] = (
            "索引已完成，但图片使用了降级 OCR，请核对引用片段"
            if meta["status"] == "degraded"
            else "索引已完成，可以参与回答和学习资源生成"
        )
        _write_json(meta_path, meta)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        stored.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        ingest_corpus(force=True)
        raise HTTPException(400, f"indexing failed: {exc}") from exc

    sample = [
        {
            "text": c.get("text", "")[:240],
            "citation": c.get("citation") or f"{meta['title']} p.{c.get('page', '?')}",
        }
        for c in chunks[:3]
    ]
    return {
        "source": _source_response(meta, len(chunks)),
        "vector_count": vector_count,
        "sample": sample,
    }


@router.get("/sources")
async def list_sources(user_id: str = Query("demo_user")):
    counts = _chunk_counts()
    items = []
    for _, meta in _uploaded_metas():
        if user_id and meta.get("user_id") != user_id:
            continue
        source_id = str(meta.get("id") or "")
        chunk_count = int(meta.get("chunk_count") or counts.get(source_id, 0))
        items.append(_source_response(meta, chunk_count))
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"items": items}


@router.get("/search")
async def search_knowledge(
    query: str = Query(..., min_length=1),
    kp: str | None = None,
    limit: int = Query(5, ge=1, le=20),
):
    ingest_corpus()
    hits = retrieve(
        query,
        top_k=max(20, limit * 4),
        final_k=max(limit * 2, limit),
        kp=kp,
    )
    return {
        "items": [
            {
                "text": hit.get("text", "")[:480],
                "citation": hit.get("citation", ""),
                "source": hit.get("source", ""),
                "source_id": hit.get("source_id", ""),
                "source_type": hit.get("source_type", ""),
                "kp": hit.get("kp", ""),
                "score": hit.get("score", 0),
            }
            for hit in hits[:limit]
        ]
    }
