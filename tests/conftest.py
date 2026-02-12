"""Shared test fixtures for Mnemo MCP Server."""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mnemo_mcp.db import MemoryDB


@pytest.fixture
def tmp_db(tmp_path: Path) -> Generator[MemoryDB]:
    """Temporary MemoryDB without embeddings."""
    db = MemoryDB(tmp_path / "test.db", embedding_dims=0)
    yield db
    db.close()


@pytest.fixture
def tmp_db_with_data(tmp_db: MemoryDB) -> MemoryDB:
    """MemoryDB seeded with sample data."""
    tmp_db.add(
        "Python is a programming language",
        category="tech",
        tags=["python", "lang"],
    )
    tmp_db.add(
        "TypeScript is used for web development",
        category="tech",
        tags=["typescript", "web"],
    )
    tmp_db.add(
        "Remember to buy groceries",
        category="personal",
        tags=["todo"],
    )
    tmp_db.add(
        "Meeting at 3pm on Friday",
        category="work",
        tags=["meeting", "schedule"],
    )
    return tmp_db


@pytest.fixture
def mock_ctx(tmp_db: MemoryDB):
    """Mock MCP Context with DB (no embeddings)."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": tmp_db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    return ctx, tmp_db
