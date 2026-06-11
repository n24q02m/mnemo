"""Tests for mnemo_mcp.graph -- entity extraction, relations, graph traversal."""

from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.graph import (
    _has_llm_provider,
    create_relations,
    extract_entities,
    find_related_memory_ids,
    link_memory_entities,
    score_importance,
    upsert_entities,
)


class TestHasLlmProvider:
    def test_no_keys(self, monkeypatch):
        for key in (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "XAI_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        assert _has_llm_provider() is False

    def test_gemini_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        assert _has_llm_provider() is True

    def test_openai_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        assert _has_llm_provider() is True

    def test_anthropic_key_only(self, monkeypatch):
        """ANTHROPIC_API_KEY alone enables LLM enrichment (litellm path)."""
        for key in (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "XAI_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        assert _has_llm_provider() is True


class TestExtractEntities:
    async def test_returns_none_in_local_mode_no_keys(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch("mnemo_mcp.graph._has_llm_provider", return_value=False),
        ):
            mock_settings.resolve_provider_mode.return_value = "local"
            result = await extract_entities("Python is a programming language")
            assert result is None

    async def test_success_with_llm(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value='{"entities": [{"name": "Python", "type": "tool"}], "relations": []}',
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("Python is a programming language")
            assert result is not None
            assert "entities" in result
            assert result["entities"][0]["name"] == "Python"

    async def test_handles_llm_error(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is None

    async def test_handles_invalid_json(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value="not json",
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is None

    async def test_handles_missing_entities_key(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value='{"relations": []}',
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is None

    async def test_proxy_mode_calls_llm(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value='{"entities": [{"name": "Test", "type": "concept"}], "relations": []}',
            ) as mock_llm,
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is not None
            mock_llm.assert_called_once()

    async def test_llm_completion_gemini_bare_name_gets_prefixed(self):
        """Bare gemini model is prefixed to litellm 'gemini/...' form."""
        from types import SimpleNamespace

        mock = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="gemini response"))
                ]
            )
        )
        with patch("mcp_core.llm.acompletion", mock):
            from mnemo_mcp.graph import _llm_completion

            res = await _llm_completion(
                "gemini-pro", [{"role": "user", "content": "hi"}]
            )
            assert res == "gemini response"
            assert mock.call_args.kwargs["model"] == "gemini/gemini-pro"

    async def test_llm_completion_slash_form_passes_through(self):
        """A 'provider/model' string is passed to litellm unchanged."""
        from types import SimpleNamespace

        mock = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="openai response"))
                ]
            )
        )
        with patch("mcp_core.llm.acompletion", mock):
            from mnemo_mcp.graph import _llm_completion

            res = await _llm_completion(
                "openai/gpt-4", [{"role": "user", "content": "hi"}]
            )
            assert res == "openai response"
            assert mock.call_args.kwargs["model"] == "openai/gpt-4"

    async def test_llm_completion_response_format_forwarded(self):
        """response_format is forwarded to litellm only when provided."""
        from types import SimpleNamespace

        mock = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
            )
        )
        with patch("mcp_core.llm.acompletion", mock):
            from mnemo_mcp.graph import _llm_completion

            await _llm_completion(
                "gemini/gemini-3-flash-preview",
                [{"role": "user", "content": "hi"}],
                response_format={"type": "json_object"},
            )
            assert mock.call_args.kwargs["response_format"] == {"type": "json_object"}

    async def test_resolve_llm_model_custom(self):
        from mnemo_mcp.graph import _resolve_llm_model

        class MockSettings:
            llm_models = " custom/model , other/model "

        assert _resolve_llm_model(MockSettings()) == "custom/model"

    async def test_resolve_llm_model_empty(self):
        from mnemo_mcp.graph import _resolve_llm_model

        class MockSettings:
            llm_models = ""

        assert _resolve_llm_model(MockSettings()) == "gemini/gemini-3-flash-preview"

    async def test_resolve_llm_model_equals_form_normalised(self):
        """=-form first entry is normalised to slash form for litellm."""
        from mnemo_mcp.graph import _resolve_llm_model

        class MockSettings:
            llm_models = "gemini=gemini-2.0-flash,openai=gpt-5-mini"

        assert _resolve_llm_model(MockSettings()) == "gemini/gemini-2.0-flash"

    async def test_resolve_llm_model_slash_form_unchanged(self):
        """Slash-form first entry is passed through unchanged."""
        from mnemo_mcp.graph import _resolve_llm_model

        class MockSettings:
            llm_models = "openai/gpt-5.4-mini,gemini/gemini-3-flash-preview"

        assert _resolve_llm_model(MockSettings()) == "openai/gpt-5.4-mini"

    async def test_equals_form_reaches_litellm_as_slash(self):
        """End-to-end: =-form resolved model reaches acompletion as provider/model."""
        from types import SimpleNamespace

        from mnemo_mcp.graph import _litellm_model, _resolve_llm_model

        class MockSettings:
            llm_models = "openai=gpt-5-mini"

        resolved = _resolve_llm_model(MockSettings())
        assert resolved == "openai/gpt-5-mini"
        # _litellm_model must NOT double-prefix an already-slash model.
        assert _litellm_model(resolved) == "openai/gpt-5-mini"

        mock = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )
        )
        with patch("mcp_core.llm.acompletion", mock):
            from mnemo_mcp.graph import _llm_completion

            await _llm_completion(resolved, [{"role": "user", "content": "hi"}])
        assert mock.call_args.kwargs["model"] == "openai/gpt-5-mini"


class TestScoreImportance:
    async def test_returns_default_in_local_mode_no_keys(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch("mnemo_mcp.graph._has_llm_provider", return_value=False),
        ):
            mock_settings.resolve_provider_mode.return_value = "local"
            score = await score_importance("some content")
            assert score == 0.5

    async def test_success_with_llm(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value="0.8",
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            score = await score_importance("critical information")
            assert score == 0.8

    async def test_clamps_to_range(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value="1.5",
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            score = await score_importance("test")
            assert score == 1.0

    async def test_clamps_negative(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value="-0.3",
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            score = await score_importance("test")
            assert score == 0.0

    async def test_handles_error(self):
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            score = await score_importance("test")
            assert score == 0.5


class TestUpsertEntities:
    def test_inserts_new_entities(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [
            {"name": "Python", "type": "tool"},
            {"name": "Alice", "type": "person"},
        ]
        ids = upsert_entities(conn, entities)
        assert len(ids) == 2
        # Verify in DB
        row = conn.execute(
            "SELECT * FROM memory_entities WHERE name = ?", ("Python",)
        ).fetchone()
        assert row is not None
        assert row["entity_type"] == "tool"

    def test_updates_existing_entity(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [{"name": "Python", "type": "tool"}]
        ids1 = upsert_entities(conn, entities)
        ids2 = upsert_entities(conn, entities)
        assert ids1[0] == ids2[0]  # Same ID

    def test_duplicate_entities_in_same_batch(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [
            {"name": "Python", "type": "tool"},
            {"name": "Python", "type": "tool"},
        ]
        ids = upsert_entities(conn, entities)
        assert len(ids) == 2
        assert ids[0] == ids[1]

    def test_skips_empty_name(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [{"name": "", "type": "tool"}, {"name": "Valid", "type": "concept"}]
        ids = upsert_entities(conn, entities)
        assert len(ids) == 1

    def test_defaults_to_concept_type(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [{"name": "SomeThing"}]
        ids = upsert_entities(conn, entities)
        assert len(ids) == 1
        row = conn.execute(
            "SELECT entity_type FROM memory_entities WHERE id = ?", (ids[0],)
        ).fetchone()
        assert row["entity_type"] == "concept"

    def test_upsert_entities_empty_list(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        assert upsert_entities(conn, []) == []


class TestCreateRelations:
    def test_creates_relation(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [
            {"name": "Alice", "type": "person"},
            {"name": "Project X", "type": "project"},
        ]
        ids = upsert_entities(conn, entities)
        name_to_id = {"Alice": ids[0], "Project X": ids[1]}

        relations = [{"source": "Alice", "target": "Project X", "type": "works_on"}]
        create_relations(conn, relations, name_to_id)

        row = conn.execute("SELECT * FROM memory_edges").fetchone()
        assert row is not None
        assert row["relation_type"] == "works_on"

    def test_skips_self_relation(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [{"name": "Alice", "type": "person"}]
        ids = upsert_entities(conn, entities)
        name_to_id = {"Alice": ids[0]}

        relations = [{"source": "Alice", "target": "Alice", "type": "related_to"}]
        create_relations(conn, relations, name_to_id)

        count = conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
        assert count == 0

    def test_skips_missing_entities(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        name_to_id = {"Alice": "id1"}
        relations = [{"source": "Alice", "target": "Bob", "type": "related_to"}]
        create_relations(conn, relations, name_to_id)

        count = conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
        assert count == 0

    def test_no_duplicate_relations(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [
            {"name": "A", "type": "concept"},
            {"name": "B", "type": "concept"},
        ]
        ids = upsert_entities(conn, entities)
        name_to_id = {"A": ids[0], "B": ids[1]}

        relations = [{"source": "A", "target": "B", "type": "related_to"}]
        create_relations(conn, relations, name_to_id)
        create_relations(conn, relations, name_to_id)  # Duplicate

        count = conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
        assert count == 1

    def test_duplicate_relations_in_same_batch(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        entities = [{"name": "A"}, {"name": "B"}]
        ids = upsert_entities(conn, entities)
        name_to_id = {"A": ids[0], "B": ids[1]}
        relations = [
            {"source": "A", "target": "B", "type": "related_to"},
            {"source": "A", "target": "B", "type": "related_to"},
        ]
        create_relations(conn, relations, name_to_id)
        count = conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
        assert count == 1


class TestLinkMemoryEntities:
    def test_links_memory_to_entities(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        mid = tmp_db.add("test content")
        entities = [{"name": "Python", "type": "tool"}]
        eids = upsert_entities(conn, entities)
        link_memory_entities(conn, mid, eids)

        row = conn.execute(
            "SELECT * FROM memory_entity_links WHERE memory_id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row["entity_id"] == eids[0]

    def test_ignores_duplicate_links(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        mid = tmp_db.add("test content")
        entities = [{"name": "Python", "type": "tool"}]
        eids = upsert_entities(conn, entities)
        link_memory_entities(conn, mid, eids)
        link_memory_entities(conn, mid, eids)  # Duplicate

        count = conn.execute(
            "SELECT COUNT(*) FROM memory_entity_links WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
        assert count == 1

    def test_empty_entity_ids(self, tmp_db: MemoryDB):
        """No-op for empty entity_ids list."""
        conn = tmp_db._conn
        mid = tmp_db.add("test")
        link_memory_entities(conn, mid, [])
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_entity_links WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
        assert count == 0

    def test_exception_is_caught_and_logged(self):
        """Exception during linking is caught and logged with details."""
        conn = MagicMock()
        conn.executemany.side_effect = Exception("DB error")
        with patch("mnemo_mcp.graph.logger") as mock_logger:
            # Should not raise
            link_memory_entities(conn, "fake-id", ["eid1", "eid2"])
            # Verify error was actually logged
            assert mock_logger.debug.called
            args, _ = mock_logger.debug.call_args
            assert "Failed to link memory entities" in args[0]
            assert "DB error" in args[0]


class TestFindRelatedMemoryIds:
    def test_finds_related_via_shared_entity(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        mid1 = tmp_db.add("Python is great")
        mid2 = tmp_db.add("Python frameworks")

        entities = [{"name": "Python", "type": "tool"}]
        eids = upsert_entities(conn, entities)
        link_memory_entities(conn, mid1, eids)
        link_memory_entities(conn, mid2, eids)

        related = find_related_memory_ids(conn, mid1)
        assert mid2 in related

    def test_returns_empty_for_unlinked(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        mid = tmp_db.add("isolated memory")
        related = find_related_memory_ids(conn, mid)
        assert related == []

    def test_excludes_self(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        mid = tmp_db.add("self test")
        entities = [{"name": "Test", "type": "concept"}]
        eids = upsert_entities(conn, entities)
        link_memory_entities(conn, mid, eids)

        related = find_related_memory_ids(conn, mid)
        assert mid not in related

    def test_multi_hop_relations(self, tmp_db: MemoryDB):
        """Test that graph traversal follows relations across hops."""
        conn = tmp_db._conn
        mid1 = tmp_db.add("Memory about A")
        mid2 = tmp_db.add("Memory about B")

        ent_a = upsert_entities(conn, [{"name": "A", "type": "concept"}])
        ent_b = upsert_entities(conn, [{"name": "B", "type": "concept"}])
        ent_c = upsert_entities(conn, [{"name": "C", "type": "concept"}])

        link_memory_entities(conn, mid1, ent_a)
        link_memory_entities(conn, mid2, ent_c)

        # A -> B -> C via relations
        name_to_id = {"A": ent_a[0], "B": ent_b[0], "C": ent_c[0]}
        create_relations(
            conn,
            [
                {"source": "A", "target": "B", "type": "related_to"},
                {"source": "B", "target": "C", "type": "related_to"},
            ],
            name_to_id,
        )

        related = find_related_memory_ids(conn, mid1, max_depth=3)
        assert mid2 in related
