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

    def test_schema_has_provider_fields_only(self):
        """Relay form scope: 4 API key provider fields ONLY.

        S3 + passphrase are operator env config (docker spawn), NOT
        per-user relay fields. See docs/passport.md for the runbook
        and relay_schema.py module docstring for the deployment-mode
        XOR semantics.
        """
        fields = RELAY_SCHEMA["fields"]
        assert len(fields) == 4
        keys = [f["key"] for f in fields]
        assert all(k.endswith("_API_KEY") for k in keys), (
            f"non-API-key fields in relay form: {keys}"
        )

    def test_schema_provider_keys(self):
        keys = [f["key"] for f in RELAY_SCHEMA["fields"]]
        assert "JINA_AI_API_KEY" in keys
        assert "GEMINI_API_KEY" in keys
        assert "OPENAI_API_KEY" in keys
        assert "COHERE_API_KEY" in keys

    def test_all_fields_optional(self):
        for f in RELAY_SCHEMA["fields"]:
            assert f.get("required") is False

    def test_provider_fields_have_help_urls(self):
        """Phase 1 provider fields keep their helpUrl pointing at signup pages.

        Phase 2 S3 + passphrase fields legitimately have no single help URL
        (S3 spans AWS/R2/B2/MinIO; passphrase is user-chosen) so we only
        require the helpUrl on the original 4 provider fields.
        """
        provider_keys = {
            "JINA_AI_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "COHERE_API_KEY",
        }
        for f in RELAY_SCHEMA["fields"]:
            if f["key"] not in provider_keys:
                continue
            assert "helpUrl" in f
            assert f["helpUrl"].startswith("https://")

    def test_capability_info_present(self):
        assert "capabilityInfo" in RELAY_SCHEMA
        labels = [c["label"] for c in RELAY_SCHEMA["capabilityInfo"]]
        assert "Embedding" in labels
        assert "Reranking" in labels
        assert "LLM" in labels
