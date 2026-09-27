"""Genuine gaps in graph.py parsing/robustness paths.

The existing suites exercise the cell-not-configured gate and the happy
paths; these tests patch the gate OPEN so the parsing bodies actually run:
invalid completions must degrade to safe defaults instead of crashing or
returning attacker-controlled data.
"""

from unittest.mock import AsyncMock, patch

import pytest

from mnemo_mcp.graph import extract_entities, score_importance


def _cell_ready():
    return (
        patch("mnemo_mcp.graph._cell_ready", return_value=True),
        patch("mnemo_mcp.graph._cell_completion", new_callable=AsyncMock),
    )


class TestExtractEntitiesParsing:
    async def test_valid_json_without_entities_key_returns_none(self):
        ready, completion = _cell_ready()
        with ready, completion as mock_completion:
            mock_completion.return_value = '{"relations": []}'
            result = await extract_entities("test content")
        assert result is None

    async def test_completion_exception_returns_none(self):
        ready, completion = _cell_ready()
        with ready, completion as mock_completion:
            mock_completion.side_effect = RuntimeError("API exploded")
            result = await extract_entities("test content")
        assert result is None

    async def test_invalid_json_returns_none(self):
        ready, completion = _cell_ready()
        with ready, completion as mock_completion:
            mock_completion.return_value = "not json at all"
            result = await extract_entities("test content")
        assert result is None

    async def test_json_array_instead_of_object_returns_none(self):
        ready, completion = _cell_ready()
        with ready, completion as mock_completion:
            mock_completion.return_value = '["entities"]'
            result = await extract_entities("test content")
        assert result is None


class TestScoreImportanceParsing:
    @pytest.mark.parametrize("bad_text", ["", "   ", "\n"])
    async def test_empty_completion_falls_back_to_default(self, bad_text):
        ready, completion = _cell_ready()
        with ready, completion as mock_completion:
            mock_completion.return_value = bad_text
            score = await score_importance("content")
        assert score == 0.5

    @pytest.mark.parametrize(
        "no_number", ["no digits here", "important: high", "zero point five"]
    )
    async def test_non_numeric_completion_falls_back_to_default(self, no_number):
        ready, completion = _cell_ready()
        with ready, completion as mock_completion:
            mock_completion.return_value = no_number
            score = await score_importance("content")
        assert score == 0.5

    async def test_number_wrapped_in_prose_is_extracted(self):
        ready, completion = _cell_ready()
        with ready, completion as mock_completion:
            mock_completion.return_value = "importance: 0.7"
            score = await score_importance("content")
        assert score == 0.7
