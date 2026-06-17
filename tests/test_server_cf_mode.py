"""server.py selects the right DB + disables passport sync on Cloudflare.

``_make_db`` returns ``MemoryDBD1`` (D1 + Vectorize) when ``DOCS_DB_BACKEND=cf-d1``
and the local SQLite ``MemoryDB`` otherwise; ``config(action="sync_now")`` returns
a clear "disabled on Cloudflare" error in CF mode. embedding_dims=0 keeps the
MemoryDBD1 store-meta guard a no-op so the factory test makes no network call.
"""

import mnemo_mcp.server as server


def test_make_db_returns_d1_on_cf(cf_env):
    db = server._make_db(
        sub="user1",
        embedding_dims=0,
        embedding_model="",
        recency_half_life_days=7,
        reindex_on_model_change=False,
    )
    assert type(db).__name__ == "MemoryDBD1"
    assert db.sub == "user1"


def test_make_db_returns_local_by_default(monkeypatch, local_default_env, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "m.db"))
    db = server._make_db(
        sub=None,
        embedding_dims=0,
        embedding_model="",
        recency_half_life_days=7,
        reindex_on_model_change=False,
    )
    assert type(db).__name__ == "MemoryDB"
    db.close()


async def test_sync_now_disabled_on_cf(monkeypatch):
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    out = await server._handle_config_sync_now(None, None)
    assert "disabled on Cloudflare" in out
