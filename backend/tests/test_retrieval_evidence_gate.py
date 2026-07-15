"""Explicit concept evidence gate for source-grounded remediation."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests._stubs import install  # noqa: E402

install()

from app.rag import retriever  # noqa: E402


def test_required_terms_remove_unrelated_source_chunks(monkeypatch):
    monkeypatch.setattr(retriever, "_hits_from_sources", lambda *args, **kwargs: [
        {
            "text": "本节介绍数组的顺序存储。",
            "source": "课程讲义",
            "source_id": "selected-source",
            "kp": "array",
            "score": 0.99,
        },
        {
            "text": "二叉树中的每个节点最多有两个孩子。",
            "source": "课程讲义",
            "source_id": "selected-source",
            "kp": "binary_tree",
            "score": 0.42,
        },
    ])
    monkeypatch.setattr(
        retriever,
        "rerank",
        lambda query, hits, top_k: (hits[:top_k], "test"),
    )

    hits = retriever.retrieve(
        "二叉树概念",
        source_ids=["selected-source"],
        required_terms=["二叉树", "binary_tree"],
    )

    assert len(hits) == 1
    assert hits[0]["kp"] == "binary_tree"


def test_required_terms_return_empty_when_source_has_no_concept_evidence(monkeypatch):
    monkeypatch.setattr(retriever, "_hits_from_sources", lambda *args, **kwargs: [
        {
            "text": "本节只介绍数组。",
            "source": "课程讲义",
            "source_id": "selected-source",
            "kp": "array",
            "score": 0.99,
        },
    ])
    monkeypatch.setattr(
        retriever,
        "rerank",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not rerank")),
    )

    assert retriever.retrieve(
        "二叉树概念",
        source_ids=["selected-source"],
        required_terms=["二叉树", "binary_tree"],
    ) == []
