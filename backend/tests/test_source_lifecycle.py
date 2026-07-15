from __future__ import annotations

import json

import pytest

from app.api.knowledge import _source_response
from app.rag import ingest


@pytest.mark.parametrize(
    ("raw_status", "chunks", "expected", "selectable"),
    [
        ("active", 0, "processing", False),
        ("active", 3, "indexed", True),
        ("processing", 0, "processing", False),
        ("indexed", 3, "indexed", True),
        ("degraded", 2, "degraded", True),
        ("failed", 0, "failed", False),
        ("quarantined", 4, "quarantined", False),
        ("inactive", 4, "inactive", False),
    ],
)
def test_source_lifecycle_normalizes_status_and_selectability(
    raw_status: str,
    chunks: int,
    expected: str,
    selectable: bool,
):
    meta = {"status": raw_status, "active": raw_status not in {"failed", "quarantined", "inactive"}}
    assert ingest.source_status(meta, chunks) == expected
    assert ingest.source_is_selectable(meta, chunks) is selectable


def test_source_response_exposes_quarantine_reason():
    source = _source_response(
        {
            "id": "source-a",
            "user_id": "alice",
            "title": "跨课程资料",
            "status": "quarantined",
            "active": False,
            "quarantine_reason": "内容与当前课程不匹配",
        },
        12,
    )

    assert source["status"] == "quarantined"
    assert source["selectable"] is False
    assert source["status_detail"] == "内容与当前课程不匹配"


def test_processing_source_cannot_be_selected_even_if_partial_chunks_exist(monkeypatch, tmp_path):
    meta = {
        "id": "source-a",
        "user_id": "alice",
        "status": "processing",
        "active": True,
    }
    (tmp_path / "source-a.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(ingest, "UPLOAD_SOURCES_DIR", tmp_path)
    monkeypatch.setattr(ingest, "load_all_chunks", lambda: [{"source_id": "source-a"}])

    with pytest.raises(ValueError, match="selected sources are unavailable"):
        ingest.validate_source_scope("alice", ["source-a"])
