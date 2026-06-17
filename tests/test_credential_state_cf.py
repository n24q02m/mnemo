"""Task 3: per-sub credentials routed through PerPluginStore (cf-kv seam).

``store_for_sub`` previously did a raw ``os.open`` plaintext write to
``subs/<hash>/config.json``, bypassing PerPluginStore so it never picked up the
cf-kv backend. Routing both the write and the per-request read through
PerPluginStore (keyed by SHA-256 hashed sub) makes per-sub config encrypted +
KV-routable while keeping the on-disk layout identical on a workstation.
"""

import hashlib

from mcp_core.storage.backends import InMemoryBackend

import mnemo_mcp.credential_state as cs


def test_store_for_sub_routes_through_backend(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    mem = InMemoryBackend()
    monkeypatch.setattr(cs, "_cred_backend", lambda: mem)
    cs.store_for_sub("user1", {"JINA_AI_API_KEY": "jina_xxx"})
    h = hashlib.sha256(b"user1").hexdigest()
    # encrypted blob under the hashed per-sub config key; raw sub never used
    assert mem.get(f"mnemo/subs/{h}/config") is not None
    assert mem.get("mnemo/subs/user1/config") is None


def test_per_sub_credentials_no_bleed(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    mem = InMemoryBackend()
    monkeypatch.setattr(cs, "_cred_backend", lambda: mem)
    cs.store_for_sub("user1", {"GEMINI_API_KEY": "u1"})
    cs.store_for_sub("user2", {"GEMINI_API_KEY": "u2"})
    cs.set_current_sub("user1")
    assert cs.credentials_for_current_request().get("GEMINI_API_KEY") == "u1"
    cs.set_current_sub("user2")
    assert cs.credentials_for_current_request().get("GEMINI_API_KEY") == "u2"
    cs.set_current_sub(None)
