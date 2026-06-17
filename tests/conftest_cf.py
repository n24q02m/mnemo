"""Cloudflare-migration test fixtures: deterministic backend doubles + corpus.

Registered as a plugin from tests/conftest.py (``pytest_plugins``) so the
fixtures below are available to the CF test modules. The fakes are wire-contract
compatible with mcp_core's CfKvBackend / D1Backend / VectorizeBackend so the
same client code runs in tests and on Cloudflare.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import unquote

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
DDL = Path(__file__).parent.parent / "migrations" / "0001_init_mnemo.sql"


class FakeKvHttp:
    """Injectable http for mcp_core CfKvBackend: .request -> (status, body)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def request(self, method, url, data=None, headers=None):
        key = unquote(url.rsplit("/", 1)[-1])
        if method == "PUT":
            self.store[key] = data or b""
            return (200, b"")
        if method == "GET":
            return (200, self.store[key]) if key in self.store else (404, b"")
        if method == "DELETE":
            existed = key in self.store
            self.store.pop(key, None)
            return (200, b"") if existed else (404, b"")
        raise AssertionError(method)


class FakeD1Http:
    """Backs D1 /query with a real in-memory sqlite running the D1 DDL so FTS5
    bm25 + recursive-CTE graph parity holds. Wire: POST /query {sql, params}
    -> (200, {"results": [<row dicts>]})."""

    def __init__(self, ddl_sql: str | None = None) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(ddl_sql or DDL.read_text(encoding="utf-8"))

    def request(self, method, url, data=None, headers=None):
        assert method == "POST" and url.endswith("/query")
        payload = json.loads(data.decode())
        cur = self.conn.execute(payload["sql"], payload.get("params", []))
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        self.conn.commit()
        return (200, json.dumps({"results": rows}).encode())


class FakeVectorizeHttp:
    """Cosine-ranks in-memory vectors with a `sub` metadata filter (D3).
    upsert ndjson {id, values, metadata}; query {vector, topK, filter} ->
    {matches:[{id, score, metadata}]}; GET -> {ready} (eventual-consistency)."""

    def __init__(self, ready_after: int = 0) -> None:
        self.vectors: dict[str, tuple[list[float], dict]] = {}
        self._ready_polls = ready_after

    @staticmethod
    def _cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = sum(x * x for x in a) ** 0.5 or 1.0
        nb = sum(y * y for y in b) ** 0.5 or 1.0
        return dot / (na * nb)

    def request(self, method, url, data=None, headers=None):
        if method == "GET":
            ready = self._ready_polls <= 0
            self._ready_polls -= 1
            return (200, json.dumps({"ready": ready}).encode())
        if url.endswith("/upsert"):
            for line in data.decode().splitlines():
                rec = json.loads(line)
                self.vectors[rec["id"]] = (rec["values"], rec.get("metadata", {}))
            return (200, json.dumps({"mutationId": "mut-test"}).encode())
        if url.endswith("/query"):
            q = json.loads(data.decode())
            flt = q.get("filter") or {}
            cands = [
                (cid, v, md)
                for cid, (v, md) in self.vectors.items()
                if all(md.get(k) == val for k, val in flt.items())
            ]
            ranked = sorted(
                ((cid, self._cosine(q["vector"], v), md) for cid, v, md in cands),
                key=lambda t: t[1],
                reverse=True,
            )[: q["topK"]]
            matches = [{"id": cid, "score": s, "metadata": md} for cid, s, md in ranked]
            return (200, json.dumps({"matches": matches}).encode())
        raise AssertionError(url)


@pytest.fixture
def fake_kv_http():
    return FakeKvHttp()


@pytest.fixture
def fake_d1_http():
    return FakeD1Http()


@pytest.fixture
def fake_vectorize_http():
    return FakeVectorizeHttp()


@pytest.fixture
def cf_env(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-credential-secret")
    monkeypatch.setenv("MCP_STORAGE_BACKEND", "cf-kv")
    monkeypatch.setenv("MCP_KV_BASE_URL", "http://kv.internal")
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    monkeypatch.setenv("MCP_D1_BASE_URL", "http://d1.internal")
    monkeypatch.setenv("MCP_VECTORIZE_BASE_URL", "http://vectorize.internal")
    monkeypatch.setenv("MCP_VECTORIZE_IDX", "mnemo-vectors-test")
    monkeypatch.setenv("EMBEDDING_MODELS", "jina_ai/jina-embeddings-v5-text-small")
    monkeypatch.setenv("RERANK_MODELS", "jina_ai/jina-reranker-v3")
    monkeypatch.setenv("JINA_AI_API_KEY", "dummy-jina-key")


@pytest.fixture
def local_default_env(monkeypatch):
    for var in ("MCP_STORAGE_BACKEND", "MCP_KV_BASE_URL", "DOCS_DB_BACKEND"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def cf_corpus():
    return [
        json.loads(line)
        for line in (FIXTURES / "cf_corpus.jsonl").read_text().splitlines()
    ]


@pytest.fixture
def cf_golden_topk():
    return json.loads((FIXTURES / "cf_golden_topk.json").read_text())
