"""Per-sub embedding-identity guard on D1 store_meta.

Ported from db.py _guard_embedding_identity (the local SQLite guard) but scoped
by sub so a shared D1 stamps/checks each user independently. A dims/model change
for a sub aborts the open (EmbeddingModelMismatch) unless REINDEX_ON_MODEL_CHANGE
is set; a fresh store stamps the current identity.
"""

import pytest
from mcp_core.storage import D1Backend, VectorizeBackend

from mnemo_mcp.db_cf import MemoryDBD1
from mnemo_mcp.exceptions import EmbeddingModelMismatch


def _make(fake_d1_http, fake_vectorize_http, **kw):
    return MemoryDBD1(
        d1=D1Backend(base_url="http://d1.internal", http=fake_d1_http),
        vectorize=VectorizeBackend(
            base_url="http://vectorize.internal", idx="i", http=fake_vectorize_http
        ),
        **kw,
    )


def test_fresh_store_stamps_identity(fake_d1_http, fake_vectorize_http):
    db = _make(
        fake_d1_http,
        fake_vectorize_http,
        sub="u1",
        embedding_dims=768,
        embedding_model="jina-v5",
    )
    assert db.get_store_meta("embedding_dims") == "768"
    assert db.get_store_meta("embedding_model") == "jina-v5"


def test_dims_mismatch_raises(fake_d1_http, fake_vectorize_http):
    _make(
        fake_d1_http,
        fake_vectorize_http,
        sub="u1",
        embedding_dims=768,
        embedding_model="jina-v5",
    )
    with pytest.raises(EmbeddingModelMismatch):
        _make(
            fake_d1_http,
            fake_vectorize_http,
            sub="u1",
            embedding_dims=512,
            embedding_model="other",
        )


def test_reindex_flag_restamps_instead_of_raising(fake_d1_http, fake_vectorize_http):
    _make(
        fake_d1_http,
        fake_vectorize_http,
        sub="u1",
        embedding_dims=768,
        embedding_model="jina-v5",
    )
    db2 = _make(
        fake_d1_http,
        fake_vectorize_http,
        sub="u1",
        embedding_dims=512,
        embedding_model="other",
        reindex_on_model_change=True,
    )
    assert db2.get_store_meta("embedding_dims") == "512"


def test_per_sub_identity_isolation(fake_d1_http, fake_vectorize_http):
    _make(
        fake_d1_http,
        fake_vectorize_http,
        sub="u1",
        embedding_dims=768,
        embedding_model="jina-v5",
    )
    # different sub on the SAME D1 stamps independently -> no false block
    db2 = _make(
        fake_d1_http,
        fake_vectorize_http,
        sub="u2",
        embedding_dims=512,
        embedding_model="other",
    )
    assert db2.get_store_meta("embedding_dims") == "512"
