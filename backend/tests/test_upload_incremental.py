"""Failure and concurrency regressions for uploaded-material indexing."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import knowledge
from app.rag import ingest, vector_store, retriever
from app.main import app


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    config.get_settings.cache_clear()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    seed = tmp_path / "seed"
    seed.mkdir()
    monkeypatch.setattr(ingest, "UPLOAD_SOURCES_DIR", uploads)
    monkeypatch.setattr(knowledge, "UPLOAD_SOURCES_DIR", uploads)
    monkeypatch.setattr(knowledge, "_UPLOAD_LOCK", asyncio.Lock())
    monkeypatch.setattr(knowledge, "backup_source_files", lambda *args: None)
    monkeypatch.setattr(ingest, "CORPUS_DIR", seed)
    monkeypatch.setattr(ingest, "EXTRA_SOURCES_DIR", seed)
    monkeypatch.setattr(ingest, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(vector_store, "_PERSIST", tmp_path / "vectors.json")
    store = vector_store.MemoryStore()
    monkeypatch.setattr(vector_store, "_store", store)
    ingest._parsed_upload.cache_clear()
    with TestClient(app) as client:
        yield client, store, uploads
    ingest._parsed_upload.cache_clear()


def upload(client, content, user="incremental-user"):
    return client.post("/api/knowledge/upload", data={"user_id": user},
        files={"file": ("notes.txt", content.encode(), "text/plain")})


A = "甲资料：植物通过光合作用固定二氧化碳，将太阳能转化成有机物中的化学能。消费者通过摄食获得有机物。"
B = "乙资料：递归需要终止条件，每次调用应向终止条件靠近。阶乘的终止条件是零的阶乘等于一。"


def test_incremental_vectors_manifest_and_tenant_isolation(corpus, monkeypatch):
    client, store, _ = corpus
    calls = []
    original = ingest.embed_texts
    def spy(texts, **kwargs):
        calls.extend(texts)
        return original(texts, **kwargs)
    monkeypatch.setattr(ingest, "embed_texts", spy)
    first = upload(client, A).json()
    calls.clear()
    second = upload(client, B)
    assert second.status_code == 200, second.text
    assert calls == [B]  # A was not embedded again.
    assert second.json()["timings"]["reused_chunks"] == 1
    assert ingest._manifest_matches(ingest._current_manifest())
    duplicate = upload(client, B).json()
    assert duplicate["duplicate"] and duplicate["source"]["id"] == second.json()["source"]["id"]
    assert store.count() == 2 and calls == [B]
    monkeypatch.setattr(ingest, "embed_texts", lambda *a, **kw: pytest.fail("unchanged corpus re-embedded"))
    assert ingest.ingest_corpus() == 2
    # Selected retrieval uses existing vectors, and never serves another owner's document.
    monkeypatch.setattr(retriever, "embed_texts", lambda texts, **kw: original(texts, **kw) if kw.get("domain") == "query" else pytest.fail("source vectors recomputed"))
    assert retriever._hits_from_sources("光合作用", [first["source"]["id"]], 5, "incremental-user")
    assert retriever._hits_from_sources("光合作用", [first["source"]["id"]], 5, "someone-else") == []


@pytest.mark.parametrize("stage", ["embedding", "persist"])
def test_failed_new_upload_keeps_previous_snapshot_and_disk(corpus, monkeypatch, stage):
    client, store, _ = corpus
    assert upload(client, A).status_code == 200
    old_file = vector_store._PERSIST.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected write or embedding failure")
    monkeypatch.setattr(ingest if stage == "embedding" else store, "embed_texts" if stage == "embedding" else "_save", fail)
    response = upload(client, B)
    assert response.status_code == 400
    assert store.count() == 1 and store.meta[0]["text"] == A
    assert vector_store._PERSIST.read_bytes() == old_file
    assert vector_store.MemoryStore().meta == store.meta


@pytest.mark.parametrize("stage", ["embedding", "persist"])
def test_slow_indexing_does_not_block_health_sources_or_old_snapshot(corpus, monkeypatch, stage):
    client, store, _ = corpus
    assert upload(client, A).status_code == 200
    entered, release = threading.Event(), threading.Event()
    original_embed = ingest.embed_texts
    original = ingest.embed_texts if stage == "embedding" else store._save
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8), "test did not release embedding"
        return original(*args, **kwargs)
    monkeypatch.setattr(ingest if stage == "embedding" else store, "embed_texts" if stage == "embedding" else "_save", blocked)
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(upload, client, B)
        try:
            assert entered.wait(5)
            assert client.get("/api/health").status_code == 200
            items = client.get("/api/knowledge/sources?user_id=incremental-user").json()["items"]
            assert any(i["status"] == "processing" and not i["selectable"] for i in items)
            assert not future.done() and store.count() == 1
            q = original_embed(["植物"], domain="query")[0]
            assert store.search(q, user_id="incremental-user")[0]["text"] == A
            duplicate = pool.submit(upload, client, B)
        finally:
            release.set()
        one, two = future.result(), duplicate.result()
    assert one.status_code == two.status_code == 200
    assert one.json()["source"]["id"] == two.json()["source"]["id"]
    assert two.json()["duplicate"] is True and store.count() == 2


def test_private_upload_without_sidecar_is_never_public(corpus):
    _, store, uploads = corpus
    (uploads / "orphan.txt").write_text(A, encoding="utf-8")
    assert ingest.ingest_corpus(force=True) == 0
    assert store.meta == []


def test_scope_validation_never_parses_another_pending_upload(corpus, monkeypatch):
    client, store, uploads = corpus
    response = upload(client, A).json()
    (uploads / "pending.pdf").write_bytes(b"slow pending PDF")
    (uploads / "pending.pdf.meta.json").write_text(json.dumps({"id": "pending", "user_id": "incremental-user", "status": "processing"}), encoding="utf-8")
    monkeypatch.setattr(ingest, "load_all_chunks", lambda: pytest.fail("request tried to parse all files"))
    assert ingest.validate_source_scope("incremental-user", [response["source"]["id"]])
    assert ingest.chunks_for_source(response["source"]["id"], "incremental-user")[0]["text"] == A
    with pytest.raises(ValueError):
        ingest.validate_source_scope("incremental-user", ["pending"])


def test_manifest_cache_failure_does_not_undo_committed_upload(corpus, monkeypatch):
    client, store, _ = corpus
    def fail(*args):
        raise OSError("manifest unavailable")
    monkeypatch.setattr(ingest, "_write_manifest", fail)
    assert upload(client, A).status_code == 200
    assert store.count() == 1


def test_final_metadata_failure_is_recoverable_without_duplicate_vectors(corpus, monkeypatch):
    client, store, uploads = corpus
    assert upload(client, A).status_code == 200
    original = knowledge._write_json
    def fail_final(path, meta):
        if meta.get("status") == "indexed":
            raise OSError("final metadata failure")
        return original(path, meta)
    monkeypatch.setattr(knowledge, "_write_json", fail_final)
    assert upload(client, B).status_code == 400
    failed = [json.loads(p.read_text(encoding="utf-8")) for p in uploads.glob("*.meta.json") if 'failed' in p.read_text(encoding="utf-8")][0]
    assert any(p.read_text(encoding="utf-8") == B for p in uploads.glob("*.txt"))
    assert store.count() == 2  # Committed B stays paired with its retained source, but is not selectable.
    with pytest.raises(ValueError):
        ingest.validate_source_scope("incremental-user", [failed["id"]])
    monkeypatch.setattr(knowledge, "_write_json", original)
    retry = upload(client, B)
    assert retry.status_code == 200 and retry.json()["source"]["id"] == failed["id"]
    assert retry.json()["source"]["selectable"] and store.count() == 2
