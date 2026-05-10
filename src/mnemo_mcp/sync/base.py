"""Abstract base class for passport-sync backends (Phase 2).

Each backend (gdrive, s3, ...) implements the same four-method contract so the
sync orchestrator can push delta bundles, pull full passports, query the
remote sequence cursor, and probe health uniformly.

The bundle bytes themselves are produced by :mod:`mnemo_mcp.sync.bundle`
(AES-256-GCM + Argon2id KDF) so backends never see plaintext - they only
store / fetch opaque blobs keyed by monotonic sequence number.

Spec reference: ``2026-04-19-mnemo-v2-design.md`` section 4.4 + Phase 2 plan
Task 4.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SyncBackend(ABC):
    """Contract every passport-sync backend must satisfy.

    Implementations should be stateless beyond connection objects - sequence
    state lives in the local SQLite ``sync_state`` table and on the remote
    side via the bundle naming convention (``passport/seq-<NNNNNN>.bin``).
    """

    #: Stable identifier registered into :func:`mnemo_mcp.sync.register`.
    name: str = ""

    @abstractmethod
    async def push(self, bundle: bytes, sequence: int) -> None:
        """Upload ``bundle`` keyed by monotonic ``sequence`` number.

        Backends MUST raise on failure so the orchestrator can fall back
        instead of silently advancing the local cursor.
        """

    @abstractmethod
    async def pull(self, sequence: int | None = None) -> bytes | None:
        """Fetch a bundle by ``sequence`` number, or the latest when ``None``.

        Returns ``None`` when no bundle exists at the requested sequence
        (or the bucket / folder is empty when ``sequence is None``).
        """

    @abstractmethod
    async def last_remote_sequence(self) -> int:
        """Return the highest sequence number present on the remote.

        Returns 0 when the remote has no bundles (fresh backend state).
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Cheap probe used by ``config(action="status")`` and CI smoke tests."""
