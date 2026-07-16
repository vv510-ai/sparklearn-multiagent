"""向量库:Milvus(生产)/ 内置内存库(轻量演示,自动持久化 JSON)双后端同构接口。

接口:upsert(chunks, vectors) / search(qvec, top_k) -> list[hit]
hit = {"text","source","chapter","page","kp","score"}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from ..config import DATA_DIR, get_settings
from .embedding import embedding_dim

log = logging.getLogger("sparklearn.vstore")
COLLECTION = "ds_algo"
_PERSIST = DATA_DIR / "vector_store.json"


class MemoryStore:
    """numpy 余弦检索 + JSON 持久化;适合课程级知识库(千级 chunk)演示。"""

    def __init__(self) -> None:
        self.meta: list[dict] = []
        self.mat: np.ndarray | None = None
        self._load()

    def _load(self) -> None:
        if _PERSIST.exists():
            try:
                data = json.loads(_PERSIST.read_text(encoding="utf-8"))
                if data.get("dim") == embedding_dim():
                    self.meta = data["meta"]
                    self.mat = np.asarray(data["vectors"], dtype=np.float32)
                    log.info("内存向量库载入 %d chunks", len(self.meta))
            except Exception as e:  # noqa: BLE001
                log.warning("向量库持久化文件损坏,忽略:%s", e)

    def persist(self) -> None:
        if self.mat is None:
            return
        _PERSIST.write_text(json.dumps(
            {"dim": embedding_dim(), "meta": self.meta, "vectors": self.mat.tolist()},
            ensure_ascii=False), encoding="utf-8")

    def upsert(self, chunks: list[dict], vectors: np.ndarray) -> None:
        self.meta.extend(chunks)
        self.mat = vectors if self.mat is None else np.vstack([self.mat, vectors])
        self.persist()

    def clear(self) -> None:
        self.meta = []
        self.mat = None
        if _PERSIST.exists():
            _PERSIST.unlink()

    def count(self) -> int:
        return len(self.meta)

    def search(
        self,
        qvec: np.ndarray,
        top_k: int = 20,
        *,
        user_id: str | None = None,
        source_ids: list[str] | None = None,
        include_builtin: bool = True,
    ) -> list[dict]:
        if self.mat is None or not len(self.meta):
            return []
        selected = {str(value) for value in (source_ids or []) if str(value)}
        allowed = []
        for index, meta in enumerate(self.meta):
            owner = str(meta.get("user_id") or "")
            tenant_ok = (include_builtin and not owner) or (
                user_id is not None and owner == str(user_id)
            )
            source_ok = not selected or str(meta.get("source_id") or "") in selected
            if tenant_ok and source_ok:
                allowed.append(index)
        if not allowed:
            return []
        allowed_idx = np.asarray(allowed, dtype=np.int64)
        scores = self.mat @ qvec  # 已归一化 → 余弦
        scores = scores[allowed_idx]
        idx = np.argsort(-scores)[:top_k]
        return [
            {**self.meta[int(allowed_idx[i])], "score": float(scores[i])}
            for i in idx
        ]


class MilvusStore:
    def __init__(self, uri: str) -> None:
        from pymilvus import MilvusClient
        self.mc = MilvusClient(uri=uri)
        dim = embedding_dim()
        if not self.mc.has_collection(COLLECTION):
            self.mc.create_collection(COLLECTION, dimension=dim, metric_type="COSINE",
                                      auto_id=True)
        self._n = 0

    def upsert(self, chunks: list[dict], vectors: np.ndarray) -> None:
        rows = [{"vector": v.tolist(), **c} for c, v in zip(chunks, vectors)]
        self.mc.insert(collection_name=COLLECTION, data=rows)
        self._n += len(rows)

    def clear(self) -> None:
        try:
            if self.mc.has_collection(COLLECTION):
                self.mc.drop_collection(COLLECTION)
            self.mc.create_collection(COLLECTION, dimension=embedding_dim(), metric_type="COSINE",
                                      auto_id=True)
            self._n = 0
        except Exception as exc:  # noqa: BLE001
            log.warning("Milvus clear failed, continuing with existing collection: %s", exc)

    def count(self) -> int:
        try:
            return self.mc.get_collection_stats(COLLECTION).get("row_count", self._n)
        except Exception:  # noqa: BLE001
            return self._n

    def search(
        self,
        qvec: np.ndarray,
        top_k: int = 20,
        *,
        user_id: str | None = None,
        source_ids: list[str] | None = None,
        include_builtin: bool = True,
    ) -> list[dict]:
        tenant_parts = []
        if include_builtin:
            tenant_parts.append('user_id == ""')
        if user_id is not None:
            tenant_parts.append(f"user_id == {json.dumps(str(user_id))}")
        filters = [f"({' or '.join(tenant_parts)})" if tenant_parts else "false"]
        selected = [str(value) for value in (source_ids or []) if str(value)]
        if selected:
            filters.append(f"source_id in {json.dumps(selected)}")
        hits = self.mc.search(
            collection_name=COLLECTION,
            data=[qvec.tolist()],
            limit=top_k,
            filter=" and ".join(filters),
            output_fields=[
                "text", "source", "chapter", "page", "kp",
                "source_type", "url", "tags", "source_id", "user_id",
            ],
        )[0]
        return [{**h["entity"], "score": float(h["distance"])} for h in hits]

    def persist(self) -> None:  # Milvus 自持久化
        pass


_store = None


def get_store():
    global _store
    if _store is None:
        uri = get_settings().milvus_uri
        if uri:
            try:
                _store = MilvusStore(uri)
                log.info("向量库后端:Milvus @ %s", uri)
                return _store
            except Exception as e:  # noqa: BLE001
                log.warning("Milvus 不可用(%s),降级内存向量库", e)
        _store = MemoryStore()
        log.info("向量库后端:MemoryStore(演示)")
    return _store
