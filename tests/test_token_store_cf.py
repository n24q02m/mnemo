"""Task 2: OAuth tokens encrypted through PerPluginStore (KV-routable, per-sub).

Previously token_store wrote plaintext JSON to disk. Routing through
PerPluginStore makes tokens AES-GCM ciphertext landing in the selected backend
(LocalFs default, CfKv on Cloudflare), keyed per JWT sub for multi-user.
"""

import hashlib
import json

from mcp_core.storage.backends import CfKvBackend, InMemoryBackend

from mnemo_mcp.token_store import (
    load_token,
    load_token_for_sub,
    save_token,
    save_token_for_sub,
)


def test_save_token_encrypts_via_backend(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    mem = InMemoryBackend()
    token = {"access_token": "abc123", "refresh_token": "r", "token_type": "Bearer"}
    save_token("google_drive", token, backend=mem)
    blob = mem.get("mnemo/tokens/google_drive")
    assert blob is not None and blob != json.dumps(token).encode()  # encrypted
    assert load_token("google_drive", backend=mem) == token


def test_multi_user_token_isolation(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    mem = InMemoryBackend()
    save_token_for_sub("user1", "google_drive", {"access_token": "u1"}, backend=mem)
    save_token_for_sub("user2", "google_drive", {"access_token": "u2"}, backend=mem)
    # sub is SHA-256 hashed into the key: distinct hashed keys, raw sub absent
    # (path-traversal/charset protection); the round-trips stay isolated.
    h1 = hashlib.sha256(b"user1").hexdigest()
    h2 = hashlib.sha256(b"user2").hexdigest()
    assert mem.get(f"mnemo/subs/{h1}/tokens/google_drive") is not None
    assert mem.get(f"mnemo/subs/{h2}/tokens/google_drive") is not None
    assert mem.get("mnemo/subs/user1/tokens/google_drive") is None
    assert load_token_for_sub("user1", "google_drive", backend=mem) == {
        "access_token": "u1"
    }
    assert load_token_for_sub("user2", "google_drive", backend=mem) == {
        "access_token": "u2"
    }


def test_cfkv_token_roundtrip(monkeypatch, fake_kv_http):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    backend = CfKvBackend(base_url="http://kv.internal", http=fake_kv_http)
    save_token("google_drive", {"access_token": "abc"}, backend=backend)
    assert any("tokens/google_drive" in k for k in fake_kv_http.store)
    assert load_token("google_drive", backend=backend) == {"access_token": "abc"}
