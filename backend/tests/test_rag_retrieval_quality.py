from __future__ import annotations

import asyncio
import base64
import sys
import types

import numpy as np


def test_fastembed_backend_uses_chinese_bge_and_query_instruction(monkeypatch):
    from app.rag.embedding import _FastEmbedBackend

    monkeypatch.delenv("FASTEMBED_MODEL_PATH", raising=False)
    captured = {}

    class FakeTextEmbedding:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def embed(self, texts, **kwargs):
            captured["texts"] = list(texts)
            captured.update(kwargs)
            return [np.ones(512, dtype=np.float32)]

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding))
    backend = _FastEmbedBackend()
    result = backend.embed(["图是什么"], domain="query")

    assert captured["model_name"] == "BAAI/bge-small-zh-v1.5"
    assert captured["threads"] == 1
    assert captured["enable_cpu_mem_arena"] is False
    assert captured["specific_model_path"] is None
    assert captured["local_files_only"] is False
    assert captured["texts"][0].startswith("为这个句子生成表示以用于检索相关文章：")
    assert result.shape == (1, 512)


def test_hash_embedding_keeps_single_character_topic():
    from app.rag.embedding import _HashBackend

    backend = _HashBackend()
    documents = backend.embed([
        "图由顶点和边组成，可以表示对象之间的关系。",
        "排序算法把一组元素按关键字重新排列。",
    ])
    query = backend.embed(["图是什么"], domain="query")[0]
    scores = documents @ query

    assert scores[0] > scores[1]


def test_hybrid_reranker_corrects_wrong_vector_order(monkeypatch):
    from app import config
    from app.rag.reranker import rerank

    monkeypatch.setenv("RERANK_MODE", "hybrid")
    config.get_settings.cache_clear()
    docs = [
        {
            "text": "二叉树中每个节点最多有两个孩子。",
            "chapter": "第6章 二叉树",
            "kp": "binary_tree",
            "score": 0.95,
        },
        {
            "text": "图由顶点集合和边集合组成，用来表示对象之间的关系。",
            "chapter": "第9章 图与最短路",
            "kp": "graph_basic",
            "score": 0.10,
        },
    ]

    ranked, mode = rerank("图是什么", docs, top_k=2)

    assert mode == "hybrid"
    assert ranked[0]["kp"] == "graph_basic"
    assert ranked[0]["lexical_score"] > ranked[1]["lexical_score"]
    assert ranked[0]["vector_score"] == 0.10


def test_semantic_hybrid_reranker_is_active_with_bge(monkeypatch):
    from app import config
    from app.rag import reranker

    monkeypatch.setenv("RERANK_MODE", "semantic")
    config.get_settings.cache_clear()
    monkeypatch.setattr(reranker, "embedding_status", lambda: {"backend": "bge-small-zh-v1.5"})

    def fake_embed(texts, *, domain="para"):
        if domain == "query":
            return np.asarray([[1.0, 0.0]], dtype=np.float32)
        return np.asarray([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32)

    monkeypatch.setattr(reranker, "embed_texts", fake_embed)
    docs = [
        {"text": "二叉树节点", "chapter": "二叉树", "score": 0.95},
        {"text": "国际贸易中的英文书信", "chapter": "外贸函电", "score": 0.10},
    ]
    ranked, mode = reranker.rerank("怎样写外贸函电", docs, top_k=2)

    assert mode == "semantic-hybrid"
    assert ranked[0]["chapter"] == "外贸函电"
    assert ranked[0]["semantic_score"] > ranked[1]["semantic_score"]


def test_real_course_short_queries_rank_the_correct_chapter(monkeypatch):
    from app import config
    from app.rag.embedding import _HashBackend
    from app.rag.ingest import load_all_chunks
    from app.rag.reranker import rerank

    monkeypatch.setenv("RERANK_MODE", "hybrid")
    config.get_settings.cache_clear()
    chunks = load_all_chunks()
    backend = _HashBackend()
    vectors = backend.embed([chunk["text"] for chunk in chunks])
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)

    expectations = (("图是什么", "第9章 图"), ("栈是什么", "第3章 栈与队列"))
    for query, expected_chapter in expectations:
        query_vector = backend.embed([query], domain="query")[0]
        query_vector /= max(np.linalg.norm(query_vector), 1e-9)
        scores = vectors @ query_vector
        indices = np.argsort(-scores)[:40]
        candidates = [{**chunks[index], "score": float(scores[index])} for index in indices]

        ranked, mode = rerank(query, candidates, top_k=5)

        assert mode == "hybrid"
        assert ranked[0]["chapter"] == expected_chapter


def test_api_reranker_failure_falls_back_to_hybrid(monkeypatch):
    from app import config
    from app.rag import reranker

    monkeypatch.setenv("RERANK_MODE", "auto")
    monkeypatch.setenv("RERANK_API_URL", "https://reranker.invalid/v1/rerank")
    config.get_settings.cache_clear()
    monkeypatch.setattr(reranker.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    ranked, mode = reranker.rerank("栈是什么", [
        {"text": "队列先进先出。", "chapter": "队列", "score": 0.9},
        {"text": "栈是后进先出的线性结构。", "chapter": "栈与队列", "score": 0.2},
    ], top_k=2)

    assert mode == "hybrid"
    assert "栈是" in ranked[0]["text"]


def test_iflytek_backend_uses_official_query_and_para_domains(monkeypatch):
    from app import config
    from app.rag import embedding

    monkeypatch.setenv("SPARK_APPID", "test-app")
    monkeypatch.setenv("SPARK_API_KEY", "test-key")
    monkeypatch.setenv("SPARK_API_SECRET", "test-secret")
    config.get_settings.cache_clear()
    calls = []
    encoded_vector = base64.b64encode(
        np.zeros(embedding.IFLYTEK_DIM, dtype="<f4").tobytes()
    ).decode("ascii")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "header": {"code": 0, "message": "success"},
                "payload": {"feature": {"text": encoded_vector}},
            }

    def fake_post(url, *, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(embedding.requests, "post", fake_post)
    backend = embedding._IflytekBackend()
    result = backend.embed(["图由顶点和边组成"], domain="para")

    assert result.shape == (1, embedding.IFLYTEK_DIM)
    assert calls[0][1]["parameter"]["emb"]["domain"] == "query"
    assert calls[1][1]["parameter"]["emb"]["domain"] == "para"
    assert "authorization=" in calls[0][0]


def test_reasoner_calls_spark_x2_with_auto_thinking(monkeypatch):
    from app import config
    from app.llm import spark_client

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SPARK_API_PASSWORD", "test-password")
    monkeypatch.setenv("SPARK_REASONING_MODE", "auto")
    config.get_settings.cache_clear()
    captured = {}

    class Message:
        content = "ok"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(spark_client, "_client", lambda x2=False: Client())
    result = asyncio.run(spark_client.llm_complete("解释图", role="reasoner"))

    assert result == "ok"
    assert captured["model"] == "spark-x"
    assert captured["extra_body"] == {"thinking": {"type": "auto"}}
