"""Tests for relay_schema module."""

from mnemo_mcp.relay_schema import RELAY_SCHEMA


class TestRelaySchema:
    """Test relay config schema definition."""

    def test_schema_has_server_name(self):
        assert RELAY_SCHEMA["server"] == "mnemo-mcp"

    def test_schema_has_display_name(self):
        assert RELAY_SCHEMA["displayName"] == "Mnemo MCP"

    def test_schema_has_description(self):
        assert "description" in RELAY_SCHEMA
        assert len(RELAY_SCHEMA["description"]) > 0

    def test_schema_has_flat_fields(self):
        """Schema uses flat fields structure (not modes)."""
        assert "fields" in RELAY_SCHEMA
        assert "modes" not in RELAY_SCHEMA

    def test_schema_has_four_provider_fields(self):
        fields = RELAY_SCHEMA["fields"]
        assert len(fields) == 4

    def test_schema_provider_keys(self):
        keys = [f["key"] for f in RELAY_SCHEMA["fields"]]
        assert "JINA_AI_API_KEY" in keys
        assert "GEMINI_API_KEY" in keys
        assert "OPENAI_API_KEY" in keys
        assert "COHERE_API_KEY" in keys

    def test_all_fields_optional(self):
        for f in RELAY_SCHEMA["fields"]:
            assert f.get("required") is False

    def test_fields_have_help_urls(self):
        for f in RELAY_SCHEMA["fields"]:
            assert "helpUrl" in f
            assert f["helpUrl"].startswith("https://")

    def test_capability_info_present(self):
        assert "capabilityInfo" in RELAY_SCHEMA
        labels = [c["label"] for c in RELAY_SCHEMA["capabilityInfo"]]
        assert "Embedding" in labels
        assert "Reranking" in labels
        assert "LLM" in labels
