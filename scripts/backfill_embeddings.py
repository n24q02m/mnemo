"""Backfill vectors for memories written while embedding was unavailable.

The public ``backfill`` function deliberately depends on a small database and
embedder protocol.  This keeps the operation testable and lets the live
runner provide the same store/backend that the MCP server uses.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from collections.abc import Iterable
from typing import Any

_DEFAULT_EMBEDDING_DIMS = 768


def _run_embedding(embedder: Any, texts: list[str]) -> list[list[float]]:
    """Embed ``texts`` using either the plan's sync or runtime async API."""
    embed = getattr(embedder, "embed", None)
    if callable(embed):
        vectors = embed(texts)
    else:
        embed_texts = getattr(embedder, "embed_texts", None)
        if not callable(embed_texts):
            raise TypeError("embedder must provide embed() or embed_texts()")
        vectors = embed_texts(texts)

    if inspect.isawaitable(vectors):
        vectors = asyncio.run(vectors)
    if not isinstance(vectors, Iterable):
        raise TypeError("embedder returned a non-iterable result")
    return [list(vector) for vector in vectors]


def _load_rows(db: Any, batch_size: int, seen_ids: set[str]) -> list[dict[str, Any]]:
    """Read the next page, using the optional exclusion supported by MemoryDB."""
    rows_without_vectors = db.rows_without_vectors
    try:
        rows = rows_without_vectors(batch_size, exclude_ids=seen_ids)
    except TypeError as exc:
        # The minimal interface in the plan only accepts ``limit``.  Keep that
        # interface usable for fakes and adapters that do not need pagination
        # exclusion; the seen-set below still prevents an infinite loop.
        if "exclude_ids" not in str(exc):
            raise
        rows = rows_without_vectors(batch_size)
    return [dict(row) for row in rows]


def backfill(db: Any, embedder: Any, batch_size: int = 32) -> dict[str, int]:
    """Embed every row without a vector and return bounded run statistics.

    A provider failure is counted for the current usable batch and stops the
    run.  No row from a failed batch is written, so retrying is idempotent.
    Empty content is intentionally skipped because it is not a valid embedding
    input; it is still included in ``scanned``.
    """
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or batch_size < 1
    ):
        raise ValueError("batch_size must be a positive integer")

    scanned = embedded = skipped = failed = 0
    seen_ids: set[str] = set()

    while True:
        rows = _load_rows(db, batch_size, seen_ids)
        fresh_rows = [row for row in rows if str(row.get("id", "")) not in seen_ids]
        if not fresh_rows:
            break
        seen_ids.update(str(row.get("id", "")) for row in fresh_rows)
        scanned += len(fresh_rows)

        usable = [row for row in fresh_rows if str(row.get("content") or "").strip()]
        skipped += len(fresh_rows) - len(usable)
        if not usable:
            continue

        try:
            vectors = _run_embedding(embedder, [str(row["content"]) for row in usable])
        except Exception:
            failed += len(usable)
            break

        if len(vectors) != len(usable):
            failed += len(usable)
            break

        batch_failed = False
        for row, vector in zip(usable, vectors, strict=True):
            if not vector:
                failed += 1
                batch_failed = True
                continue
            try:
                db.write_vector(row["id"], vector)
            except Exception:
                failed += 1
                batch_failed = True
                continue
            embedded += 1

        if batch_failed:
            break

        if len(rows) < batch_size:
            break

    return {
        "scanned": scanned,
        "embedded": embedded,
        "skipped": skipped,
        "failed": failed,
    }


def main() -> int:
    """Run a local-store backfill from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--model", default=None, help="Embedding model override")
    parser.add_argument("--dimensions", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    from mnemo_mcp.config import settings
    from mnemo_mcp.db import MemoryDB
    from mnemo_mcp.embedder import CloudEmbeddingBackend

    embedding_dims = (
        args.dimensions or settings.embedding_dims or _DEFAULT_EMBEDDING_DIMS
    )
    db = MemoryDB(args.db, embedding_dims=embedding_dims)
    embedder = CloudEmbeddingBackend(model=args.model)
    result = backfill(db, embedder, batch_size=args.batch_size)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
