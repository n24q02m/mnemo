"""Additional tests for mnemo_mcp.server — covering uncovered lines.

Targets: _embed backend is None, _format_memory tags parse error,
config sync action, config set sync_interval, config set generic,
stats_resource, main function, _init_embedding_backend
candidate exception.
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    _default_embedding_dims,
    _embed,
    _format_memory,
    _json,
    config,
    memory,
    stats_resource,
)


def test_default_embedding_width_is_stable_across_removed_backends(monkeypatch):
    """Legacy backend env selectors are inert; the width contract is 1024.

    De-host rework: the CF D1/Vectorize 1536-width branch is gone; fresh
    stores default to DEFAULT_EMBEDDING_DIMS regardless of stale env vars.
    """
    monkeypatch.setenv("MEMORY_DB_BACKEND", "cf-d1")
    with patch("mnemo_mcp.server.settings") as mock_settings:
        mock_settings.resolve_embedding_dims.return_value = 0
        assert _default_embedding_dims() == 1024

    monkeypatch.setenv("MEMORY_DB_BACKEND", "sqlite")
    with patch("mnemo_mcp.server.settings") as mock_settings:
        mock_settings.resolve_embedding_dims.return_value = 0
        assert _default_embedding_dims() == 1024


@pytest.fixture
def ctx_with_db(tmp_path: Path) -> Generator[tuple[MagicMock, MemoryDB]]:
    """Mock MCP Context with fresh DB."""
    db = MemoryDB(tmp_path / "server_test.db", embedding_dims=0)
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    yield ctx, db
    db.close()


@pytest.mark.parametrize("operation", ["add", "update", "capture"])
async def test_sentinel_validation_errors_hide_internal_details(
    operation, ctx_with_db, monkeypatch
):
    from mnemo_mcp import server

    ctx, db = ctx_with_db
    internal_detail = "fixture internal storage constraint"

    def reject(*args, **kwargs):
        raise ValueError(internal_detail)

    if operation == "add":
        monkeypatch.setattr(db, "add", reject)
        result = await server._handle_add(ctx, "fixture memory")
    elif operation == "update":
        monkeypatch.setattr(db, "update", reject)
        result = await server._handle_update(ctx, "fixture-id", "fixture memory")
    else:

        async def reject_capture(*args, **kwargs):
            raise ValueError(internal_detail)

        monkeypatch.setattr("mnemo_mcp.capture.capture", reject_capture)
        result = await server._handle_capture(ctx, "fixture memory")

    assert "error" in result
    assert internal_detail not in json.dumps(result)


# ---------------------------------------------------------------------------
# _embed edge cases
# ---------------------------------------------------------------------------


class TestEmbed:
    async def test_no_model_returns_none(self):
        """Returns None when model is None (embedding not ready)."""
        result = await _embed("test text", None, 768)
        assert result is None

    async def test_backend_is_none_returns_none(self):
        """Returns None when backend singleton is None despite model being set."""
        with patch("mnemo_mcp.embedder.get_backend", return_value=None):
            result = await _embed("test text", "some-model", 768)
            assert result is None

    async def test_embed_transient_exception_returns_none(self):
        """A transient embedding error degrades this call to None (FTS5-only)."""

        class TransientEmbeddingError(Exception):
            pass

        mock_backend = MagicMock()
        mock_backend.embed_single = AsyncMock(side_effect=TransientEmbeddingError())

        with (
            patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend),
            patch("mnemo_mcp.embedder._is_retryable", return_value=True),
        ):
            result = await _embed("test text", "some-model", 768)
            assert result is None

    async def test_embed_permanent_exception_raises(self):
        """A permanent embedding error is surfaced loudly, not swallowed to None."""
        mock_backend = MagicMock()
        mock_backend.embed_single = AsyncMock(
            side_effect=Exception("model does not exist")
        )

        with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
            with pytest.raises(Exception, match="does not exist"):
                await _embed("test text", "some-model", 768)

    async def test_embed_query_passes_query_role(self):
        """Any backend receives the query role for search embeddings."""
        mock_backend = MagicMock()
        mock_backend.embed_single = AsyncMock(return_value=[0.1, 0.2])

        result = await _embed(
            "search query",
            "some-model",
            768,
            is_query=True,
            backend=mock_backend,
        )

        assert result == [0.1, 0.2]
        mock_backend.embed_single.assert_awaited_once_with(
            "search query", 768, role="query"
        )

    async def test_embed_document_passes_document_role(self):
        """Any backend receives the document role for stored embeddings."""
        mock_backend = MagicMock()
        mock_backend.embed_single = AsyncMock(return_value=[0.3, 0.4])

        result = await _embed(
            "memory body",
            "some-model",
            768,
            backend=mock_backend,
        )

        assert result == [0.3, 0.4]
        mock_backend.embed_single.assert_awaited_once_with(
            "memory body", 768, role="document"
        )


# ---------------------------------------------------------------------------
# _format_memory edge cases
# ---------------------------------------------------------------------------


class TestFormatMemory:
    def test_tags_parse_error(self):
        """Invalid JSON in tags is left as-is."""
        mem = {"tags": "not-valid-json", "content": "test"}
        result = _format_memory(mem)
        assert result["tags"] == "not-valid-json"

    def test_tags_none_type_error(self):
        """None tags with TypeError don't crash."""
        mem = {"tags": None, "content": "test"}
        result = _format_memory(mem)
        assert result["tags"] is None

    def test_score_rounding(self):
        """Score is rounded to 3 decimal places."""
        mem = {"score": 0.123456789, "content": "test"}
        result = _format_memory(mem)
        assert result["score"] == 0.123

    def test_no_score_no_crash(self):
        """Memories without score are handled."""
        mem = {"content": "test", "tags": '["a"]'}
        result = _format_memory(mem)
        assert "score" not in result


# ---------------------------------------------------------------------------
# config tool — sync and set actions
# ---------------------------------------------------------------------------


class TestConfigSync:
    async def test_config_set_log_level(self, ctx_with_db):
        """Config set log_level updates logger configuration."""
        ctx, _ = ctx_with_db
        result = await config(action="set", key="log_level", value="DEBUG", ctx=ctx)
        assert result["status"] == "updated"
        assert result["key"] == "log_level"

    async def test_config_set_invalid_log_level(self, ctx_with_db):
        """Config set with invalid log level returns error."""
        ctx, _ = ctx_with_db
        result = await config(action="set", key="log_level", value="INVALID", ctx=ctx)
        assert "error" in result
        assert "valid_levels" in result

    async def test_config_backfill_embeddings_uses_request_backend(self):
        """Backfill pages the store and writes vectors through the active backend."""
        db = MagicMock()
        db.rows_without_vectors.side_effect = [
            [
                {"id": "m-1", "content": "first memory"},
                {"id": "m-2", "content": "second memory"},
            ],
            [],
        ]
        backend = MagicMock()
        backend.embed_texts = AsyncMock(return_value=[[1.0] * 1536, [2.0] * 1536])
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "db": db,
            "embedding_model": "cohere/embed-v4.0",
            "embedding_dims": 1536,
        }

        with patch("mnemo_mcp.embedder.get_backend", return_value=backend):
            result = await config(action="backfill_embeddings", batch_size=2, ctx=ctx)

        assert result == {
            "status": "completed",
            "model": "cohere/embed-v4.0",
            "dimensions": 1536,
            "scanned": 2,
            "embedded": 2,
            "skipped": 0,
            "failed": 0,
        }
        assert db.write_vector.call_count == 2
        backend.embed_texts.assert_awaited_once_with(
            ["first memory", "second memory"], 1536, role="document"
        )

    @pytest.mark.parametrize("batch_size", [0, 101, True, "2"])
    async def test_config_backfill_rejects_unbounded_batch_size(
        self, ctx_with_db, batch_size
    ):
        ctx, _ = ctx_with_db
        result = await config(
            action="backfill_embeddings", batch_size=batch_size, ctx=ctx
        )
        assert result["error"].startswith("batch_size must be")

    async def test_config_backfill_default_batch_size_reports_unavailable(self):
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "db": MagicMock(),
            "embedding_model": "cohere/embed-v4.0",
            "embedding_dims": 1536,
        }
        with patch("mnemo_mcp.embedder.get_backend", return_value=None):
            result = await config(action="backfill_embeddings", ctx=ctx)
        assert result == {
            "status": "unavailable",
            "error": "No embedding backend is configured for the current subject.",
            "suggestion": "Verify embedding configuration or run the setup flow.",
            "scanned": 0,
            "embedded": 0,
            "skipped": 0,
            "failed": 0,
        }

    async def test_config_backfill_skips_empty_page(self):
        """Blank-content rows are skipped without spending an embed call."""

        class LegacyDB:
            def __init__(self):
                self.calls = 0
                self.written = []

            def rows_without_vectors(self, limit):
                self.calls += 1
                return [{"id": "empty", "content": ""}] if self.calls == 1 else []

            def write_vector(self, memory_id, vector):
                self.written.append((memory_id, vector))

        db = LegacyDB()
        backend = MagicMock()
        backend.embed_texts = AsyncMock()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "db": db,
            "embedding_model": "cohere/embed-v4.0",
            "embedding_dims": 1536,
        }
        with patch("mnemo_mcp.embedder.get_backend", return_value=backend):
            result = await config(action="backfill_embeddings", batch_size=2, ctx=ctx)

        assert result["status"] == "completed"
        assert result["scanned"] == 1
        assert result["skipped"] == 1
        backend.embed_texts.assert_not_awaited()

    async def test_config_backfill_continues_after_full_empty_page(self):
        db = MagicMock()
        db.rows_without_vectors.side_effect = [
            [
                {"id": "empty-1", "content": ""},
                {"id": "empty-2", "content": "  "},
            ],
            [],
        ]
        backend = MagicMock()
        backend.embed_texts = AsyncMock()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "db": db,
            "embedding_model": "cohere/embed-v4.0",
            "embedding_dims": 1536,
        }
        with patch("mnemo_mcp.embedder.get_backend", return_value=backend):
            result = await config(action="backfill_embeddings", batch_size=2, ctx=ctx)

        assert result["status"] == "completed"
        assert result["scanned"] == 2
        assert result["skipped"] == 2
        assert db.rows_without_vectors.call_count == 2

    async def test_config_backfill_partial_for_provider_and_vector_failures(self):
        db = MagicMock()
        db.rows_without_vectors.side_effect = [
            [{"id": "m-1", "content": "one"}, {"id": "m-2", "content": "two"}],
        ]
        backend = MagicMock()
        backend.embed_texts = AsyncMock(return_value=[[1.0] * 1536])
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "db": db,
            "embedding_model": "cohere/embed-v4.0",
            "embedding_dims": 1536,
        }
        with patch("mnemo_mcp.embedder.get_backend", return_value=backend):
            result = await config(action="backfill_embeddings", batch_size=2, ctx=ctx)
            assert result["status"] == "partial"
            assert result["failed"] == 2

            db.rows_without_vectors.reset_mock()
            db.rows_without_vectors.side_effect = [
                [
                    {"id": "m-1", "content": "one"},
                    {"id": "m-2", "content": "two"},
                ],
            ]
            backend.embed_texts.reset_mock()
            backend.embed_texts.return_value = [[1.0] * 1536, []]
            db.write_vector.side_effect = RuntimeError("vector unavailable")
            result = await config(action="backfill_embeddings", batch_size=2, ctx=ctx)
        assert result["status"] == "partial"
        assert result["embedded"] == 0
        assert result["failed"] == 2

    async def test_config_backfill_provider_exception_is_partial(self):
        db = MagicMock()
        db.rows_without_vectors.return_value = [{"id": "m-1", "content": "one"}]
        backend = MagicMock()
        backend.embed_texts = AsyncMock(side_effect=RuntimeError("provider down"))
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "db": db,
            "embedding_model": "cohere/embed-v4.0",
            "embedding_dims": 1536,
        }
        with patch("mnemo_mcp.embedder.get_backend", return_value=backend):
            result = await config(action="backfill_embeddings", batch_size=2, ctx=ctx)
        assert result["status"] == "partial"
        assert result["failed"] == 1


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResources:
    async def test_stats_resource(self, ctx_with_db):
        """stats_resource returns database stats."""
        ctx, db = ctx_with_db
        db.add("test memory")
        result = json.loads(await stats_resource(ctx=ctx))
        assert result["total_memories"] == 1
        assert "embedding_model" in result


# De-host note: the old TestMainFunction pinned stdio-mode main(); main() now
# only resolves MNEMO_HOST/PORT and delegates to run_server_blocking (covered
# in tests/test_main.py).

# ---------------------------------------------------------------------------
# _init_embedding_backend — candidate exception path
# ---------------------------------------------------------------------------


class TestInitEmbeddingBackend:
    """Cell-first _init_embedding_backend: cloud probe, local leg, FTS5 mode."""

    async def test_embedding_backend_disabled_without_local_or_cloud_model(
        self,
    ):
        """DISABLE_LOCAL_EMBED with no embed cell stays in FTS5 mode."""
        from mnemo_mcp.server import _init_embedding_backend

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.embedder.init_backend") as mock_init,
        ):
            mock_settings.disable_local_embed = True
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)

        assert ctx == {"embedding_model": None, "embedding_dims": 768}
        mock_init.assert_not_called()

    async def test_cell_probe_exception_stays_fts5_only(self):
        """A raising cloud probe surfaces an error and keeps FTS5-only mode."""
        from mnemo_mcp.server import _init_embedding_backend

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=True),
            patch(
                "mnemo_mcp.embedder.init_backend",
                side_effect=Exception("API Error"),
            ),
            patch("mnemo_mcp.server.logger") as mock_logger,
        ):
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)

        assert ctx == {"embedding_model": None, "embedding_dims": 768}
        mock_logger.error.assert_called()

    async def test_local_backend_zero_dims(self):
        """Local check_available == 0 logs the error and keeps FTS5 mode."""
        from mnemo_mcp.server import _init_embedding_backend

        backend = MagicMock()
        backend.check_available.return_value = 0

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server._maybe_register_custom_embed"),
            patch("mnemo_mcp.embedder.init_backend", return_value=backend),
            patch("mnemo_mcp.server.logger") as mock_logger,
        ):
            mock_settings.disable_local_embed = False
            mock_settings.resolve_local_embedding_model.return_value = "local/m"
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)

        assert ctx["embedding_model"] is None
        mock_logger.error.assert_called_with("Local embedding model not available")

    async def test_local_backend_preserves_configured_dimensions(self):
        """A configured storage width is retained after native model probing."""
        from mnemo_mcp.server import _init_embedding_backend

        backend = MagicMock()
        backend.check_available.return_value = 1024

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server._maybe_register_custom_embed"),
            patch("mnemo_mcp.embedder.init_backend", return_value=backend),
        ):
            mock_settings.disable_local_embed = False
            mock_settings.resolve_local_embedding_model.return_value = "local/m"
            ctx: dict = {"embedding_model": None, "embedding_dims": 384}
            await _init_embedding_backend(ctx)

        assert ctx == {"embedding_model": "local/m", "embedding_dims": 384}


class TestCustomEmbeddingRegistration:
    def test_custom_embed_uses_default_dimension_when_unconfigured(self):
        """A BYO model with no width configured receives the default width."""
        from mnemo_mcp.server import _maybe_register_custom_embed

        with (
            patch("mnemo_mcp.server._supported_model_ids", return_value={"known"}),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server._register_embed_spec") as mock_spec,
        ):
            mock_settings.local_embedding_dim = 0
            mock_settings.resolve_embedding_dims.return_value = 0
            mock_settings.local_embedding_model_file = None
            mock_settings.local_embedding_pooling = "mean"
            mock_settings.local_embedding_normalize = True

            _maybe_register_custom_embed("org/custom-embed")

        mock_spec.assert_called_once_with(
            model_id="org/custom-embed",
            hf="org/custom-embed",
            model_file=None,
            dim=1024,
            pooling="mean",
            normalization=True,
        )


async def test_ambient_env_keys_do_not_initialize_backends(monkeypatch):
    """Ambient provider env vars are inert: no cell, no init -- FTS5-only.

    De-host rework: remote startup has no dedicated branch anymore; the pin
    is that COHERE_API_KEY alone initializes nothing.
    """
    from mnemo_mcp.server import _init_embedding_backend, _init_reranker_backend

    monkeypatch.setenv("COHERE_API_KEY", "ambient-must-not-be-used")

    def forbidden(*args, **kwargs):
        pytest.fail("Startup initialized a process-wide provider/model")

    monkeypatch.setattr("mnemo_mcp.embedder.init_backend", forbidden)
    monkeypatch.setattr("mnemo_mcp.reranker.init_reranker", forbidden)
    monkeypatch.setattr("mnemo_mcp.server.cell_configured", lambda task: False)
    monkeypatch.setattr(
        "mnemo_mcp.server.settings",
        MagicMock(disable_local_embed=True, rerank_enabled=False),
    )
    context = {"embedding_model": None, "embedding_dims": 1536}
    await _init_embedding_backend(context)
    await _init_reranker_backend()
    assert context["embedding_model"] is None


# ---------------------------------------------------------------------------
# Memory tool limit clamping
# ---------------------------------------------------------------------------


class TestMemoryLimitClamping:
    async def test_limit_clamped_to_min(self, ctx_with_db):
        """Limit below 1 is clamped to 1."""
        ctx, db = ctx_with_db
        db.add("test")
        result = await memory(action="list", limit=0, ctx=ctx)
        assert result["count"] <= 1

    async def test_limit_clamped_to_max(self, ctx_with_db):
        """Limit above 100 is clamped to 100."""
        ctx, db = ctx_with_db
        result = await memory(action="list", limit=1000, ctx=ctx)
        # Should not crash, limit is clamped
        assert isinstance(result["results"], list)

    async def test_local_backend_init_fails(self):
        """When local backend init raises exception, logs error."""
        from mnemo_mcp.server import _init_embedding_backend

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server._maybe_register_custom_embed"),
            patch(
                "mnemo_mcp.embedder.init_backend",
                side_effect=Exception("init failed test error"),
            ),
            patch("mnemo_mcp.server.logger") as mock_logger,
        ):
            mock_settings.disable_local_embed = False
            mock_settings.resolve_local_embedding_model.return_value = "local/m"
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)
            mock_logger.error.assert_called_with(
                "Local embedding init failed: init failed test error"
            )

        assert ctx["embedding_model"] is None


class TestWarmupInitEmbeddingBackend:
    """Background-init paths of _init_embedding_backend (cell + local leg).

    De-host rework: the multi-candidate cloud chain is gone; the single
    ``[models.embed]`` cell is probed, then the local ONNX leg.
    """

    async def test_cell_probe_success_updates_ctx(self):
        """A healthy cell sets the cell model and keeps the stored width."""
        from mnemo_mcp.server import _init_embedding_backend

        backend = MagicMock()
        backend.check_available = AsyncMock(return_value=3072)

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=True),
            patch("mnemo_mcp.server.model_cell") as mock_model_cell,
            patch("mnemo_mcp.embedder.init_backend", return_value=backend),
        ):
            mock_model_cell.return_value.model = "cell-model"
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)

        assert ctx == {"embedding_model": "cell-model", "embedding_dims": 768}

    async def test_cell_probe_zero_dims_no_local_fallback(self):
        """Configured-but-dead cell: FTS5-only, no silent local download."""
        from mnemo_mcp.server import _init_embedding_backend

        backend = MagicMock()
        backend.check_available = AsyncMock(return_value=0)

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=True),
            patch("mnemo_mcp.embedder.init_backend", return_value=backend) as mock_init,
        ):
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)

        assert ctx["embedding_model"] is None
        mock_init.assert_called_once_with("cloud")

    async def test_direct_local_backend(self):
        """No embed cell -> local ONNX init with the resolved model id."""
        from mnemo_mcp.server import _init_embedding_backend

        backend = MagicMock()
        backend.check_available.return_value = 1024

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server._maybe_register_custom_embed"),
            patch("mnemo_mcp.embedder.init_backend", return_value=backend) as mock_init,
        ):
            mock_settings.disable_local_embed = False
            mock_settings.resolve_embedding_dims.return_value = 0
            mock_settings.resolve_local_embedding_model.return_value = "local/m"
            ctx: dict = {"embedding_model": None, "embedding_dims": 0}
            await _init_embedding_backend(ctx)

        mock_init.assert_called_once_with("local", "local/m")
        assert ctx == {"embedding_model": "local/m", "embedding_dims": 1024}

    async def test_local_backend_check_available_failure_logs_error(self):
        """check_available raising during local init leaves FTS5 mode."""
        from mnemo_mcp.server import _init_embedding_backend

        backend = MagicMock()
        backend.check_available.side_effect = Exception("import error")

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server._maybe_register_custom_embed"),
            patch("mnemo_mcp.embedder.init_backend", return_value=backend),
            patch("mnemo_mcp.server.logger") as mock_logger,
        ):
            mock_settings.disable_local_embed = False
            mock_settings.resolve_local_embedding_model.return_value = "local/m"
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)

        assert ctx["embedding_model"] is None
        mock_logger.error.assert_called_with(
            "Local embedding init failed: import error"
        )

    async def test_local_backend_init_raises_exception(self):
        """init_backend raising logs the same guarded error path."""
        from mnemo_mcp.server import _init_embedding_backend

        with (
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server._maybe_register_custom_embed"),
            patch(
                "mnemo_mcp.embedder.init_backend",
                side_effect=Exception("Init Backend Failed"),
            ),
            patch("mnemo_mcp.server.logger") as mock_logger,
        ):
            mock_settings.disable_local_embed = False
            mock_settings.resolve_local_embedding_model.return_value = "local/m"
            ctx: dict = {"embedding_model": None, "embedding_dims": 768}
            await _init_embedding_backend(ctx)

        assert ctx["embedding_model"] is None
        mock_logger.error.assert_called_with(
            "Local embedding init failed: Init Backend Failed"
        )


class TestJsonHelper:
    """Tests for the _json formatting helper."""

    def test_json_indentation(self):
        """Verify _json serializes with indent=2."""
        data = {"a": 1, "b": [2, 3]}
        result = _json(data)
        expected = json.dumps(data, separators=(",", ":"))
        assert result == expected
        # assert "\n  " in result  # Check for 2-space indentation
