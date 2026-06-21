"""Tests for mnemo_mcp.server — MCP tools, prompts, resources."""

import json
import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.db import MAX_CONTENT_LENGTH, MemoryDB
from mnemo_mcp.server import (
    _enrich_memory,
    _handle_add,
    _handle_consolidate,
    _handle_search,
    _handle_update,
    _maybe_register_custom_embed,
    _maybe_register_custom_rerank,
    config,
    delete_memory,
    help,
    main,
    memory,
    recall_context,
    save_summary,
)


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


class TestMemoryAdd:
    async def test_add(self, ctx_with_db):
        ctx, db = ctx_with_db
        result = json.loads(await memory(action="add", content="test memory", ctx=ctx))
        assert result["status"] == "saved"
        assert result["id"]
        assert result["semantic"] is False

    async def test_add_with_category(self, ctx_with_db):
        ctx, db = ctx_with_db
        result = json.loads(
            await memory(
                action="add",
                content="test",
                category="work",
                tags=["urgent"],
                ctx=ctx,
            )
        )
        assert result["category"] == "work"
        mem = db.get(result["id"])
        assert mem is not None
        assert json.loads(mem["tags"]) == ["urgent"]

    async def test_add_no_content(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="add", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result

    async def test_add_exceeds_content_length(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await memory(
                action="add",
                content="x" * (MAX_CONTENT_LENGTH + 1),
                ctx=ctx,
            )
        )
        assert "error" in result
        assert "exceeds limit" in result["error"]


class TestMemorySearch:
    async def test_search(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("Python is great for AI and machine learning")
        result = json.loads(await memory(action="search", query="Python AI", ctx=ctx))
        assert result["count"] > 0
        assert result["semantic"] is False
        # Tags should be parsed list, not JSON string
        assert isinstance(result["results"][0]["tags"], list)
        # Score should be rounded
        score = result["results"][0]["score"]
        assert score == round(score, 3)

    async def test_search_no_query(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="search", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result

    async def test_search_with_filters(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("Python tip", category="tech", tags=["python"])
        db.add("Python recipe", category="food", tags=["cooking"])
        result = json.loads(
            await memory(
                action="search",
                query="Python",
                category="tech",
                ctx=ctx,
            )
        )
        assert all(r["category"] == "tech" for r in result["results"])


class TestMemoryList:
    async def test_list(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("mem1", tags=["a", "b"])
        db.add("mem2")
        result = json.loads(await memory(action="list", ctx=ctx))
        assert result["count"] == 2
        # Tags should be parsed lists
        for r in result["results"]:
            assert isinstance(r["tags"], list)

    async def test_list_with_category(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("a", category="x")
        db.add("b", category="y")
        result = json.loads(await memory(action="list", category="x", ctx=ctx))
        assert result["count"] == 1


class TestMemoryUpdate:
    async def test_update(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("original")
        result = json.loads(
            await memory(
                action="update",
                memory_id=mid,
                content="updated",
                ctx=ctx,
            )
        )
        assert result["status"] == "updated"
        mem = db.get(mid)
        assert mem is not None
        assert mem["content"] == "updated"

    async def test_update_no_id(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="update", content="x", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result

    async def test_update_nonexistent(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await memory(
                action="update",
                memory_id="fake123",
                content="x",
                ctx=ctx,
            )
        )
        assert "error" in result

    async def test_update_exceeds_content_length(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("original")
        result = json.loads(
            await memory(
                action="update",
                memory_id=mid,
                content="x" * (MAX_CONTENT_LENGTH + 1),
                ctx=ctx,
            )
        )
        assert "error" in result
        assert "exceeds limit" in result["error"]
        # Original content preserved
        mem = db.get(mid)
        assert mem is not None
        assert mem["content"] == "original"


class TestMemoryDelete:
    async def test_delete(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("to delete")
        result = json.loads(await memory(action="delete", memory_id=mid, ctx=ctx))
        assert result["status"] == "deleted"
        assert db.get(mid) is None

    async def test_delete_no_id(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="delete", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result

    async def test_delete_nonexistent(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await memory(
                action="delete",
                memory_id="fake123",
                ctx=ctx,
            )
        )
        assert "error" in result


class TestDeleteMemoryTool:
    async def test_delete_memory_success(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("to delete via tool")
        result = json.loads(await delete_memory(memory_id=mid, ctx=ctx))
        assert result["status"] == "deleted"
        assert result["id"] == mid
        assert db.get(mid) is None

    async def test_delete_memory_not_found(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await delete_memory(memory_id="fake123", ctx=ctx))
        assert "error" in result
        assert "Memory fake123 not found" in result["error"]


class TestMemoryExportImport:
    async def test_export(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("mem1")
        db.add("mem2")
        result = json.loads(await memory(action="export", ctx=ctx))
        assert result["format"] == "jsonl"
        assert result["count"] == 2

    async def test_import(self, ctx_with_db):
        ctx, _ = ctx_with_db
        data = json.dumps({"id": "imp1", "content": "imported"})
        result = json.loads(await memory(action="import", data=data, ctx=ctx))
        assert result["status"] == "imported"
        assert result["imported"] == 1

    async def test_import_no_data(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="import", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result


class TestMemoryStats:
    async def test_stats(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("test")
        result = json.loads(await memory(action="stats", ctx=ctx))
        assert result["total_memories"] == 1
        assert "embedding_model" in result
        assert "sync_enabled" in result

    async def test_stats_empty(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="stats", ctx=ctx))
        assert result["total_memories"] == 0


class TestMemoryRestore:
    async def test_restore(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("to archive and restore")
        db._conn.execute(
            "UPDATE memories SET last_accessed = datetime('now', '-100 days'), importance = 0.1 WHERE id = ?",
            (mid,),
        )
        db._conn.commit()
        db.archive_old_memories(days=90, importance_threshold=0.3)
        # Phase 1 soft-archive: row stays in memories with archived_at set.
        archived = db.get(mid)
        assert archived is not None
        assert archived["archived_at"] is not None

        result = json.loads(await memory(action="restore", memory_id=mid, ctx=ctx))
        assert result["status"] == "restored"
        restored = db.get(mid)
        assert restored is not None
        assert restored["archived_at"] is None

    async def test_restore_no_id(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="restore", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result

    async def test_restore_nonexistent(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await memory(action="restore", memory_id="fake123", ctx=ctx)
        )
        assert "error" in result


class TestMemoryArchived:
    async def test_archived_empty(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="archived", ctx=ctx))
        assert result["count"] == 0
        assert result["results"] == []

    async def test_archived_with_data(self, ctx_with_db):
        ctx, db = ctx_with_db
        mid = db.add("old memory")
        db._conn.execute(
            "UPDATE memories SET last_accessed = datetime('now', '-100 days'), importance = 0.1 WHERE id = ?",
            (mid,),
        )
        db._conn.commit()
        db.archive_old_memories(days=90, importance_threshold=0.3)

        result = json.loads(await memory(action="archived", ctx=ctx))
        assert result["count"] == 1
        assert result["results"][0]["id"] == mid


class TestMemoryConsolidate:
    async def test_consolidate_local_mode_error(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("mem1", category="tech")
        db.add("mem2", category="tech")
        # Default mode is local (no API keys)
        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.graph._has_llm_provider", return_value=False),
        ):
            mock_settings.resolve_provider_mode.return_value = "local"
            result = json.loads(await _handle_consolidate(ctx, "tech"))
        assert "error" in result
        assert "LLM" in result["error"]

    async def test_consolidate_no_category(self, ctx_with_db):
        ctx, _ = ctx_with_db
        with patch("mnemo_mcp.server.settings") as mock_settings:
            mock_settings.resolve_provider_mode.return_value = "sdk"
            result = json.loads(await memory(action="consolidate", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result


class TestMemoryUnknownAction:
    async def test_unknown_action(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="invalid", ctx=ctx))
        assert "error" in result
        assert "valid_actions" in result
        assert "add" in result["valid_actions"]
        assert "suggestion" in result
        assert "Common actions:" in result["suggestion"]


class TestConfigTool:
    async def test_status(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="status", ctx=ctx))
        assert "database" in result
        assert "embedding" in result
        assert "sync" in result
        assert "path" in result["database"]

    async def test_set_sync_folder_rejected(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(
                action="set",
                key="sync_folder",
                value="new-folder",
                ctx=ctx,
            )
        )
        assert "error" in result
        assert "valid_keys" in result

    async def test_set_sync_enabled(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(
                action="set",
                key="sync_enabled",
                value="true",
                ctx=ctx,
            )
        )
        assert result["status"] == "updated"

    async def test_set_invalid_key(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(
                action="set",
                key="invalid_key",
                value="x",
                ctx=ctx,
            )
        )
        assert "error" in result
        assert "valid_keys" in result

    async def test_set_missing_params(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="set", ctx=ctx))
        assert "error" in result
        assert "suggestion" in result

    async def test_unknown_action(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="invalid", ctx=ctx))
        assert "error" in result
        assert "valid_actions" in result
        assert "suggestion" in result
        assert "Common actions:" in result["suggestion"]

    async def test_models_action_removed(self, ctx_with_db):
        """The 'models' catalog-listing action no longer exists."""
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="models", ctx=ctx))
        assert "Unknown action 'models'" in result["error"]
        assert "models" not in result["valid_actions"]


class TestHelpTool:
    async def test_memory_topic(self):
        result = await help(topic="memory")
        assert "memory" in result.lower()
        assert len(result) > 100  # Should be substantial docs

    async def test_config_topic(self):
        result = await help(topic="config")
        assert "config" in result.lower()

    async def test_invalid_topic(self):
        result = json.loads(await help(topic="invalid"))
        assert "error" in result
        assert "valid_topics" in result


class TestDedupWarning:
    async def test_add_with_similar_dedup(self, ctx_with_db):
        """Cover lines 335-337: dedup_warning set from similar/duplicate result."""
        ctx, db = ctx_with_db
        # Add first memory
        db.add("Python is great for machine learning")
        # Add similar memory -- should trigger dedup warning
        with patch.object(
            db,
            "check_duplicate",
            return_value={"similar": True, "match_id": "abc", "score": 0.85},
        ):
            result = json.loads(
                await _handle_add(ctx, "Python is excellent for ML", None, None)
            )
        assert result["status"] == "saved"
        assert "dedup_warning" in result

    async def test_add_with_duplicate_dedup(self, ctx_with_db):
        """Cover line 334-335: dedup_warning set from duplicate result."""
        ctx, db = ctx_with_db
        with patch.object(
            db,
            "check_duplicate",
            return_value={"duplicate": True, "match_id": "abc", "score": 0.99},
        ):
            result = json.loads(await _handle_add(ctx, "exact duplicate", None, None))
        assert result["status"] == "saved"
        assert "dedup_warning" in result

    async def test_add_dedup_exception_ignored(self, ctx_with_db):
        """Cover lines 338-339: dedup exception is non-blocking."""
        ctx, db = ctx_with_db
        with patch.object(db, "check_duplicate", side_effect=RuntimeError("boom")):
            result = json.loads(await _handle_add(ctx, "test content", None, None))
        assert result["status"] == "saved"


class TestHandleAddErrors:
    async def test_add_unexpected_exception(self, ctx_with_db):
        """Cover lines 352-354: unexpected exception in db.add."""
        ctx, db = ctx_with_db
        with patch.object(db, "add", side_effect=RuntimeError("unexpected")):
            result = json.loads(await _handle_add(ctx, "test", None, None))
        assert "error" in result
        assert "Internal error" in result["error"]


class TestHandleUpdateErrors:
    async def test_update_unexpected_exception(self, ctx_with_db):
        """Cover lines 528-530: unexpected exception in db.update."""
        ctx, db = ctx_with_db
        mid = db.add("original")
        with patch.object(db, "update", side_effect=RuntimeError("unexpected")):
            result = json.loads(
                await _handle_update(ctx, mid, "new content", None, None, None, None)
            )
        assert "error" in result
        assert "Internal error" in result["error"]


class TestEnrichMemory:
    async def test_enrich_importance_error(self, ctx_with_db):
        """Cover lines 384-386: importance scoring error is non-blocking."""
        ctx, db = ctx_with_db
        mid = db.add("test memory")
        with patch(
            "mnemo_mcp.graph.score_importance",
            new_callable=AsyncMock,
            side_effect=RuntimeError("api error"),
        ):
            # Should not raise
            await _enrich_memory(db, mid, "test memory")

    async def test_enrich_entity_extraction(self, ctx_with_db):
        """Cover lines 391-403: entity extraction and linking."""
        ctx, db = ctx_with_db
        mid = db.add("Python is a programming language")
        mock_graph_data = {
            "entities": [
                {"name": "Python", "type": "technology"},
                {"name": "programming language", "type": "concept"},
            ],
            "relations": [
                {"source": "Python", "target": "programming language", "type": "is_a"}
            ],
        }
        with (
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                return_value=0.5,
            ),
            patch(
                "mnemo_mcp.graph.extract_entities",
                new_callable=AsyncMock,
                return_value=mock_graph_data,
            ),
            patch("mnemo_mcp.graph.upsert_entities", return_value=["e1", "e2"]),
            patch("mnemo_mcp.graph.create_relations"),
            patch("mnemo_mcp.graph.link_memory_entities"),
        ):
            await _enrich_memory(db, mid, "Python is a programming language")

    async def test_enrich_entity_extraction_error(self, ctx_with_db):
        """Cover lines 402-403: entity extraction error is non-blocking."""
        ctx, db = ctx_with_db
        mid = db.add("test")
        with (
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                return_value=0.5,
            ),
            patch(
                "mnemo_mcp.graph.extract_entities",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            await _enrich_memory(db, mid, "test")


class TestSearchRerankerAndGraph:
    async def test_search_with_reranker(self, ctx_with_db):
        """Cover lines 437-451: reranker reranks results."""
        ctx, db = ctx_with_db
        db.add("Python for AI")
        db.add("Python for web")
        db.add("Python for data")
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [(1, 0.95), (0, 0.85), (2, 0.70)]
        with patch("mnemo_mcp.reranker.get_reranker", return_value=mock_reranker):
            result = json.loads(await _handle_search(ctx, "Python", None, None, 5))
        assert result["reranked"] is True
        assert result["results"][0]["rerank_score"] == 0.95

    async def test_search_reranker_failure(self, ctx_with_db):
        """Cover line 451: reranker failure falls back to original order."""
        ctx, db = ctx_with_db
        db.add("Python for AI")
        db.add("Python for web")
        mock_reranker = MagicMock()
        mock_reranker.rerank.side_effect = RuntimeError("rerank failed")
        with patch("mnemo_mcp.reranker.get_reranker", return_value=mock_reranker):
            result = json.loads(await _handle_search(ctx, "Python", None, None, 5))
        assert result["reranked"] is False

    async def test_search_with_graph_boost(self, ctx_with_db):
        """Cover lines 463-468: graph boost marks related memories."""
        ctx, db = ctx_with_db
        db.add("Python for AI")
        mid2 = db.add("Python for web development")
        with patch("mnemo_mcp.graph.find_related_memory_ids", return_value=[mid2]):
            result = json.loads(await _handle_search(ctx, "Python", None, None, 5))
        # At least one result should have graph_related
        related = [r for r in result["results"] if r.get("graph_related")]
        assert len(related) >= 1

    async def test_search_graph_boost_error(self, ctx_with_db):
        """Cover lines 467-468: graph boost error is non-blocking."""
        ctx, db = ctx_with_db
        db.add("Python for AI")
        with patch(
            "mnemo_mcp.graph.find_related_memory_ids",
            side_effect=RuntimeError("graph error"),
        ):
            result = json.loads(await _handle_search(ctx, "Python", None, None, 5))
        assert result["count"] > 0


class TestConsolidate:
    async def test_consolidate_no_category_non_local(self, ctx_with_db):
        """Cover line 637-638: no category error when mode is not local."""
        ctx, db = ctx_with_db
        with patch("mnemo_mcp.server.settings") as mock_settings:
            mock_settings.resolve_provider_mode.return_value = "sdk"
            result = json.loads(await _handle_consolidate(ctx, None))
        assert "error" in result
        assert "category is required" in result["error"]
        assert "suggestion" in result

    async def test_consolidate_too_few_memories(self, ctx_with_db):
        """Cover lines 640-644: less than 2 memories in category."""
        ctx, db = ctx_with_db
        db.add("only one", category="tech")
        with patch("mnemo_mcp.server.settings") as mock_settings:
            mock_settings.resolve_provider_mode.return_value = "sdk"
            result = json.loads(await _handle_consolidate(ctx, "tech"))
        assert "error" in result
        assert "at least 2" in result["error"]

    async def test_consolidate_success(self, ctx_with_db):
        """Cover lines 646-688: successful consolidation with LLM."""
        ctx, db = ctx_with_db
        db.add("Python is great", category="tech")
        db.add("Python is awesome", category="tech")

        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch(
                "mnemo_mcp.llm.acomplete",
                new_callable=AsyncMock,
                return_value="Python is excellent",
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gpt-4o,gemini-flash"
            result = json.loads(await _handle_consolidate(ctx, "tech"))

        assert result["status"] == "consolidated"
        assert result["category"] == "tech"
        assert result["original_count"] == 2
        assert result["summary"] == "Python is excellent"

    async def test_consolidate_llm_error(self, ctx_with_db):
        """Cover lines 689-690: LLM error during consolidation."""
        ctx, db = ctx_with_db
        db.add("mem1", category="tech")
        db.add("mem2", category="tech")
        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch(
                "mnemo_mcp.llm.acomplete",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM error"),
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gpt-4o"
            result = json.loads(await _handle_consolidate(ctx, "tech"))
        assert "error" in result
        assert "Consolidation failed" in result["error"]


class TestConfigSet:
    async def test_set_sync_interval(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(action="set", key="sync_interval", value="600", ctx=ctx)
        )
        assert result["status"] == "updated"

    async def test_set_log_level(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(action="set", key="log_level", value="DEBUG", ctx=ctx)
        )
        assert result["status"] == "updated"

    async def test_set_invalid_log_level(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(action="set", key="log_level", value="INVALID", ctx=ctx)
        )
        assert "error" in result
        assert "valid_levels" in result


class TestMain:
    def test_main_invalid_log_level(self):
        """Cover line 1001: invalid log level falls back to WARNING.

        main() in stdio mode runs FastMCP stdio server directly (no bridge).
        """
        from mnemo_mcp import server as server_mod

        with (
            patch("mnemo_mcp.server.logger"),
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch.object(server_mod.mcp, "run") as mock_run,
            patch.dict(os.environ, {"MCP_TRANSPORT": "stdio"}),
        ):
            mock_settings.log_level = "BOGUS"
            main()
            mock_run.assert_called_once_with(transport="stdio")


class TestPrompts:
    def test_save_summary(self):
        result = save_summary("This conversation was about Python")
        assert "Python" in result
        assert "memory" in result.lower()

    def test_recall_context(self):
        result = recall_context("machine learning")
        assert "machine learning" in result
        assert "search" in result.lower()


class TestServerVersion:
    def test_serverinfo_version_matches_package(self):
        """initialize's serverInfo.version reports the package version,
        not the MCP SDK version."""
        from mnemo_mcp.server import __version__, mcp

        init_opts = mcp._mcp_server.create_initialization_options()
        assert init_opts.server_version == __version__


class TestMaybeRegisterCustomEmbed:
    """BYO local embedding model registration (no model download)."""

    def test_builtin_id_skips_registration(self):
        import qwen3_embed

        with patch.object(qwen3_embed.TextEmbedding, "add_custom_model") as mock_add:
            _maybe_register_custom_embed("n24q02m/Qwen3-Embedding-0.6B-ONNX")
            mock_add.assert_not_called()

    def test_custom_id_registers_with_dim_and_pooling(self):
        import qwen3_embed
        from qwen3_embed.common.model_description import PoolingType

        with patch.object(qwen3_embed.TextEmbedding, "add_custom_model") as mock_add:
            with patch("mnemo_mcp.server.settings") as mock_settings:
                mock_settings.local_embedding_dim = 1024
                mock_settings.resolve_embedding_dims.return_value = 768
                mock_settings.local_embedding_model_file = "onnx/model.onnx"
                mock_settings.local_embedding_pooling = "CLS"
                mock_settings.local_embedding_normalize = True

                _maybe_register_custom_embed("Org/custom-embed")

            mock_add.assert_called_once()
            description = mock_add.call_args.args[0]
            assert description.model == "Org/custom-embed"
            assert description.dim == 1024
            assert mock_add.call_args.kwargs["pooling"] == PoolingType.CLS
            assert mock_add.call_args.kwargs["normalization"] is True

    def test_reregistration_is_graceful(self):
        """A second register (backend re-init) swallows 'already registered'."""
        import qwen3_embed

        with patch.object(
            qwen3_embed.TextEmbedding,
            "add_custom_model",
            side_effect=ValueError("Model Org/custom-embed is already registered"),
        ):
            with patch("mnemo_mcp.server.settings") as mock_settings:
                mock_settings.local_embedding_dim = 768
                mock_settings.resolve_embedding_dims.return_value = 768
                mock_settings.local_embedding_model_file = "onnx/model.onnx"
                mock_settings.local_embedding_pooling = "CLS"
                mock_settings.local_embedding_normalize = True

                # Must not raise -- re-init reuses the existing registration.
                _maybe_register_custom_embed("Org/custom-embed")


class TestMaybeRegisterCustomRerank:
    """BYO local reranker registration (no model download)."""

    def test_builtin_id_skips_registration(self):
        import qwen3_embed

        with patch.object(qwen3_embed.TextCrossEncoder, "add_custom_model") as mock_add:
            _maybe_register_custom_rerank("n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo")
            mock_add.assert_not_called()

    def test_custom_id_registers_with_model_file(self):
        import qwen3_embed

        with patch.object(qwen3_embed.TextCrossEncoder, "add_custom_model") as mock_add:
            with patch("mnemo_mcp.server.settings") as mock_settings:
                mock_settings.local_rerank_model_file = "onnx/model_quantized.onnx"

                _maybe_register_custom_rerank("Org/custom-reranker")

            mock_add.assert_called_once()
            description = mock_add.call_args.args[0]
            assert description.model == "Org/custom-reranker"
            assert description.model_file == "onnx/model_quantized.onnx"
            assert description.sources.hf == "Org/custom-reranker"
