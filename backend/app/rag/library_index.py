"""Immutable public textbook index, built before release activation."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
from pathlib import Path
from functools import lru_cache

import numpy as np
from fastapi import HTTPException
from .embedding import get_backend, embed_texts, embedding_status

PIPELINE = "library-v1:parent-sections:token-420:utf8-fallback-420:l2"


@lru_cache(maxsize=4)
def _model_identity(backend) -> dict:
    info = {"name": backend.name, "dimension": backend.dim, "pipeline": PIPELINE,
            "embedding_code": hashlib.sha256(Path(__file__).with_name("embedding.py").read_bytes()).hexdigest()}
    inner = getattr(getattr(backend, "model", None), "model", None)
    directory = getattr(inner, "_model_dir", None)
    if directory:
        hashes = {}
        for path in sorted(Path(directory).rglob("*")):
            if path.is_file() and path.suffix in {".onnx", ".json", ".txt"}:
                h = hashlib.sha256()
                with path.open("rb") as f:
                    for block in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(block)
                hashes[str(path.relative_to(directory))] = h.hexdigest()
        info["files"] = hashes
    else:
        # Backends without reproducible local weights cannot reuse an index across
        # process lifetimes solely because they share a model name/dimension.
        if not backend.name.startswith("hash"):
            import os
            info["runtime_instance"] = f"{os.getpid()}:{id(backend)}"
    for package in ("fastembed", "tokenizers"):
        try:
            info[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    return info


def index_identity() -> dict:
    return _model_identity(get_backend())


def _counter():
    backend = get_backend()
    inner = getattr(getattr(backend, "model", None), "model", None)
    tokenizer = getattr(inner, "tokenizer", None)
    if tokenizer is not None:
        from tokenizers import Tokenizer
        counter = Tokenizer.from_str(tokenizer.to_str())
        counter.no_truncation()
        counter.no_padding()
        return lambda text: len(counter.encode(text).ids)
    # UTF-8 bytes is a deliberately conservative bound for the supported local
    # BGE tokenizers; also below the hosted backend's byte clipping threshold.
    return lambda text: len(text.encode("utf-8")) + 2


def chunks_for_book(book: dict, release_id: str) -> list[dict]:
    count = _counter()
    result = []
    for section in book["sections"]:
        text, start = section["text"], 0
        while start < len(text):
            lo, hi = start + 1, min(len(text), start + 1800)
            while lo < hi:
                middle = (lo + hi + 1) // 2
                if count(text[start:middle]) <= 420:
                    lo = middle
                else:
                    hi = middle - 1
            end = lo
            if end < len(text):
                newline = text.rfind("\n", start + (end - start) // 2, end)
                if newline > start:
                    end = newline + 1
            part = text[start:end]
            if part.strip():
                result.append({"text": part, "source": book["title"], "source_id": book["id"],
                    "source_type": book.get("source_kind", "textbook"), "course": book["course"], "course_release_id": release_id,
                    "section_id": section["id"], "chapter": section["title"], "kp": ",".join(section["kps"]),
                    "page": len(result) + 1, "location_kind": "章节", "start_char": start, "end_char": end,
                    "version": book["version"], "url": section["url"], "tags": [section["title"], *section["kps"]],
                    "source_sha256": section["sha256"], "user_id": ""})
            start = end
    return result


def build_index(bundle: dict) -> dict:
    chunks = chunks_for_book(bundle["textbook"], bundle["release_id"])
    identity = index_identity()
    vectors = embed_texts([c["text"] for c in chunks])
    if vectors.shape != (len(chunks), identity["dimension"]) or not np.isfinite(vectors).all():
        raise ValueError("Invalid public index vectors")
    return {"identity": identity, "chunks": chunks, "vectors": vectors.tolist(),
            "generation": hashlib.sha256(json.dumps([identity, chunks], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def retrieve_release(release_id: str, query: str, kp: str | None = None, top_k: int = 20) -> list[dict]:
    from ..services.course_library import load_release
    from .retriever import hit_matches_kp
    _, index = load_release(release_id)
    if index.get("identity") != index_identity():
        raise HTTPException(503, "教材检索模型已变化，索引正在等待重建；正文阅读仍可使用")
    selected = [i for i, c in enumerate(index["chunks"]) if hit_matches_kp(c, kp)]
    if not selected:
        return []
    vectors = np.asarray(index["vectors"], dtype=np.float32)[selected]
    query_vector = embed_texts([query], domain="query")[0]
    scores = vectors @ query_vector
    candidates = [{**index["chunks"][i], "score": float(score), "index_generation": index["generation"],
                   "retrieval_mode": "lexical-hash" if get_backend().name.startswith("hash") else "semantic"}
                  for i, score in zip(selected, scores)]
    # Lexical rerank works across the bounded course corpus without re-encoding.
    # Keep all candidates here so exact terms survive weak vector recall.
    from .reranker import _local_hybrid_rerank
    return _local_hybrid_rerank(query, candidates, top_k)
