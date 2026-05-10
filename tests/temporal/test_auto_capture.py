"""Tests for Phase 3 KG_AUTO_ENABLED auto-extract on capture."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mnemo_mcp.config import settings
from mnemo_mcp.db import MemoryDB


class TestKgAutoEnabledFlag:
    def test_default_is_false(self):
        # Settings defaults: kg_auto_enabled is opt-in.
        assert settings.kg_auto_enabled is False

    def test_thresholds_have_defaults(self):
        assert settings.temporal_entity_resolution_threshold == 0.85
        assert settings.temporal_supersession_threshold == 0.85
        assert settings.temporal_supersession_enabled is True


class TestEnrichMemoryPhase3Path:
    """When KG_AUTO_ENABLED=true, enrich_memory routes via temporal.store
    instead of the legacy graph helpers."""

    @pytest.fixture(autouse=True)
    def _enable_kg(self, monkeypatch):
        monkeypatch.setattr(settings, "kg_auto_enabled", True)
        yield
        monkeypatch.setattr(settings, "kg_auto_enabled", False)

    async def test_phase3_path_invoked(self, tmp_db: MemoryDB):
        from mnemo_mcp.server import _enrich_memory

        mid = tmp_db.add("Alice works on Project X")
        canned = {
            "entities": [
                {"name": "Alice", "type": "person"},
                {"name": "Project X", "type": "project"},
            ],
            "relations": [
                {"source": "Alice", "target": "Project X", "type": "works_on"}
            ],
            "supersedes": [],
        }
        with (
            patch(
                "mnemo_mcp.temporal.extract.extract_entities",
                new_callable=AsyncMock,
                return_value=canned,
            ),
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                return_value=0.5,
            ),
        ):
            await _enrich_memory(tmp_db, mid, "Alice works on Project X")

        # Verify the edge has memory_id set (Phase 3 bookkeeping).
        edge = tmp_db._conn.execute(
            "SELECT memory_id, valid_from FROM memory_edges"
        ).fetchone()
        assert edge is not None
        assert edge["memory_id"] == mid
        assert edge["valid_from"] is not None
