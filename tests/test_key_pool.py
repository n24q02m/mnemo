"""Provider key pools: rotation, disable, redacted exhaustion, seeding.

The pool itself is hull's (``hull_core.credentials``); these tests pin mnemo's
adapter: every provider call leases a credential, records the outcome, rotates
on 401/403/429, migrates a legacy single key exactly once, and maps hull's
exhaustion error into mnemo's redacted ``ProviderCredentialsExhausted``.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from hull_core.config.models import ModelCell
from hull_core.providers.openai_spec import ProviderError

from mnemo import keys, runtime
from mnemo.exceptions import ProviderCredentialsExhausted

BASE_URL = "https://openrouter.ai/api/v1"
KEY_ONE = "sk-or-v1-rotation-" + "0001"
KEY_TWO = "sk-or-v1-rotation-" + "0002"


def _cell(**overrides) -> ModelCell:
    fields = {
        "task": "chat",
        "base_url": BASE_URL,
        "api_key": "",
        "model": "z-ai/glm-5.3-flash",
    }
    fields.update(overrides)
    return ModelCell(**fields)


def _seed(*key_values: str, provider: str = "openrouter", account: str | None = None):
    store = keys.credential_store()
    return [
        store.add_credential(provider, value, base_url=BASE_URL, account_id=account)
        for value in key_values
    ]


class _RateLimited(ProviderError):
    """A 429 carrying the provider's hint, as a real HTTP client would."""

    def __init__(self, detail: str = "slow down", retry_after: str = "7") -> None:
        super().__init__(429, detail)
        self.headers = {"Retry-After": retry_after}


class _ScriptedClient:
    """Stand-in for ``OpenAICompatClient``: fails the keys it is told to fail.

    Each call suspends *inside* the attempt window, so two attempts that hold
    the same credential at once are detectable (``overlap``).
    """

    instances: list[_ScriptedClient] = []
    failures: dict[str, Exception] = {}
    in_flight: list[str] = []
    overlap = False
    fail_close = False

    def __init__(self, cell, *, auth_mode="no-auth", timeout=60.0) -> None:
        self.cell = cell
        self.auth_mode = auth_mode
        self.timeout = timeout
        _ScriptedClient.instances.append(self)

    @asynccontextmanager
    async def _attempt(self):
        key = self.cell.api_key
        if key in _ScriptedClient.in_flight:
            _ScriptedClient.overlap = True
        _ScriptedClient.in_flight.append(key)
        try:
            await asyncio.sleep(0.01)
            failure = _ScriptedClient.failures.get(key)
            if failure is not None:
                raise failure
            yield key
        finally:
            _ScriptedClient.in_flight.remove(key)

    async def chat(self, messages, **options) -> str:
        async with self._attempt() as key:
            return f"answer from {key}"

    async def embeddings(self, texts, *, dimensions=None, **extra):
        async with self._attempt():
            return [[len(texts), dimensions]]

    async def rerank(self, query, documents, top_n=None):
        async with self._attempt():
            return [{"index": 0, "relevance_score": 1.0, "query": query}]

    async def aclose(self) -> None:
        if self.fail_close:
            raise RuntimeError("loop already closed")
        return None


@pytest.fixture(autouse=True)
def _scripted(monkeypatch: pytest.MonkeyPatch):
    _ScriptedClient.instances = []
    _ScriptedClient.failures = {}
    _ScriptedClient.in_flight = []
    _ScriptedClient.overlap = False
    _ScriptedClient.fail_close = False
    monkeypatch.setattr("mnemo.keys.openai_spec.OpenAICompatClient", _ScriptedClient)
    runtime.reset_settings_cache()
    yield
    _ScriptedClient.instances = []
    _ScriptedClient.failures = {}
    _ScriptedClient.in_flight = []
    _ScriptedClient.overlap = False
    _ScriptedClient.fail_close = False


def _health() -> list:
    return keys.pool_for(_cell()).health()


# ---------------------------------------------------------------------------
# rotation
# ---------------------------------------------------------------------------


def test_two_key_rotation_on_429() -> None:
    """A 429 cools the first key (honouring Retry-After) and the second serves."""
    _seed(KEY_ONE, KEY_TWO)
    _ScriptedClient.failures = {KEY_ONE: _RateLimited(retry_after="7")}

    text = asyncio.run(
        keys.PooledClient(_cell()).chat([{"role": "user", "content": "q"}])
    )

    assert text == f"answer from {KEY_TWO}"
    first, second = _health()
    assert first.last_status == 429
    assert first.cooldown_remaining > 5.5, "Retry-After: 7 was not honoured"
    assert first.usable is False
    assert second.last_status == 200
    assert second.usable is True
    # Two attempts, one per credential.
    assert [client.cell.api_key for client in _ScriptedClient.instances] == [
        KEY_ONE,
        KEY_TWO,
    ]


def test_401_disables_the_credential_and_rotates() -> None:
    _seed(KEY_ONE, KEY_TWO)
    _ScriptedClient.failures = {KEY_ONE: ProviderError(401, "invalid api key")}

    text = asyncio.run(
        keys.PooledClient(_cell()).chat([{"role": "user", "content": "q"}])
    )

    assert text == f"answer from {KEY_TWO}"
    first, second = _health()
    assert first.disabled is True
    assert first.last_status == 401
    assert second.disabled is False
    # The disabled key is not leased again on the next call.
    _ScriptedClient.instances.clear()
    asyncio.run(keys.PooledClient(_cell()).chat([{"role": "user", "content": "q"}]))
    assert [client.cell.api_key for client in _ScriptedClient.instances] == [KEY_TWO]


def test_client_error_status_does_not_rotate() -> None:
    """A 400 is the request's fault: re-raise untouched, keep the key usable."""
    _seed(KEY_ONE, KEY_TWO)
    _ScriptedClient.failures = {KEY_ONE: ProviderError(400, "bad request")}

    with pytest.raises(ProviderError):
        asyncio.run(keys.PooledClient(_cell()).chat([{"role": "user", "content": "q"}]))

    health = _health()
    assert [item.disabled for item in health] == [False, False]
    assert [item.usable for item in health] == [True, True]
    assert [item.last_status for item in health] == [None, None]
    assert [item.failure_count for item in health] == [0, 0]


# ---------------------------------------------------------------------------
# exhaustion
# ---------------------------------------------------------------------------


def test_exhaustion_is_redacted_and_carries_retry_after() -> None:
    _seed(KEY_ONE)
    _ScriptedClient.failures = {KEY_ONE: _RateLimited(retry_after="30")}

    with pytest.raises(ProviderCredentialsExhausted) as caught:
        asyncio.run(keys.PooledClient(_cell()).chat([{"role": "user", "content": "q"}]))

    error = caught.value
    assert error.provider == "openrouter"
    assert error.account is None
    assert (error.total, error.disabled, error.cooling_down) == (1, 0, 1)
    assert error.retry_after is not None and error.retry_after > 20
    message = str(error)
    assert "retry in" in message
    assert KEY_ONE not in message
    assert "slow down" in message  # last error text survives, key does not


def test_exhaustion_redacts_a_key_echoed_by_the_provider() -> None:
    _seed(KEY_ONE)
    _ScriptedClient.failures = {
        KEY_ONE: ProviderError(401, f"invalid api key {KEY_ONE}")
    }

    with pytest.raises(ProviderCredentialsExhausted) as caught:
        asyncio.run(keys.PooledClient(_cell()).chat([{"role": "user", "content": "q"}]))

    message = str(caught.value)
    assert KEY_ONE not in message
    assert "[redacted]" in message
    assert caught.value.disabled == 1


def test_empty_pool_raises_mnemo_error() -> None:
    with pytest.raises(ProviderCredentialsExhausted) as caught:
        asyncio.run(keys.PooledClient(_cell()).chat([{"role": "user", "content": "q"}]))

    assert caught.value.total == 0
    assert "no usable 'openrouter' credential" in str(caught.value)


# ---------------------------------------------------------------------------
# legacy single key
# ---------------------------------------------------------------------------


def test_legacy_config_key_is_seeded_once_and_keeps_working() -> None:
    cell = _cell(api_key=KEY_ONE)

    first = keys.ensure_seeded(cell)
    assert first is not None
    assert (first.provider, first.added, first.skipped) == ("openrouter", 1, 0)

    # Second boot: the pool already holds a credential, nothing is copied.
    assert keys.ensure_seeded(cell) is None
    assert [item.api_key for item in keys.pool_for(cell).credentials()] == [KEY_ONE]

    text = asyncio.run(keys.PooledClient(cell).chat([{"role": "user", "content": "q"}]))
    assert text == f"answer from {KEY_ONE}"


def test_legacy_env_key_is_migrated_without_deleting_the_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = Path(os.environ["HOME"]) / ".mnemo"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        f'[models.chat]\nbase_url = "{BASE_URL}"\nmodel = "z-ai/glm-5.3-flash"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HULL_CHAT_API_KEY", KEY_TWO)
    runtime.reset_settings_cache()

    assert runtime.model_cell("chat").api_key == KEY_TWO  # hull env override
    results = runtime.seed_provider_credentials()
    assert [(result.provider, result.added) for result in results] == [
        ("openrouter", 1)
    ]
    assert os.environ["HULL_CHAT_API_KEY"] == KEY_TWO
    assert [item.api_key for item in keys.pool_for(_cell()).credentials()] == [KEY_TWO]
    # Seeding again on the next boot stays a no-op.
    assert runtime.seed_provider_credentials() == []


def test_cell_without_key_and_empty_pool_stays_unconfigured() -> None:
    assert runtime.cell_configured("chat") is False


def test_cell_configured_by_a_stored_credential_only() -> None:
    _seed(KEY_ONE)
    assert runtime.cell_configured("chat") is True
    assert runtime.provider_client("chat").cell.api_key == ""


def test_legacy_key_wins_the_configured_flag_without_touching_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HULL_CHAT_API_KEY", KEY_ONE)
    runtime.reset_settings_cache()
    assert runtime.cell_configured("chat") is True


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def test_named_account_pool_is_isolated_from_the_default_pool() -> None:
    account = keys.credential_store().accounts().add(provider="openrouter", name="Work")
    _seed(KEY_ONE)
    _seed(KEY_TWO, account=account.account_id)

    default_pool = keys.pool_for(_cell())
    account_pool = keys.pool_for(_cell(account=account.account_id))

    assert [item.api_key for item in default_pool.credentials()] == [KEY_ONE]
    assert [item.api_key for item in account_pool.credentials()] == [KEY_TWO]

    text = asyncio.run(
        keys.PooledClient(_cell(account=account.account_id)).chat(
            [{"role": "user", "content": "q"}]
        )
    )
    assert text == f"answer from {KEY_TWO}"


def test_provider_override_selects_another_pool() -> None:
    store = keys.credential_store()
    store.add_credential("gateway", KEY_TWO, base_url="https://gw.example/v1")

    assert keys.provider_id(_cell(provider="gateway")) == "gateway"
    assert [
        item.api_key for item in keys.pool_for(_cell(provider="gateway")).credentials()
    ] == [KEY_TWO]
    # An unknown account is reported at seed time instead of crashing startup.
    cell = _cell(api_key=KEY_ONE, account="missing")
    assert keys.seed_from_cells([cell]) == []
    assert keys.pool_total(cell) == 0


# ---------------------------------------------------------------------------
# concurrency + isolation of the store
# ---------------------------------------------------------------------------


def test_concurrent_calls_never_share_a_leased_credential() -> None:
    """The gate plus hull's lease keep one in-flight call per credential."""
    _seed(KEY_ONE, KEY_TWO)
    client = keys.PooledClient(_cell())

    async def run() -> list[str]:
        return await asyncio.gather(
            *(client.chat([{"role": "user", "content": str(i)}]) for i in range(4))
        )

    texts = asyncio.run(run())

    assert len(set(texts)) == 2
    assert _ScriptedClient.overlap is False, "two calls used the same leased key"
    assert [client.cell.api_key for client in _ScriptedClient.instances] == [
        KEY_ONE,
        KEY_TWO,
    ]


def test_lease_state_is_shared_through_the_store() -> None:
    """Two pools (two processes) never lease the same credential at once."""
    _seed(KEY_ONE, KEY_TWO)
    cell = _cell()
    first = keys.pool_for(cell).acquire()
    second = keys.pool_for(cell).acquire()

    assert {first.api_key, second.api_key} == {KEY_ONE, KEY_TWO}
    with pytest.raises(Exception, match="leased=2"):
        keys.pool_for(cell).acquire()


def test_provider_client_is_cached_per_task_and_config() -> None:
    chat = runtime.provider_client("chat")
    assert runtime.provider_client("chat") is chat
    assert runtime.provider_client("embed") is not chat

    runtime.reset_provider_clients()
    assert runtime.provider_client("chat") is not chat

    # A settings reload (config edit) drops them too.
    runtime.provider_client("chat")
    runtime.reset_settings_cache()
    assert runtime.provider_client("chat") is not chat


def test_store_lives_under_the_instance_config_dir() -> None:
    assert keys.store_path() == Path(os.environ["HOME"]) / ".mnemo" / "credentials.db"
    keys.credential_store()
    assert keys.store_path().is_file()


def test_pool_health_is_masked() -> None:
    _seed(KEY_ONE)
    health = keys.PooledClient(_cell()).health()
    assert health[0].key_hint.endswith(KEY_ONE[-4:])
    assert KEY_ONE not in repr(health[0])


def test_aclose_is_idempotent_and_closes_cached_clients() -> None:
    _seed(KEY_ONE)
    client = keys.PooledClient(_cell())
    asyncio.run(client.chat([{"role": "user", "content": "q"}]))
    asyncio.run(client.aclose())
    asyncio.run(client.aclose())
    # A closed client is rebuilt on the next call instead of reused.
    _ScriptedClient.instances.clear()
    asyncio.run(client.chat([{"role": "user", "content": "q"}]))
    assert len(_ScriptedClient.instances) == 1


# ---------------------------------------------------------------------------
# every operation goes through the pool
# ---------------------------------------------------------------------------


def test_embeddings_and_rerank_rotate_through_the_pool() -> None:
    """The pool sits under every provider call, not only chat."""
    _seed(KEY_ONE, KEY_TWO)
    _ScriptedClient.failures = {KEY_ONE: _RateLimited(retry_after="5")}
    client = keys.PooledClient(_cell(task="embed"))

    vectors = asyncio.run(client.embeddings(["a", "b"], dimensions=1024))
    results = asyncio.run(client.rerank("q", ["a"], top_n=1))

    assert vectors == [[2, 1024]]  # scripted echo: (batch size, dimensions)
    assert results == [{"index": 0, "relevance_score": 1.0, "query": "q"}]
    # 429 on the first key rotated both calls onto the second one.
    assert [item.cell.api_key for item in _ScriptedClient.instances] == [
        KEY_ONE,
        KEY_TWO,
        KEY_TWO,
    ]
    assert client.provider == "openrouter"
    assert client.account is None


def test_unregistered_account_is_reported_not_created() -> None:
    cell = _cell(account="missing")

    with pytest.raises(ProviderCredentialsExhausted) as caught:
        keys.pool_for(cell)

    assert caught.value.account == "missing"
    assert "not registered" in str(caught.value)
    assert keys.credential_store().account_row("missing") is None


def test_unreadable_store_degrades_to_the_cell_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(cell) -> int:
        raise OSError("disk gone")

    monkeypatch.setattr(keys, "pool_total", boom)
    assert keys.cell_pool_configured(_cell(api_key=KEY_ONE)) is False
    assert keys.cell_pool_configured(_cell(api_key=KEY_ONE)) is False  # warned once


def test_seed_from_cells_survives_a_failing_cell(monkeypatch) -> None:
    def boom(cell) -> None:
        raise RuntimeError("unwritable store")

    monkeypatch.setattr(keys, "ensure_seeded", boom)
    assert keys.seed_from_cells([_cell(api_key=KEY_ONE)]) == []


def test_aclose_survives_a_client_from_a_dead_loop() -> None:
    """The rerank path runs one ``asyncio.run`` per call; closing must not raise."""
    _seed(KEY_ONE)
    client = keys.PooledClient(_cell())
    _ScriptedClient.fail_close = True
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(client.chat([{"role": "user", "content": "q"}]))
        assert client._clients, "the attempt should have cached its transport"
        loop.run_until_complete(client.aclose())  # a raising close is swallowed
    finally:
        loop.close()
    assert client._clients == {}


def test_store_is_reopened_when_the_instance_root_moves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = keys.credential_store()
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "elsewhere"))
    second = keys.credential_store()

    assert second is not first
    assert second.path != first.path
    assert second.path.parent.is_dir()
