"""token_store public contract over the PerPluginStore seam.

Storage internals (file permissions, os.open/chmod fallbacks, plaintext layout)
moved into mcp-core's PerPluginStore + LocalFsBackend and are covered there.
These tests pin the mnemo-side contract: save/load round-trips, the guard rails
(missing / no-access_token / undecryptable -> None), deletion (backend + legacy
file modes), the conventional path helpers, and per-sub isolation. Round-trips
run through the default backend (LocalFsBackend, isolated to a tmp HOME by the
autouse `_isolate_per_plugin_home` fixture). CF-backend specifics (encryption,
cf-kv wire) live in test_token_store_cf.py.
"""

from __future__ import annotations

import pytest
from mcp_core.storage.backends import InMemoryBackend

from mnemo_mcp.token_store import (
    async_load_token,
    async_save_token,
    delete_token,
    get_token_path,
    get_token_path_for_sub,
    load_token,
    load_token_for_sub,
    save_token,
    save_token_for_sub,
)


@pytest.fixture(autouse=True)
def _credential_secret(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")


class TestLoadSave:
    def test_round_trip(self):
        token = {"access_token": "abc123", "token_type": "Bearer"}
        save_token("drive", token)
        assert load_token("drive") == token

    def test_load_missing_returns_none(self):
        assert load_token("never-saved") is None

    def test_load_missing_access_token_returns_none(self):
        save_token("drive", {"refresh": "only"})
        assert load_token("drive") is None

    def test_overwrite(self):
        save_token("drive", {"access_token": "old"})
        save_token("drive", {"access_token": "new"})
        assert load_token("drive") == {"access_token": "new"}

    def test_load_undecryptable_returns_none(self):
        mem = InMemoryBackend()
        save_token("drive", {"access_token": "x"}, backend=mem)
        # Corrupt the stored ciphertext: load must swallow the error, not raise.
        mem.put("mnemo/tokens/drive", b"not-a-valid-blob")
        assert load_token("drive", backend=mem) is None


class TestDeleteToken:
    def test_delete_via_backend(self):
        mem = InMemoryBackend()
        save_token("drive", {"access_token": "abc"}, backend=mem)
        assert delete_token("drive", backend=mem) is True
        assert load_token("drive", backend=mem) is None

    def test_delete_file_mode_nonexistent(self):
        assert delete_token("never-saved") is False

    def test_delete_file_mode_existing(self):
        path = get_token_path("legacy")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        assert delete_token("legacy") is True
        assert not path.exists()


class TestPathHelpers:
    def test_get_token_path(self):
        path = get_token_path("drive")
        assert path.name == "drive.json"
        assert path.parent.name == "tokens"

    def test_get_token_path_for_sub_is_hashed(self):
        import hashlib

        sub = "test-user"
        path = get_token_path_for_sub(sub, "google")
        safe_sub = hashlib.sha256(sub.encode("utf-8")).hexdigest()
        assert path.name == "google.json"
        assert safe_sub in str(path)
        assert sub not in str(path)  # raw sub never on disk


class TestSubTokenStore:
    def test_round_trip(self):
        token = {"access_token": "sub-abc"}
        save_token_for_sub("user1", "google", token)
        assert load_token_for_sub("user1", "google") == token

    def test_isolation_between_subs(self):
        save_token_for_sub("user1", "google", {"access_token": "u1"})
        save_token_for_sub("user2", "google", {"access_token": "u2"})
        assert load_token_for_sub("user1", "google") == {"access_token": "u1"}
        assert load_token_for_sub("user2", "google") == {"access_token": "u2"}

    def test_load_missing_returns_none(self):
        assert load_token_for_sub("user1", "missing") is None

    def test_load_missing_access_token_returns_none(self):
        save_token_for_sub("user1", "google", {"refresh": "only"})
        assert load_token_for_sub("user1", "google") is None


class TestAsyncTokenStore:
    async def test_async_round_trip(self):
        token = {"access_token": "async123"}
        await async_save_token("async_drive", token)
        assert await async_load_token("async_drive") == token

    async def test_async_round_trip_for_sub(self):
        from mnemo_mcp.token_store import (
            async_load_token_for_sub,
            async_save_token_for_sub,
        )

        await async_save_token_for_sub("async-user", "google", {"access_token": "t"})
        result = await async_load_token_for_sub("async-user", "google")
        assert result == {"access_token": "t"}
