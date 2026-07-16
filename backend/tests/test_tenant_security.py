from __future__ import annotations

import numpy as np

from app.models import db as db_module
from app.rag.vector_store import MemoryStore


def test_memory_vector_search_filters_tenant_before_ranking():
    store = MemoryStore.__new__(MemoryStore)
    store.meta = [
        {"source_id": "builtin", "user_id": "", "text": "course"},
        {"source_id": "alice-note", "user_id": "alice", "text": "alice"},
        {"source_id": "bob-note", "user_id": "bob", "text": "bob"},
    ]
    store.mat = np.asarray([
        [0.2, 0.0],
        [0.9, 0.0],
        [1.0, 0.0],
    ], dtype=np.float32)
    query = np.asarray([1.0, 0.0], dtype=np.float32)

    alice = store.search(query, user_id="alice", top_k=10)
    assert {hit["source_id"] for hit in alice} == {"builtin", "alice-note"}
    assert all(hit["user_id"] != "bob" for hit in alice)

    selected = store.search(
        query,
        user_id="alice",
        source_ids=["bob-note"],
        include_builtin=False,
    )
    assert selected == []

    anonymous = store.search(query, top_k=10)
    assert [hit["source_id"] for hit in anonymous] == ["builtin"]


class _CaptureConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))


class _Begin:
    def __init__(self, connection: _CaptureConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


class _CaptureEngine:
    def __init__(self) -> None:
        self.connection = _CaptureConnection()

    def begin(self):
        return _Begin(self.connection)


def test_postgres_tenant_policy_is_forced_and_fails_closed():
    engine = _CaptureEngine()
    db_module._apply_postgres_tenant_security(engine)
    sql = "\n".join(engine.connection.statements)

    for table in db_module.TENANT_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY sparklearn_tenant_isolation ON {table}" in sql
    assert "current_setting('app.current_user_id', true)" in sql
    assert "WITH CHECK" in sql
