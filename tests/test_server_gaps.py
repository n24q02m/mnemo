"""Genuine uncovered server paths: lifespan wiring, per-sub store resolution,
manual compression, dispatch guards, embed deadline degradation, HTTP app
assembly, and entrypoint safety guards."""

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    ServerConfigError,
    _embed,
    _enrich_memory,
    _get_ctx,
    _handle_entity_search,
    _handle_memory_compress,
    _is_loopback_host,
    build_http_app,
    lifespan,
    memory,
    run_server_blocking,
)


@pytest.fixture
def ctx_with_db(tmp_path: Path):
    """Mock MCP Context bound to a fresh host-root DB."""
    db = MemoryDB(tmp_path / "server_gaps.db", embedding_dims=0)
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    yield ctx, db
    db.close()


@pytest.fixture(autouse=True)
def _clean_sub_db_cache():
    import mnemo_mcp.server as server_module

    server_module._sub_db_cache.clear()
    yield
    for db in server_module._sub_db_cache.values():
        db.close()
    server_module._sub_db_cache.clear()


def _passthrough_to_thread():
    return patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )


def _mock_settings(**overrides):
    s = MagicMock()
    s.resolve_embedding_dims.return_value = 1024
    s.resolve_local_embedding_model.return_value = "local-embed-model"
    s.recency_half_life_days = 30.0
    s.reindex_on_model_change = False
    s.kg_auto_enabled = False
    s.archive_enabled = False
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


# ---------------------------------------------------------------------------
# lifespan
# ---------------------------------------------------------------------------


class TestLifespan:
    async def test_yields_context_and_cancels_background_tasks(self, tmp_path):
        db_path = tmp_path / "lifespan" / "memories.db"

        async def hanging_init(ctx):
            await asyncio.Event().wait()  # never completes; must be cancelled

        settings = _mock_settings()
        with (
            patch("mnemo_mcp.server.settings", settings),
            patch("mnemo_mcp.server.cell_configured", return_value=True),
            patch("mnemo_mcp.server.model_cell") as model_cell,
            patch("mnemo_mcp.server.db_path_for_namespace", return_value=db_path),
            patch(
                "mnemo_mcp.server._init_embedding_backend",
                side_effect=hanging_init,
            ),
            patch("mnemo_mcp.server._init_reranker_backend", side_effect=hanging_init),
        ):
            model_cell.return_value.model = "cloud-embed"
            async with lifespan(MagicMock()) as ctx:
                assert ctx["embedding_dims"] == 1024
                assert ctx["embedding_model"] is None  # backend not ready yet
                db = ctx["db"]
                assert db.vec_enabled is True
                assert db_path.exists()
        # Exiting the context closes the store.
        with pytest.raises(sqlite3.ProgrammingError):
            db.stats()

    async def test_unconfigured_cell_uses_local_identity(self, tmp_path):
        db_path = tmp_path / "lifespan2" / "memories.db"

        async def instant_init(ctx):
            ctx["embedding_model"] = "local-embed-model"

        settings = _mock_settings()
        with (
            patch("mnemo_mcp.server.settings", settings),
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.db_path_for_namespace", return_value=db_path),
            patch(
                "mnemo_mcp.server._init_embedding_backend",
                side_effect=instant_init,
            ),
            patch(
                "mnemo_mcp.server._init_reranker_backend",
                side_effect=_instant_noop,
            ),
        ):
            async with lifespan(MagicMock()) as ctx:
                await asyncio.sleep(0)  # let the background init task run
                # Background init resolved the model identity in-place.
                assert ctx["embedding_model"] == "local-embed-model"
                db = ctx["db"]

        assert db._db_path == db_path


async def _instant_noop():
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# _get_ctx: per-sub namespace isolation (mode 3)
# ---------------------------------------------------------------------------


class TestGetCtxSubNamespace:
    async def test_non_default_namespace_gets_isolated_cached_store(
        self, tmp_path, ctx_with_db
    ):
        ctx, host_db = ctx_with_db
        alice_path = tmp_path / "alice" / "memories.db"
        settings = _mock_settings()
        with (
            patch("mnemo_mcp.server.current_sub", return_value="alice"),
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings", settings),
            patch("mnemo_mcp.server.db_path_for_namespace", return_value=alice_path),
        ):
            db1, model1, dims1 = _get_ctx(ctx)
            db2, model2, dims2 = _get_ctx(ctx)

        assert db1 is not host_db
        assert db1 is db2  # cached per process
        assert db1._db_path == alice_path
        assert alice_path.exists()  # physically separate store file
        assert model1 is None and dims1 == 0

    async def test_default_namespace_uses_host_store(self, ctx_with_db):
        ctx, host_db = ctx_with_db
        with patch("mnemo_mcp.server.current_sub", return_value="default"):
            db, _, _ = _get_ctx(ctx)
        assert db is host_db


# ---------------------------------------------------------------------------
# _embed deadline degradation
# ---------------------------------------------------------------------------


class TestEmbedDeadline:
    async def test_timeout_degrades_to_fts(self, monkeypatch):
        import mnemo_mcp.server as server_module

        monkeypatch.setattr(server_module, "EMBED_CALL_DEADLINE_S", 0.05)

        class SlowBackend:
            async def embed_single(self, text, dims, role=None):
                await asyncio.sleep(1.0)

        with patch("mnemo_mcp.server.logger") as mock_logger:
            result = await _embed("text", "model", 8, backend=SlowBackend())
        assert result is None
        assert mock_logger.warning.called

    async def test_no_model_returns_none_immediately(self):
        assert await _embed("text", None, 8) is None


# ---------------------------------------------------------------------------
# _enrich_memory paths
# ---------------------------------------------------------------------------


class TestEnrichMemory:
    async def test_scores_and_persists_importance(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("worth remembering")
        with (
            patch("mnemo_mcp.server.settings", _mock_settings()),
            _passthrough_to_thread(),
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                return_value=0.9,
            ),
        ):
            await _enrich_memory(db, mid, "worth remembering")
        assert db.get(mid)["importance"] == 0.9

    async def test_phase3_failure_falls_back_to_legacy_entities(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("Python is a tool")
        graph_data = {
            "entities": [{"name": "Python", "type": "tool"}],
            "relations": [],
        }
        with (
            patch("mnemo_mcp.server.settings", _mock_settings(kg_auto_enabled=True)),
            _passthrough_to_thread(),
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                return_value=0.5,
            ),
            patch(
                "mnemo_mcp.temporal.extract.extract_entities",
                new_callable=AsyncMock,
                side_effect=RuntimeError("phase 3 broken"),
            ),
            patch(
                "mnemo_mcp.graph.extract_entities",
                new_callable=AsyncMock,
                return_value=graph_data,
            ),
        ):
            await _enrich_memory(db, mid, "Python is a tool")

        links = db._conn.execute(
            "SELECT entity_id FROM memory_entity_links WHERE memory_id = ?", (mid,)
        ).fetchall()
        assert len(links) == 1  # legacy path linked the entity despite the failure

    async def test_legacy_path_creates_relations(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("Python powers MCP")
        graph_data = {
            "entities": [
                {"name": "Python", "type": "tool"},
                {"name": "MCP", "type": "project"},
            ],
            "relations": [{"source": "Python", "target": "MCP", "type": "related_to"}],
        }
        with (
            patch("mnemo_mcp.server.settings", _mock_settings(kg_auto_enabled=False)),
            _passthrough_to_thread(),
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                return_value=0.5,
            ),
            patch(
                "mnemo_mcp.graph.extract_entities",
                new_callable=AsyncMock,
                return_value=graph_data,
            ),
        ):
            await _enrich_memory(db, mid, "Python powers MCP")

        edges = db._conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
        links = db._conn.execute(
            "SELECT COUNT(*) FROM memory_entity_links WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
        assert edges == 1
        assert links == 2


# ---------------------------------------------------------------------------
# manual compression handler
# ---------------------------------------------------------------------------


class TestHandleMemoryCompress:
    async def test_requires_memory_id(self, ctx_with_db):
        resp = await _handle_memory_compress(ctx_with_db[0], None)
        assert "error" in resp and "memory_id required" in resp["error"]

    async def test_unknown_id_errors(self, ctx_with_db):
        resp = await _handle_memory_compress(ctx_with_db[0], "missing-id")
        assert "not found" in resp["error"]

    async def test_already_compressed_short_circuits(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add_with_context_type(
            "dense text",
            text_raw="original long text",
            compressed=True,
            compression_provider="gemini",
        )
        resp = await _handle_memory_compress(ctx, mid)
        assert resp == {
            "status": "already_compressed",
            "id": mid,
            "compression_provider": "gemini",
        }

    async def test_compress_unavailable_skips(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("plain row")
        with patch(
            "mnemo_mcp.compression.compress",
            new_callable=AsyncMock,
            return_value={"compressed": False},
        ):
            resp = await _handle_memory_compress(ctx, mid)
        assert resp["status"] == "skipped"

    async def test_successful_compression_updates_row(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("long uncompressed content")
        compress_result = {
            "compressed": True,
            "text": "dense",
            "text_raw": "long uncompressed content",
            "compression_provider": "gemini",
            "tokens_in": 12,
            "tokens_out": 3,
        }
        with (
            _passthrough_to_thread(),
            patch(
                "mnemo_mcp.compression.compress",
                new_callable=AsyncMock,
                return_value=compress_result,
            ),
        ):
            resp = await _handle_memory_compress(ctx, mid)
        assert resp["status"] == "compressed"
        row = db.get(mid)
        assert row["content"] == "dense"
        assert row["compressed"] == 1
        assert row["compression_provider"] == "gemini"


# ---------------------------------------------------------------------------
# dispatch guards
# ---------------------------------------------------------------------------


class TestDispatchGuards:
    async def test_as_of_with_other_action_is_refused(self, ctx_with_db):
        resp = await memory(
            action="search", query="x", as_of="2026-01-01T00:00:00Z", ctx=ctx_with_db[0]
        )
        assert "as_of is only supported" in resp["error"]

    async def test_unknown_action_closest_match_suggestion(self, ctx_with_db):
        resp = await memory(action="addd", ctx=ctx_with_db[0])
        assert resp["suggestion"] == "Did you mean 'add'?"

    async def test_unknown_action_without_match_lists_actions(self, ctx_with_db):
        resp = await memory(action="zzzzzz", ctx=ctx_with_db[0])
        assert resp["suggestion"].startswith("Available actions are:")

    async def test_archived_limit_clamped(self, ctx_with_db):
        resp = await memory(action="archived", limit=0, ctx=ctx_with_db[0])
        assert resp["count"] == 0
        assert "suggestion" in resp

    async def test_as_of_limit_clamped(self, ctx_with_db):
        resp = await memory(
            action="as_of", as_of="2026-01-01T00:00:00Z", limit=500, ctx=ctx_with_db[0]
        )
        assert resp["count"] == 0
        assert resp["as_of"] == "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# search: reranker empty-output fallback
# ---------------------------------------------------------------------------


class TestSearchRerankerFallback:
    async def test_empty_rerank_output_falls_back_to_original_order(
        self, ctx_with_db, monkeypatch
    ):
        ctx, db = ctx_with_db
        db.add("python asyncio basics one")
        db.add("python asyncio basics two")

        outcome = MagicMock()
        outcome.results = []
        monkeypatch.setattr("mnemo_mcp.reranker.get_reranker", lambda: MagicMock())
        monkeypatch.setattr(
            "mnemo_mcp.reranker.describe_reranker", lambda _r: ("backend", "model")
        )
        monkeypatch.setattr(
            "mnemo_mcp.reranker.rerank_with_identity",
            MagicMock(return_value=outcome),
        )
        resp = await memory(action="search", query="python asyncio", limit=2, ctx=ctx)
        assert resp["reranker"]["fallback"] == "original_order_after_empty_result"
        assert len(resp["results"]) == 2
        assert resp["reranked"] is False


# ---------------------------------------------------------------------------
# entity_search validation
# ---------------------------------------------------------------------------


class TestEntitySearchValidation:
    async def test_invalid_entity_type_without_close_match(self, ctx_with_db):
        resp = await _handle_entity_search(
            ctx_with_db[0], name="X", entity_type="zzzzzz"
        )
        assert resp["suggestion"].startswith("Pick an entity_type from")

    async def test_invalid_entity_type_with_close_match(self, ctx_with_db):
        resp = await _handle_entity_search(
            ctx_with_db[0], name="X", entity_type="persn"
        )
        assert resp["suggestion"] == "Did you mean 'person'?"


# ---------------------------------------------------------------------------
# update via dispatch
# ---------------------------------------------------------------------------


class TestUpdateDispatch:
    async def test_update_with_content_reports_updated(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("before")
        resp = await memory(action="update", memory_id=mid, content="after", ctx=ctx)
        assert resp["status"] == "updated"
        assert resp["id"]
        await asyncio.sleep(0)  # let the background enrichment task settle


# ---------------------------------------------------------------------------
# HTTP app + entrypoint guards
# ---------------------------------------------------------------------------


def test_build_http_app_returns_authenticated_starlette_app():
    from starlette.routing import Mount

    settings = _mock_settings()
    with patch("mnemo_mcp.server.build_authenticator", return_value=MagicMock()):
        app = build_http_app(settings)
    assert isinstance(app, Starlette)
    # The MCP ASGI app is mounted at the root behind the auth middleware.
    assert app.routes
    assert isinstance(app.routes[0], Mount)
    assert app.routes[0].path in ("", "/")


def test_is_loopback_host():
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("[::1]") is True
    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("127.255.0.3") is True
    assert _is_loopback_host("8.8.8.8") is False
    assert _is_loopback_host("example.invalid") is False
    assert _is_loopback_host("999.1.1.1") is False


def test_run_server_blocking_refuses_open_auth_off_loopback(monkeypatch):
    hs = _mock_settings()
    hs.server.auth = "open"
    hs.server.host = "127.0.0.1"
    hs.server.port = 8000
    monkeypatch.setattr("mnemo_mcp.runtime.hull_settings", lambda: hs)

    def explode(_name, _port):
        raise AssertionError("LifecycleLock must not be acquired for a refused bind")

    monkeypatch.setattr("hull_core.lifecycle.lock.LifecycleLock", explode)
    with pytest.raises(ServerConfigError, match="only permits loopback binds"):
        run_server_blocking(host="0.0.0.0", port=8000)
