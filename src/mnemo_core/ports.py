"""Storage port for the mnemo pilot.

The domain layer depends on this protocol only; the concrete adapter is
mnemo_mcp's :class:`~mnemo_mcp.db.MemoryDB` (satisfied structurally).
Surfaces never talk to storage directly — they call operations.
"""

from __future__ import annotations

from typing import Any, Protocol


class StoragePort(Protocol):
    """Minimal storage surface the pilot operations need."""

    def add(
        self,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        source: str | None = None,
        subject: str | None = None,
        embedding: list[float] | None = None,
    ) -> str: ...

    def search(
        self,
        query: str,
        embedding: list[float] | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 5,
        *,
        subject: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get(
        self, memory_id: str, subject: str | None = None
    ) -> dict[str, Any] | None: ...

    def close(self) -> None: ...
