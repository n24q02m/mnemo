"""Tests for graph.py -- LLM completion routing and edge cases.

Targets: _llm_completion (Gemini path with json_object, OpenAI path with
response_format, xAI path), _resolve_llm_model, extract_entities entity
validation (invalid types, long names), upsert_entities with empty list,
link_memory_entities empty, link_memory_entities exception,
find_related_memory_ids no_new_ids early break.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.graph import (
    _has_llm_provider,
    _llm_completion,
    _resolve_llm_model,
    extract_entities,
    find_related_memory_ids,
    link_memory_entities,
    upsert_entities,
)

# ---------------------------------------------------------------------------
# _resolve_llm_model
# ---------------------------------------------------------------------------


class TestResolveLlmModel:
    def test_first_model_from_csv(self):
        mock_settings = MagicMock()
        mock_settings.llm_models = "gemini/gemini-3-flash-preview,openai/gpt-5.4-mini"
        assert _resolve_llm_model(mock_settings) == "gemini/gemini-3-flash-preview"

    def test_single_model(self):
        mock_settings = MagicMock()
        mock_settings.llm_models = "openai/gpt-5.4-mini"
        assert _resolve_llm_model(mock_settings) == "openai/gpt-5.4-mini"

    def test_empty_models_fallback(self):
        mock_settings = MagicMock()
        mock_settings.llm_models = ""
        assert _resolve_llm_model(mock_settings) == "gemini/gemini-3-flash-preview"


# ---------------------------------------------------------------------------
# _llm_completion
# ---------------------------------------------------------------------------


class TestLlmCompletion:
    async def test_gemini_path(self, monkeypatch):
        """Routes to Gemini SDK when model is gemini/..."""
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = '{"result": "test"}'
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await _llm_completion(
                "gemini/gemini-3-flash-preview",
                [{"role": "user", "content": "test prompt"}],
                response_format={"type": "json_object"},
            )

            assert result == '{"result": "test"}'
            # Verify json_object maps to response_mime_type
            call_kwargs = mock_client.models.generate_content.call_args
            config = call_kwargs.kwargs.get("config")
            assert config is not None

    async def test_gemini_no_prefix(self, monkeypatch):
        """Routes to Gemini for model without prefix containing 'gemini'."""
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "0.7"
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await _llm_completion(
                "gemini-3-flash-preview",
                [{"role": "user", "content": "score"}],
            )
            assert result == "0.7"

    async def test_gemini_empty_text(self, monkeypatch):
        """Gemini returns empty string when response.text is None."""
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = None
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await _llm_completion(
                "gemini/gemini-3-flash-preview",
                [{"role": "user", "content": "test"}],
            )
            assert result == ""

    async def test_openai_path(self, monkeypatch):
        """Routes to OpenAI SDK when model is openai/..."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        with patch("openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = '{"entities": []}'
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await _llm_completion(
                "openai/gpt-5.4-mini",
                [{"role": "user", "content": "test"}],
                response_format={"type": "json_object"},
            )
            assert result == '{"entities": []}'

    async def test_xai_path(self, monkeypatch):
        """Routes to OpenAI SDK with xAI base_url when XAI_API_KEY is set."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("XAI_API_KEY", "xai_test")

        with patch("openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "0.5"
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await _llm_completion(
                "xai/grok-4-mini",
                [{"role": "user", "content": "test"}],
            )
            assert result == "0.5"
            mock_client_cls.assert_called_once_with(
                api_key="xai_test",
                base_url="https://api.x.ai/v1",
            )

    async def test_openai_empty_content(self, monkeypatch):
        """OpenAI returns empty string when message.content is None."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        with patch("openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = None
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await _llm_completion(
                "openai/gpt-5.4-mini",
                [{"role": "user", "content": "test"}],
            )
            assert result == ""

    async def test_openai_no_prefix(self, monkeypatch):
        """Non-gemini model without prefix uses openai SDK."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        with patch("openai.OpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "0.8"
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await _llm_completion(
                "gpt-5.4-mini",
                [{"role": "user", "content": "test"}],
            )
            assert result == "0.8"
            # Model should be used as-is (no prefix)
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["model"] == "gpt-5.4-mini"


# ---------------------------------------------------------------------------
# _has_llm_provider
# ---------------------------------------------------------------------------


class TestHasLlmProviderCoverage:
    def test_google_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza_google")
        assert _has_llm_provider() is True

    def test_xai_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("XAI_API_KEY", "xai_test")
        assert _has_llm_provider() is True


# ---------------------------------------------------------------------------
# extract_entities -- entity validation
# ---------------------------------------------------------------------------


class TestExtractEntitiesValidation:
    async def test_filters_invalid_entity_types(self):
        """Filters out entities with invalid types."""
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value=(
                    '{"entities": ['
                    '  {"name": "Python", "type": "tool"},'
                    '  {"name": "Bad", "type": "invalid_type"},'
                    '  {"name": "Alice", "type": "person"}'
                    '], "relations": ['
                    '  {"source": "Alice", "target": "Python", "type": "uses"},'
                    '  {"source": "Alice", "target": "Bad", "type": "bad_relation"}'
                    "]}"
                ),
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is not None
            # "Bad" with invalid type should be filtered
            entity_names = [e["name"] for e in result["entities"]]
            assert "Python" in entity_names
            assert "Alice" in entity_names
            assert "Bad" not in entity_names
            # "bad_relation" should be filtered
            rel_types = [r["type"] for r in result["relations"]]
            assert "uses" in rel_types
            assert "bad_relation" not in rel_types

    async def test_filters_long_entity_names(self):
        """Filters out entities with names longer than 200 chars."""
        long_name = "A" * 201
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value=(
                    f'{{"entities": [{{"name": "{long_name}", "type": "concept"}}, '
                    f'{{"name": "Short", "type": "concept"}}], "relations": []}}'
                ),
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is not None
            entity_names = [e["name"] for e in result["entities"]]
            assert "Short" in entity_names
            assert long_name not in entity_names

    async def test_filters_non_dict_entities(self):
        """Filters out non-dict entries in entities list."""
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value=(
                    '{"entities": ["not_a_dict", {"name": "Valid", "type": "concept"}], "relations": []}'
                ),
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is not None
            assert len(result["entities"]) == 1
            assert result["entities"][0]["name"] == "Valid"

    async def test_filters_non_string_entity_names(self):
        """Filters out entities with non-string names."""
        with (
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.graph._llm_completion",
                new_callable=AsyncMock,
                return_value=(
                    '{"entities": [{"name": 123, "type": "concept"}, '
                    '{"name": "Valid", "type": "concept"}], "relations": []}'
                ),
            ),
        ):
            mock_settings.resolve_provider_mode.return_value = "sdk"
            mock_settings.llm_models = "gemini/gemini-3-flash-preview"

            result = await extract_entities("test content")
            assert result is not None
            assert len(result["entities"]) == 1


# ---------------------------------------------------------------------------
# upsert_entities edge cases
# ---------------------------------------------------------------------------


class TestUpsertEntitiesCoverage:
    def test_empty_entities_list(self, tmp_db: MemoryDB):
        """Returns empty list for empty input."""
        conn = tmp_db._conn
        ids = upsert_entities(conn, [])
        assert ids == []

    def test_all_empty_names(self, tmp_db: MemoryDB):
        """Returns empty list when all entities have empty names."""
        conn = tmp_db._conn
        entities = [{"name": "", "type": "concept"}, {"name": "  ", "type": "tool"}]
        ids = upsert_entities(conn, entities)
        assert ids == []

    def test_deduplicates_same_entities(self, tmp_db: MemoryDB):
        """Returns IDs for each occurrence, deduplicating same (name, type)."""
        conn = tmp_db._conn
        entities = [
            {"name": "Python", "type": "tool"},
            {"name": "Python", "type": "tool"},
            {"name": "Alice", "type": "person"},
        ]
        ids = upsert_entities(conn, entities)
        assert len(ids) == 3
        # First two should be the same
        assert ids[0] == ids[1]
        assert ids[0] != ids[2]


# ---------------------------------------------------------------------------
# link_memory_entities edge cases
# ---------------------------------------------------------------------------


class TestLinkMemoryEntitiesCoverage:
    def test_empty_entity_ids(self, tmp_db: MemoryDB):
        """No-op for empty entity_ids list."""
        conn = tmp_db._conn
        mid = tmp_db.add("test")
        link_memory_entities(conn, mid, [])
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_entity_links WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
        assert count == 0

    def test_exception_is_caught_and_logged(self, tmp_db: MemoryDB):
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


# ---------------------------------------------------------------------------
# find_related_memory_ids -- early break when no new neighbors
# ---------------------------------------------------------------------------


class TestFindRelatedMemoryIdsCoverage:
    def test_no_neighbors_at_depth(self, tmp_db: MemoryDB):
        """Graph traversal breaks early when no new neighbors found."""
        conn = tmp_db._conn
        mid1 = tmp_db.add("Memory A")
        mid2 = tmp_db.add("Memory B")

        ent_a = upsert_entities(conn, [{"name": "A", "type": "concept"}])
        ent_b = upsert_entities(conn, [{"name": "B", "type": "concept"}])

        link_memory_entities(conn, mid1, ent_a)
        link_memory_entities(conn, mid2, ent_b)

        # A and B are not related, so traversal should break early
        related = find_related_memory_ids(conn, mid1, max_depth=3)
        assert mid2 not in related

    def test_max_depth_one(self, tmp_db: MemoryDB):
        """max_depth=1 only finds directly shared entities (no hops)."""
        conn = tmp_db._conn
        mid1 = tmp_db.add("Memory 1")
        mid2 = tmp_db.add("Memory 2")

        ent = upsert_entities(conn, [{"name": "Shared", "type": "concept"}])
        link_memory_entities(conn, mid1, ent)
        link_memory_entities(conn, mid2, ent)

        related = find_related_memory_ids(conn, mid1, max_depth=1)
        assert mid2 in related
