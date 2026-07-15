from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import knowledge
from app.config import UPLOAD_SOURCES_DIR
from app.main import app
from app.rag.ingest import chunks_for_source, ingest_corpus
from app.rag.retriever import retrieve


def test_image_upload_materializes_ocr_once(monkeypatch):
    calls = 0
    ocr_text = (
        "二叉树课堂讲义照片。二叉树每个节点最多有两个孩子，"
        "前序遍历顺序是根节点、左子树、右子树。"
        "这段固定文字用于验证图片 OCR 入库、切片和指定来源检索。"
    )

    async def fake_ocr(image_bytes, **kwargs):
        nonlocal calls
        calls += 1
        return {
            "ok": True,
            "degraded": False,
            "data": {"text": ocr_text, "chars": len(ocr_text), "engine": "test-ocr"},
            "error": "",
            "capability": "ocr",
            "elapsed_ms": 12,
            "trace_id": kwargs.get("trace_id", ""),
        }

    monkeypatch.setattr(knowledge.multimodal_gateway, "ocr_image", fake_ocr)
    source_id = ""
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/knowledge/upload",
                data={"user_id": "ocr_test_user", "kp": "binary_tree", "title": "二叉树板书照片"},
                files={"file": ("binary-tree-board.png", b"fake-png-ocr-material", "image/png")},
            )
        assert response.status_code == 200, response.text
        payload = response.json()
        source = payload["source"]
        source_id = source["id"]
        assert source["source_type"] == "uploaded_image"
        assert source["status"] == "indexed"
        assert source["selectable"] is True
        assert source["chunk_count"] >= 1
        assert calls == 1

        meta_path = next(UPLOAD_SOURCES_DIR.glob(f"{source_id}*.meta.json"))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["ocr"]["text"] == ocr_text
        assert meta["ocr"]["engine"] == "test-ocr"
        assert meta["ocr"]["degraded"] is False

        chunks = chunks_for_source(source_id)
        assert chunks and all(chunk["source_type"] == "uploaded_image" for chunk in chunks)
        hits = retrieve(
            "前序遍历根节点左子树右子树",
            source_ids=[source_id],
            kp="binary_tree",
            final_k=5,
        )
        assert hits and any(hit["source_id"] == source_id for hit in hits)

        # 重新解析和检索只读 sidecar，不会再次调用 OCR。
        assert chunks_for_source(source_id)
        assert calls == 1
    finally:
        if source_id:
            for path in UPLOAD_SOURCES_DIR.glob(f"{source_id}*"):
                path.unlink(missing_ok=True)
            ingest_corpus(force=True)


def test_failed_image_ocr_leaves_no_partial_source(monkeypatch):
    async def failed_ocr(image_bytes, **kwargs):
        return {
            "ok": False,
            "degraded": True,
            "data": {},
            "error": "credentials not configured",
            "capability": "ocr",
            "elapsed_ms": 0,
            "trace_id": kwargs.get("trace_id", ""),
        }

    monkeypatch.setattr(knowledge.multimodal_gateway, "ocr_image", failed_ocr)
    before = {path.name for path in UPLOAD_SOURCES_DIR.glob("ocr-failure*")}
    with TestClient(app) as client:
        response = client.post(
            "/api/knowledge/upload",
            data={"user_id": "ocr-failure", "kp": "binary_tree", "title": "识别失败样例"},
            files={"file": ("unreadable.jpg", b"fake-jpg-ocr-failure", "image/jpeg")},
        )

    assert response.status_code == 400
    assert "图片识别未配置或失败" in response.json()["detail"]
    after = {path.name for path in UPLOAD_SOURCES_DIR.glob("ocr-failure*")}
    assert after == before
