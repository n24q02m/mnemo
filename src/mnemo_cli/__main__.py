"""Thin CLI surface over mnemo_core (TOOL-1, P0).

The CLI only parses arguments and serializes the core's envelope. It never
implements memory logic itself and never invokes the MCP surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from mnemo_core import operations, results, standing
from mnemo_mcp.db import MemoryDB


def _serialize(envelope: dict) -> str:
    return json.dumps(envelope, sort_keys=True, ensure_ascii=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemo-pilot",
        description="Mnemo pilot CLI (capture/recall/reflect/fetch) over the shared domain core",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--db", required=True, help="Path to the SQLite memory DB")
        p.add_argument("--subject", default=None, help="Explicit subject label")

    p_capture = sub.add_parser("capture", help="Store one memory")
    add_common(p_capture)
    p_capture.add_argument("content")
    p_capture.add_argument("--tags", default="", help="Comma-separated tags")
    p_capture.add_argument("--category", default="general")
    p_capture.add_argument("--source", default=None)

    p_recall = sub.add_parser("recall", help="Search a subject's memories")
    add_common(p_recall)
    p_recall.add_argument("query")
    p_recall.add_argument("--k", type=int, default=5)

    p_reflect = sub.add_parser("reflect", help="Bounded cited reflect over retrieval")
    add_common(p_reflect)
    p_reflect.add_argument("query")
    p_reflect.add_argument("--k", type=int, default=5)
    p_reflect.add_argument(
        "--paid",
        action="store_true",
        help="Route the answer through a bounded completion provider "
        "(gateway key from CF_AIG_BASE/CF_AIG_TOKEN or OPENROUTER_API_KEY; "
        "hard-capped)",
    )

    p_fetch = sub.add_parser("fetch", help="Fetch one memory by id")
    add_common(p_fetch)
    p_fetch.add_argument("memory_id")

    p_sref = sub.add_parser(
        "standing-refresh", help="Materialize a standing page via reflect"
    )
    add_common(p_sref)
    p_sref.add_argument("key")
    p_sref.add_argument("question")
    p_sref.add_argument("--k", type=int, default=5)

    p_sread = sub.add_parser(
        "standing-read", help="Cheap read of a standing page with staleness"
    )
    add_common(p_sread)
    p_sread.add_argument("key")

    p_sinv = sub.add_parser(
        "standing-invalidate", help="Materialize a tombstone standing page"
    )
    add_common(p_sinv)
    p_sinv.add_argument("key")
    p_sinv.add_argument("--question", default="")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the taxonomy-mapped process exit code."""
    args = _build_parser().parse_args(argv)
    store = MemoryDB(Path(args.db), embedding_dims=0)
    try:
        if args.command == "capture":
            tags = [t.strip() for t in args.tags.split(",") if t.strip()] or None
            envelope = operations.capture(
                store,
                args.subject,
                args.content,
                tags=tags,
                category=args.category,
                source=args.source,
            )
        elif args.command == "reflect":
            provider = None
            if getattr(args, "paid", False):
                import os

                from mnemo_mcp.providers import BoundedReflectProvider

                api_base = os.getenv("CF_AIG_BASE")
                api_key = os.getenv("CF_AIG_TOKEN") or os.getenv("OPENROUTER_API_KEY")
                if not api_key:
                    envelope = results.err(
                        results.AUTH_DENIED,
                        "--paid requires CF_AIG_TOKEN or OPENROUTER_API_KEY",
                    )
                else:
                    provider = BoundedReflectProvider(
                        model=os.getenv(
                            "MNEMO_REFLECT_MODEL", "openrouter/minimax/minimax-m3:free"
                        ),
                        api_key=api_key,
                        api_base=api_base,
                        cap_usd=float(os.getenv("MNEMO_REFLECT_CAP_USD", "5.00")),
                    )
            if provider is not None or not getattr(args, "paid", False):
                envelope = operations.reflect(
                    store, args.subject, args.query, k=args.k, provider=provider
                )
        elif args.command == "recall":
            envelope = operations.recall(store, args.subject, args.query, k=args.k)
        elif args.command == "standing-refresh":
            envelope = standing.standing_refresh(
                store, args.subject, args.key, args.question, k=args.k
            )
        elif args.command == "standing-read":
            envelope = standing.standing_read(store, args.subject, args.key)
        elif args.command == "standing-invalidate":
            envelope = standing.standing_invalidate(
                store,
                args.subject,
                args.key,
                question=args.question,
            )
        else:
            envelope = operations.fetch(store, args.subject, args.memory_id)
    finally:
        store.close()
    print(_serialize(envelope))
    return results.exit_code(envelope)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
