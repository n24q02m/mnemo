"""Record the at-rest encryption state of the store in ``store_meta``.

Every store gets an ``encryption`` key in ``store_meta``. A store that was
created before at-rest encryption existed is plaintext, so the migration
writes ``none``. An encrypted store is created by ``MemoryDB`` with the
scheme, key derivation parameters, salt and key-check value already written
before migrations run, so ``INSERT OR IGNORE`` leaves them untouched.

The key itself is never stored. See ``mnemo.crypto`` for the format of the
other ``encryption_*`` keys.

Downgrading past this revision would leave an encrypted store that older
releases read as plaintext, so the downgrade refuses to run until the store
has been decrypted with ``n24q02m-mnemo decrypt``.

Revision ID: mem_008_encryption_meta
Revises: mem_007_confidence
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mem_008_encryption_meta"
down_revision: str | Sequence[str] | None = "mem_007_confidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEME_KEY = "encryption"
_SCHEME_NONE = "none"


def upgrade() -> None:
    """Mark the store as plaintext unless an encryption scheme is recorded."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS store_meta ("
            "key TEXT PRIMARY KEY NOT NULL, value TEXT)"
        )
    )
    bind.execute(
        sa.text("INSERT OR IGNORE INTO store_meta (key, value) VALUES (:key, :value)"),
        {"key": _SCHEME_KEY, "value": _SCHEME_NONE},
    )


def downgrade() -> None:
    """Remove the plaintext marker; refuse while the store is encrypted."""
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT value FROM store_meta WHERE key = :key"),
        {"key": _SCHEME_KEY},
    ).fetchone()
    if row is not None and row[0] not in (None, _SCHEME_NONE):
        raise RuntimeError(
            "this store is encrypted; run `n24q02m-mnemo decrypt` first, then downgrade"
        )
    bind.execute(
        sa.text("DELETE FROM store_meta WHERE key = :key"), {"key": _SCHEME_KEY}
    )
