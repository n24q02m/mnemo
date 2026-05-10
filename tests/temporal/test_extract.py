"""Tests for ``mnemo_mcp.temporal.extract`` -- LLM-backed entity extraction.

Verifies the Phase 3 port to :func:`mnemo_mcp.llm.call_llm`:

- Returns ``None`` when no LLM provider is available (``call_llm`` returns
  ``None``).
- Returns parsed dict when ``call_llm`` returns valid JSON.
- Filters out invalid entity / relation types preserving Phase 1 behaviour.
- Honours the ``supersedes`` field added in Phase 3.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from mnemo_mcp.temporal.extract import extract_entities


class TestExtractEntitiesPhase3:
    async def test_returns_none_when_no_provider(self):
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await extract_entities("Python is a programming language")
            assert result is None

    async def test_dispatches_via_call_llm(self):
        canned = json.dumps(
            {
                "entities": [{"name": "Python", "type": "tool"}],
                "relations": [],
            }
        )
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=canned,
        ) as mock_llm:
            result = await extract_entities("Python is a tool")
            assert result is not None
            assert result["entities"][0]["name"] == "Python"
            assert result["entities"][0]["type"] == "tool"
            assert result["relations"] == []
            assert result["supersedes"] == []
            mock_llm.assert_called_once()
            # Verify temperature=0.0 + structured prompt
            args, kwargs = mock_llm.call_args
            assert kwargs.get("temperature") == 0.0
            assert "<untrusted_memory_content>" in args[0]

    async def test_invalid_json_returns_none(self):
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value="not json at all",
        ):
            result = await extract_entities("text")
            assert result is None

    async def test_missing_entities_key_returns_none(self):
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=json.dumps({"relations": []}),
        ):
            result = await extract_entities("text")
            assert result is None

    async def test_validates_entity_types_filters_invalid(self):
        canned = json.dumps(
            {
                "entities": [
                    {"name": "Python", "type": "tool"},
                    {"name": "Bogus", "type": "invalid"},
                    {"name": "Alice", "type": "person"},
                ],
                "relations": [],
            }
        )
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=canned,
        ):
            result = await extract_entities("text")
            assert result is not None
            names = {e["name"] for e in result["entities"]}
            assert "Python" in names
            assert "Alice" in names
            assert "Bogus" not in names

    async def test_validates_relation_types_filters_invalid(self):
        canned = json.dumps(
            {
                "entities": [
                    {"name": "A", "type": "concept"},
                    {"name": "B", "type": "concept"},
                ],
                "relations": [
                    {"source": "A", "target": "B", "type": "uses"},
                    {"source": "A", "target": "B", "type": "frobnicates"},
                ],
            }
        )
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=canned,
        ):
            result = await extract_entities("text")
            assert result is not None
            assert len(result["relations"]) == 1
            assert result["relations"][0]["type"] == "uses"

    async def test_supersedes_section_parsed(self):
        canned = json.dumps(
            {
                "entities": [{"name": "Python", "type": "tool"}],
                "relations": [],
                "supersedes": [
                    {"old_fact_id": "abc123", "confidence": 0.92},
                    {"old_fact_id": "def456", "confidence": 0.42},
                ],
            }
        )
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=canned,
        ):
            result = await extract_entities("text")
            assert result is not None
            assert len(result["supersedes"]) == 2
            assert result["supersedes"][0]["old_fact_id"] == "abc123"
            assert result["supersedes"][0]["confidence"] == 0.92

    async def test_supersedes_filters_invalid_confidence(self):
        canned = json.dumps(
            {
                "entities": [{"name": "X", "type": "concept"}],
                "supersedes": [
                    {"old_fact_id": "ok", "confidence": 0.5},
                    {"old_fact_id": "bad", "confidence": "not-a-number"},
                    {"old_fact_id": "out-of-range", "confidence": 1.5},
                ],
            }
        )
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=canned,
        ):
            result = await extract_entities("text")
            assert result is not None
            assert len(result["supersedes"]) == 1
            assert result["supersedes"][0]["old_fact_id"] == "ok"

    async def test_truncates_content_to_3000_chars(self):
        with patch(
            "mnemo_mcp.temporal.extract.call_llm",
            new_callable=AsyncMock,
            return_value=json.dumps({"entities": []}),
        ) as mock_llm:
            big = "x" * 5000
            await extract_entities(big)
            args, _ = mock_llm.call_args
            prompt = args[0]
            # Find the inner section between tags
            assert "<untrusted_memory_content>" in prompt
            inner = prompt.split("<untrusted_memory_content>")[1].split(
                "</untrusted_memory_content>"
            )[0]
            assert len(inner.strip()) == 3000
