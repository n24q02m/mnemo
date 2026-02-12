"""Tests for mnemo_mcp.server — MCP tools, prompts, resources."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import config, help, memory, recall_context, save_summary


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


class TestMemorySearch:
    async def test_search(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("Python is great for AI and machine learning")
        result = json.loads(await memory(action="search", query="Python AI", ctx=ctx))
        assert result["count"] > 0
        assert result["semantic"] is False

    async def test_search_no_query(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="search", ctx=ctx))
        assert "error" in result

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
        db.add("mem1")
        db.add("mem2")
        result = json.loads(await memory(action="list", ctx=ctx))
        assert result["count"] == 2

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


class TestMemoryUnknownAction:
    async def test_unknown_action(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await memory(action="invalid", ctx=ctx))
        assert "error" in result
        assert "valid_actions" in result
        assert "add" in result["valid_actions"]


class TestConfigTool:
    async def test_status(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="status", ctx=ctx))
        assert "database" in result
        assert "embedding" in result
        assert "sync" in result
        assert "path" in result["database"]

    async def test_set_valid_key(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(
                action="set",
                key="sync_folder",
                value="new-folder",
                ctx=ctx,
            )
        )
        assert result["status"] == "updated"

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

    async def test_unknown_action(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="invalid", ctx=ctx))
        assert "error" in result
        assert "valid_actions" in result


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


class TestPrompts:
    def test_save_summary(self):
        result = save_summary("This conversation was about Python")
        assert "Python" in result
        assert "memory" in result.lower()

    def test_recall_context(self):
        result = recall_context("machine learning")
        assert "machine learning" in result
        assert "search" in result.lower()
