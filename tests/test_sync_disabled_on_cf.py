"""Passport delta-sync is gated off on Cloudflare (D1 is the durable store).

On CF, D1 + Vectorize survive container recreates, so the GDrive/S3 passport
delta-sync is redundant -- and it operates on raw ``db._conn`` (LWW writes) which
the D1 shim does not back. The gate is mode-based: ``DOCS_DB_BACKEND=cf-d1`` ->
scheduler OFF; local / self-host (sqlite) -> scheduler ON.
"""

import mnemo_mcp.sync as sync


def test_passport_scheduler_disabled_on_cf(monkeypatch):
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    sync.stop_passport_scheduler()  # clean slate
    # interval > 0 would normally spawn a task; the CF gate short-circuits first.
    assert sync.start_passport_scheduler(object(), interval=300) is False


async def test_passport_scheduler_runs_locally(monkeypatch):
    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    sync.stop_passport_scheduler()  # clear any leftover task
    try:
        assert sync.start_passport_scheduler(object(), interval=300) is True
    finally:
        sync.stop_passport_scheduler()
