"""Coverage tests for ``temporal.extract`` validation edge cases."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from mnemo_mcp.temporal.extract import (
    _validate_entities,
    _validate_relations,
    _validate_supersedes,
    extract_entities,
)


class TestValidationEdgeCases:
    def test_validate_entities_rejects_non_list(self):
        assert _validate_entities("not a list") == []
        assert _validate_entities(None) == []
        assert _validate_entities({"k": "v"}) == []

    def test_validate_entities_rejects_oversized_name(self):
        long_name = "x" * 250
        result = _validate_entities([{"name": long_name, "type": "tool"}])
        assert result == []

    def test_validate_entities_rejects_non_dict_items(self):
        result = _validate_entities([{"name": "OK", "type": "tool"}, "not a dict", 42])
        assert len(result) == 1
        assert result[0]["name"] == "OK"

    def test_validate_relations_rejects_non_list(self):
        assert _validate_relations("not a list") == []

    def test_validate_relations_rejects_non_dict_items(self):
        result = _validate_relations(["not a dict"])
        assert result == []

    def test_validate_relations_rejects_blank_source_or_target(self):
        result = _validate_relations(
            [
                {"source": "", "target": "T", "type": "uses"},
                {"source": "S", "target": "", "type": "uses"},
                {"source": "S", "target": "T", "type": "uses"},
            ]
        )
        assert len(result) == 1

    def test_validate_supersedes_rejects_non_list(self):
        assert _validate_supersedes("not a list") == []

    def test_validate_supersedes_accepts_old_id_alias(self):
        # Both keys old_fact_id and old_id are accepted.
        result = _validate_supersedes([{"old_id": "abc", "confidence": 0.9}])
        assert result == [{"old_fact_id": "abc", "confidence": 0.9}]

    def test_validate_supersedes_rejects_non_dict_items(self):
        assert _validate_supersedes(["not a dict"]) == []

    def test_validate_supersedes_rejects_missing_old_id(self):
        result = _validate_supersedes([{"confidence": 0.9}])
        assert result == []


class TestExtractEntitiesNonDictResponse:
    async def test_response_not_dict(self):
        # call_llm returns a JSON list (not dict).
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=json.dumps(["not", "a", "dict"]),
        ):
            result = await extract_entities("text")
            assert result is None
