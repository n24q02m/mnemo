"""Provider credential pools for mnemo's task cells (``hull_core.credentials``).

mnemo used to resolve exactly one key per task cell, so a revoked or
rate-limited key took the whole feature down: compression skipped, cloud
embedding failed, rerank fell back to local. The cell shape is unchanged --
``base_url + api_key + model`` in ``~/.mnemo/config.toml`` -- and hull keeps an
ordered **pool** of credentials per provider identity in
``~/.mnemo/credentials.db``:

* every provider call leases the highest-priority usable credential, makes the
  request with that credential's own ``api_key``/``base_url`` and records the
  outcome: 2xx clears the entry, 401/403 disables it, 429 cools it down
  (``Retry-After`` / ``rate_limit_reset``, clamped 1 s..1 h), 5xx retries once
  and then rotates, any other status re-raises untouched;
* ``provider`` and ``account`` keys in ``[models.<task>]`` select which pool a
  cell reads (default: the provider's unaccounted pool);
* a legacy single key (config file or ``HULL_<TASK>_API_KEY``) is seeded into
  its pool while that pool is still empty, so existing setups keep working
  without edits. The env var is never deleted and no key is ever logged.

Rotation policy, bounded attempts and the redacted exhaustion error live in
hull (:class:`hull_core.credentials.KeyPool`); this module is only the
product-side adapter: pool resolution, one-time seeding, and a per-attempt
client built from the leased credential.

Model ownership: four task cells share one provider pool but never one model,
so the *cell* keeps the model id and the credential contributes only the key
and its endpoint. A credential's own ``model`` column is advisory and unused
here.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hull_core.config.models import ModelCell
from hull_core.credentials import (
    Credential,
    CredentialHealth,
    CredentialStore,
    KeyPool,
    MigrationResult,
    PoolExhaustedError,
    provider_from_base_url,
)
from hull_core.providers import openai_spec
from loguru import logger

from mnemo.exceptions import ProviderCredentialsExhausted

if TYPE_CHECKING:
    from hull_core.providers.openai_spec import OpenAICompatClient

# Instance-local store next to ``memories.db``: credential scope follows the
# instance (``~/.mnemo``), not the machine-wide ``~/.hull`` database that other
# hull products own.
STORE_FILENAME = "credentials.db"

# One in-flight attempt per leased credential; the lease is hull's default.
LEASE_SECONDS = 60.0
MAX_5XX_RETRIES = 1

_store: CredentialStore | None = None
_store_path: str | None = None
_store_warned = False
_warned_scopes: set[str] = set()


def store_path() -> Path:
    """The instance credential store: ``~/.mnemo/credentials.db``."""
    from mnemo.runtime import mnemo_config_dir

    return mnemo_config_dir() / STORE_FILENAME


def credential_store() -> CredentialStore:
    """Process-wide store (one SQLite connection per instance config root)."""
    global _store, _store_path
    path = str(store_path())
    if _store is None or _store_path != path:
        if _store is not None:
            _store.close()
        _store = CredentialStore(path)
        _store_path = path
    return _store


def reset_credential_cache() -> None:
    """Drop the cached store (tests, or after the config root changes)."""
    global _store, _store_path, _store_warned
    if _store is not None:
        _store.close()
    _store = None
    _store_path = None
    _store_warned = False
    _warned_scopes.clear()


def _text_attr(cell: Any, name: str) -> str:
    """Read a hull cell's optional string field; duck-typed cells stay empty."""
    value = getattr(cell, name, "")
    return value.strip() if isinstance(value, str) else ""


def provider_id(cell: ModelCell) -> str:
    """Pool identity for a cell: its ``provider`` key, else derived from base_url."""
    return _text_attr(cell, "provider") or provider_from_base_url(
        _text_attr(cell, "base_url")
    )


def account_id(cell: ModelCell) -> str | None:
    """Named account a cell points at; ``None`` is the provider's default pool."""
    return _text_attr(cell, "account") or None


def _scope(provider: str, account: str | None) -> str:
    return f"{provider!r}" if account is None else f"{provider!r}/{account!r}"


def _registered(store: CredentialStore, provider: str, account: str | None) -> bool:
    """True when the cell's pool scope exists (always, for the default pool)."""
    if account is None:
        return True
    if store.account_row(account) is not None:
        return True
    warning = (
        f"credential pool {_scope(provider, account)}: the account is not in "
        "the registry; add it with hull_core.credentials.AccountRegistry.add "
        "before using it"
    )
    if warning not in _warned_scopes:
        _warned_scopes.add(warning)
        logger.warning(warning)
    return False


def _unregistered_error(provider: str, account: str) -> ProviderCredentialsExhausted:
    return ProviderCredentialsExhausted(
        f"no usable {provider!r} credential for account {account!r}: the account "
        "is not registered; add it with hull_core.credentials.AccountRegistry "
        "first",
        provider=provider,
        account=account,
    )


def ensure_seeded(
    cell: ModelCell, *, store: CredentialStore | None = None
) -> MigrationResult | None:
    """Seed a cell's legacy single key into its pool while the pool is empty.

    Idempotent by construction: once the pool holds any credential the cell's
    key is no longer copied, so an operator-removed key does not come back on
    the next boot and repeated calls do no inserts. Returns ``None`` when there
    was nothing to do (no key, no endpoint, or a pool that is already seeded).
    """
    key = _text_attr(cell, "api_key")
    base_url = _text_attr(cell, "base_url")
    if not key or not base_url:
        # Nothing to migrate: an empty cell, or a duck-typed test double that
        # carries no real endpoint. The pool decides the call outcome.
        return None
    store = credential_store() if store is None else store
    provider, account = provider_id(cell), account_id(cell)
    if not _registered(store, provider, account):
        return None
    if int(store.diagnose(provider, account)["total"]) > 0:
        return None
    result = store.migrate_model_cells([cell], provider=provider, account_id=account)
    logger.info(
        f"credential pool {_scope(provider, account)}: seeded "
        f"{result.added} credential(s) from the configured cell, "
        f"{result.skipped} already stored"
    )
    return result


def seed_from_cells(cells: Any) -> list[MigrationResult]:
    """Seed every configured task cell (server start; idempotent)."""
    results: list[MigrationResult] = []
    for cell in cells:
        try:
            result = ensure_seeded(cell)
        except Exception as exc:
            # A named account that the registry does not know yet, or an
            # unwritable store: report the scope, never the key.
            logger.warning(
                f"credential pool {_scope(provider_id(cell), account_id(cell))}: "
                f"seeding skipped ({type(exc).__name__}: {exc})"
            )
            continue
        if result is not None:
            results.append(result)
    return results


def pool_for(cell: ModelCell) -> KeyPool:
    """Health-aware rotation pool for the cell's provider/account scope."""
    store = credential_store()
    provider, account = provider_id(cell), account_id(cell)
    if not _registered(store, provider, account):
        raise _unregistered_error(provider, account or "")
    ensure_seeded(cell, store=store)
    return store.pool(
        provider,
        account_id=account,
        max_5xx_retries=MAX_5XX_RETRIES,
        lease_seconds=LEASE_SECONDS,
    )


def pool_total(cell: ModelCell) -> int:
    """How many credentials the cell's pool holds (0 when it can serve nothing)."""
    store = credential_store()
    provider, account = provider_id(cell), account_id(cell)
    if not _registered(store, provider, account):
        return 0
    ensure_seeded(cell, store=store)
    return int(store.diagnose(provider, account)["total"])


def cell_pool_configured(cell: ModelCell) -> bool:
    """True when a stored credential exists for the cell's pool.

    Bounded resilience: a broken instance store must not take the memory
    server down, so the failure is reported once and rotation degrades to the
    cell's own single key. The message names the failure class only.
    """
    global _store_warned
    try:
        return pool_total(cell) > 0
    except Exception as exc:
        if not _store_warned:
            _store_warned = True
            logger.warning(
                f"credential store unavailable ({type(exc).__name__}: {exc}); "
                "falling back to each cell's single key"
            )
        return False


def pool_health(cell: ModelCell) -> list[CredentialHealth]:
    """Masked pool state for operators (no key material)."""
    return pool_for(cell).health()


def _credential_cell(credential: Credential, template: ModelCell) -> ModelCell:
    """Per-attempt cell: the credential owns the key + endpoint, the cell the model."""
    return ModelCell(
        task=template.task,
        base_url=credential.base_url or template.base_url,
        api_key=credential.api_key,
        model=template.model,
        provider=template.provider,
        account=template.account,
    )


class PooledClient:
    """OpenAI-spec client façade whose every call rotates the pool's keys.

    ``cell`` stays the configured cell (display identity for logs and model
    names); each attempt is served by a real
    :class:`~hull_core.providers.openai_spec.OpenAICompatClient` built from the
    leased credential. Attempts are gated to the pool size because hull leases
    a credential exclusively for one in-flight attempt: without the gate a
    second concurrent call on a one-key pool would read that lease as
    exhaustion instead of waiting for it.

    Underlying clients are cached per event loop so a long-lived server loop
    keeps HTTP keep-alive across calls; a loop that dies with its thread (the
    rerank path runs one ``asyncio.run`` per call) drops its clients with it.
    """

    def __init__(
        self,
        cell: ModelCell,
        *,
        auth_mode: str = "no-auth",
        timeout: float = 60.0,
    ) -> None:
        self.cell = cell
        self._auth_mode = auth_mode
        self._timeout = float(timeout)
        self._clients: weakref.WeakKeyDictionary[Any, dict[tuple[int, str], Any]] = (
            weakref.WeakKeyDictionary()
        )
        self._gates: weakref.WeakKeyDictionary[Any, tuple[int, asyncio.Semaphore]] = (
            weakref.WeakKeyDictionary()
        )

    @property
    def provider(self) -> str:
        return provider_id(self.cell)

    @property
    def account(self) -> str | None:
        return account_id(self.cell)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"PooledClient(provider={self.provider!r}, account={self.account!r})"

    def health(self) -> list[CredentialHealth]:
        """Masked per-credential state of this client's pool."""
        return pool_health(self.cell)

    # -- call surface (mirrors OpenAICompatClient) ------------------------

    async def chat(self, messages: list[dict], **options: Any) -> str:
        return await self._call("chat", lambda client: client.chat(messages, **options))

    async def embeddings(
        self,
        texts: list[str],
        *,
        dimensions: int | None = None,
        **extra: Any,
    ) -> list[list[float]]:
        return await self._call(
            "embeddings",
            lambda client: client.embeddings(texts, dimensions=dimensions, **extra),
        )

    async def rerank(
        self, query: str, documents: list[str], top_n: int | None = None
    ) -> list[dict]:
        return await self._call(
            "rerank", lambda client: client.rerank(query, documents, top_n=top_n)
        )

    async def aclose(self) -> None:
        """Close every cached transport (best effort; dead loops included)."""
        for clients in list(self._clients.values()):
            for client in list(clients.values()):
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001 - a dead loop's client must not raise
                    pass
        self._clients.clear()
        self._gates.clear()

    # -- attempt plumbing -------------------------------------------------

    async def _call(
        self, op: str, call: Callable[[OpenAICompatClient], Awaitable[Any]]
    ) -> Any:
        pool = pool_for(self.cell)
        total = int(pool.store.diagnose(pool.provider, pool.account_id)["total"])

        async def attempt(credential: Credential) -> Any:
            try:
                return await call(self._client_for(credential))
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    # Cancellation (e.g. the server's embed deadline) bypasses
                    # KeyPool.arun, which releases only on Exception; release the
                    # lease here so the next call is not refused for LEASE_SECONDS.
                    pool.report_failure(credential, None)
                raise

        async with self._gate(total):
            try:
                return await pool.arun(attempt)
            except PoolExhaustedError as exc:
                logger.warning(f"{op}: provider pool exhausted: {exc}")
                raise ProviderCredentialsExhausted.from_pool_error(exc) from exc

    def _gate(self, total: int) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        gate = self._gates.get(loop)
        if gate is None or gate[0] != total:
            gate = (total, asyncio.Semaphore(max(1, total)))
            self._gates[loop] = gate
        return gate[1]

    def _client_for(self, credential: Credential) -> OpenAICompatClient:
        loop = asyncio.get_running_loop()
        clients = self._clients.get(loop)
        if clients is None:
            clients = {}
            self._clients[loop] = clients
        slot = (credential.id, credential.key_hint)
        client = clients.get(slot)
        if client is None:
            client = openai_spec.OpenAICompatClient(
                _credential_cell(credential, self.cell),
                auth_mode=self._auth_mode,
                timeout=self._timeout,
            )
            clients[slot] = client
        return client


__all__ = [
    "LEASE_SECONDS",
    "MAX_5XX_RETRIES",
    "STORE_FILENAME",
    "PooledClient",
    "account_id",
    "cell_pool_configured",
    "credential_store",
    "ensure_seeded",
    "pool_for",
    "pool_health",
    "pool_total",
    "provider_id",
    "reset_credential_cache",
    "seed_from_cells",
    "store_path",
]
