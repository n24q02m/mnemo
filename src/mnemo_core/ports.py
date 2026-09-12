"""Storage port for the mnemo pilot.

The domain layer depends on this protocol only; the concrete adapter is
mnemo_mcp's :class:`~mnemo_mcp.db.MemoryDB` (satisfied structurally).
Surfaces never talk to storage directly — they call operations.
"""

from typing import Any, Protocol, TypedDict


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


class ProviderAnswer(TypedDict):
    """What a reflect provider must return for one bounded call."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class ReflectPort(Protocol):
    """Bounded generation provider for reflect (P4 paid path).

    Implementations receive ONLY already-redacted citations and the query;
    they must honor the caller's spend cap and report token usage so the
    core can build a cost receipt.
    """

    def synthesize(
        self, query: str, citations: list[dict[str, Any]]
    ) -> ProviderAnswer: ...


class CapExceeded(RuntimeError):
    """Raised by a ReflectPort when the session spend cap is exhausted."""
