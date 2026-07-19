"""Embedding backends with deployment-safe fallbacks.

Auto mode prefers local FastEmbed ``bge-small-zh-v1.5`` INT8, then the official
iFlytek Embedding API, then an offline hashing encoder.  BGE-M3 remains an
explicit optional backend.  The hashing encoder deliberately keeps Chinese
single-character features so short questions such as ``图是什么`` remain
retrievable even when no hosted embedding service is configured.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from functools import lru_cache

import numpy as np
import requests

from ..config import get_settings
from ..llm.signing import assemble_auth_url

log = logging.getLogger("sparklearn.embedding")
HASH_DIM = 1024
IFLYTEK_DIM = 2560
_QUESTION_PREFIXES = (
    "请问", "麻烦解释", "请解释", "帮我解释", "帮我介绍", "介绍一下",
    "什么是", "为什么",
)
_QUESTION_SUFFIXES = (
    "是什么", "是啥", "是什么意思", "什么意思", "的定义", "怎么理解",
    "请解释", "介绍一下",
)


def query_core(text: str) -> str:
    """Remove conversational question wrappers while retaining the topic."""

    value = re.sub(r"[\s？?。！!，,；;：:]+", "", str(text or "")).lower()
    changed = True
    while changed and value:
        changed = False
        for prefix in _QUESTION_PREFIXES:
            if value.startswith(prefix) and len(value) > len(prefix):
                value = value[len(prefix):]
                changed = True
        for suffix in _QUESTION_SUFFIXES:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[:-len(suffix)]
                changed = True
    return value or re.sub(r"\s+", "", str(text or "")).lower()


class _BGEBackend:
    name, dim = "bge-m3", 1024

    def __init__(self) -> None:
        from FlagEmbedding import BGEM3FlagModel

        self.model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)

    def embed(self, texts: list[str], *, domain: str = "para") -> np.ndarray:
        del domain
        out = self.model.encode(texts)["dense_vecs"]
        return np.asarray(out, dtype=np.float32)


class _FastEmbedBackend:
    """Lightweight Chinese BGE embeddings backed by ONNX Runtime."""

    name, dim = "bge-small-zh-v1.5-int8", 512
    model_name = "BAAI/bge-small-zh-v1.5"

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        cache_dir = os.getenv("FASTEMBED_CACHE_DIR", "").strip() or None
        model_path = os.getenv("FASTEMBED_MODEL_PATH", "").strip() or None
        self.model = TextEmbedding(
            model_name=self.model_name,
            cache_dir=cache_dir,
            threads=max(1, int(os.getenv("FASTEMBED_THREADS", "1"))),
            enable_cpu_mem_arena=False,
            specific_model_path=model_path,
            local_files_only=bool(model_path),
        )
        self.batch_size = max(1, int(os.getenv("FASTEMBED_BATCH_SIZE", "2")))

    def embed(self, texts: list[str], *, domain: str = "para") -> np.ndarray:
        values = [str(text or "") for text in texts]
        if domain == "query":
            values = [
                f"为这个句子生成表示以用于检索相关文章：{query_core(text)}"
                for text in values
            ]
        vectors = list(self.model.embed(values, batch_size=self.batch_size))
        return np.asarray(vectors, dtype=np.float32)


class _IflytekBackend:
    """Official signed iFlytek llm-embedding HTTP protocol."""

    name, dim = "iflytek", IFLYTEK_DIM

    def __init__(self) -> None:
        settings = get_settings()
        if not (settings.spark_appid and settings.spark_api_key and settings.spark_api_secret):
            raise RuntimeError("SPARK_APPID/SPARK_API_KEY/SPARK_API_SECRET are required")
        self.appid = settings.spark_appid
        self.api_key = settings.spark_api_key
        self.api_secret = settings.spark_api_secret
        self.url = settings.iflytek_embedding_url
        self.timeout = settings.embedding_timeout_s

        # Select this backend only when the account is actually entitled to the
        # service.  Otherwise auto mode safely proceeds to the offline backend.
        probe = self._embed_one("检索", domain="query")
        if probe.shape != (IFLYTEK_DIM,):
            raise RuntimeError(f"unexpected iFlytek embedding dimension: {probe.shape}")

    @staticmethod
    def _clip_text(text: str, max_bytes: int = 1700) -> str:
        raw = str(text or "").encode("utf-8")
        if len(raw) <= max_bytes:
            return str(text or "")
        return raw[:max_bytes].decode("utf-8", errors="ignore")

    def _embed_one(self, text: str, *, domain: str) -> np.ndarray:
        message = {
            "messages": [{"content": self._clip_text(text), "role": "user"}],
        }
        encoded = base64.b64encode(
            json.dumps(message, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        payload = {
            "header": {"app_id": self.appid, "uid": "sparklearn", "status": 3},
            "parameter": {
                "emb": {
                    "domain": "query" if domain == "query" else "para",
                    "feature": {"encoding": "utf8", "compress": "raw", "format": "plain"},
                },
            },
            "payload": {
                "messages": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "json",
                    "status": 3,
                    "text": encoded,
                },
            },
        }
        signed_url = assemble_auth_url(
            self.url, self.api_key, self.api_secret, method="POST"
        )
        response = requests.post(signed_url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        header = data.get("header") if isinstance(data, dict) else {}
        code = int((header or {}).get("code", -1))
        if code != 0:
            raise RuntimeError(
                f"iFlytek embedding error {code}: {(header or {}).get('message', 'unknown')}"
            )
        feature = ((data.get("payload") or {}).get("feature") or {}).get("text", "")
        raw = base64.b64decode(feature)
        vector = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=True)
        if vector.size != IFLYTEK_DIM:
            raise RuntimeError(f"expected {IFLYTEK_DIM} values, got {vector.size}")
        return vector

    def embed(self, texts: list[str], *, domain: str = "para") -> np.ndarray:
        return np.vstack([self._embed_one(text, domain=domain) for text in texts])


class _HashBackend:
    """Chinese-aware signed feature hashing with no model dependency."""

    name, dim = "hash-v2", HASH_DIM

    @staticmethod
    def _add_feature(row: np.ndarray, feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % HASH_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        row[bucket] += sign * weight

    def embed(self, texts: list[str], *, domain: str = "para") -> np.ndarray:
        mat = np.zeros((len(texts), HASH_DIM), dtype=np.float32)
        for i, original in enumerate(texts):
            text = query_core(original) if domain == "query" else str(original or "").lower()
            for token in re.findall(r"[a-z0-9_+#.-]+", text):
                self._add_feature(mat[i], f"latin:{token}", 2.0)
            for sequence in re.findall(r"[\u3400-\u9fff]+", text):
                for n, weight in ((1, 0.9), (2, 1.5), (3, 1.2)):
                    for start in range(max(0, len(sequence) - n + 1)):
                        gram = sequence[start:start + n]
                        self._add_feature(mat[i], f"cjk{n}:{gram}", weight)
        return mat


def _l2(mat: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(mat, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return mat / norm


@lru_cache
def get_backend():
    pref = (get_settings().embedding_backend or "auto").lower()
    order = {
        "bge-small-zh": [_FastEmbedBackend, _HashBackend],
        "bge-small-zh-v1.5": [_FastEmbedBackend, _HashBackend],
        "fastembed": [_FastEmbedBackend, _HashBackend],
        "bge-m3": [_BGEBackend],
        "iflytek": [_IflytekBackend],
        "hash": [_HashBackend],
        "hash-v2": [_HashBackend],
        "auto": [_FastEmbedBackend, _IflytekBackend, _HashBackend],
    }.get(pref, [_HashBackend])
    for backend_class in order:
        try:
            backend = backend_class()
            log.info("Embedding backend: %s (dim=%d)", backend.name, backend.dim)
            return backend
        except Exception as exc:  # noqa: BLE001
            log.info("Embedding backend %s unavailable (%s); trying fallback", backend_class.__name__, exc)
    return _HashBackend()


def embed_texts(texts: list[str], *, domain: str = "para") -> np.ndarray:
    if not texts:
        return np.empty((0, embedding_dim()), dtype=np.float32)
    return _l2(get_backend().embed(texts, domain=domain))


def embedding_dim() -> int:
    return get_backend().dim


def embedding_status() -> dict[str, str | int]:
    backend = get_backend()
    return {"backend": backend.name, "dimension": backend.dim}
