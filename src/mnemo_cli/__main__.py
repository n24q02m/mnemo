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

from mnemo.db import MemoryDB
from mnemo_core import operations, results, standing


def _serialize(envelope: dict) -> str:
    return json.dumps(envelope, sort_keys=True, ensure_ascii=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemo",
        description="mnemo: CLI-first memory surface (capture/recall/reflect/fetch) "
        "over the shared domain core",
    )
    from mnemo import __version__

    parser.add_argument("--version", action="version", version=f"mnemo {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=None,
            help="Path to the SQLite memory DB (defaults to active profile store)",
        )
        p.add_argument(
            "--profile",
            default=None,
            help="Named profile under ~/.n24q02m/mnemo/profiles/<name>",
        )
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
    p_recall.add_argument(
        "--compact",
        action="store_true",
        help="Return progressive-disclosure compact index entries (id, snippet, score)",
    )
    p_recall.add_argument(
        "--context",
        action="append",
        default=None,
        help="Preceding turn context for coreference resolution (repeatable)",
    )
    p_recall.add_argument("--since", default=None, help="ISO start timestamp bound")
    p_recall.add_argument("--until", default=None, help="ISO end timestamp bound")

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

    p_forget = sub.add_parser(
        "forget", help="Forget (soft-archive or hard-delete) one memory"
    )
    add_common(p_forget)
    p_forget.add_argument("memory_id")
    p_forget.add_argument(
        "--hard",
        action="store_true",
        help="Permanently delete instead of soft-archiving",
    )

    p_tl = sub.add_parser("timeline", help="Show chronological memory timeline")
    add_common(p_tl)
    p_tl.add_argument("--entity", default=None, help="Filter by entity name or text")
    p_tl.add_argument("--since", default=None, help="ISO start timestamp bound")
    p_tl.add_argument("--until", default=None, help="ISO end timestamp bound")
    p_tl.add_argument("--limit", type=int, default=50)
    p_tl.add_argument(
        "--active-only",
        action="store_true",
        help="Exclude superseded and archived entries",
    )

    p_graph = sub.add_parser("graph", help="Show entity graph and evolution timeline")
    add_common(p_graph)
    p_graph.add_argument("entity_query")
    p_graph.add_argument("--limit", type=int, default=50)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the taxonomy-mapped process exit code."""
    args = _build_parser().parse_args(argv)
    if args.profile:
        import os

        from mnemo.keys import reset_credential_cache
        from mnemo.runtime import reset_settings_cache

        os.environ["MNEMO_PROFILE"] = args.profile
        reset_settings_cache()
        reset_credential_cache()
    if args.db:
        db_path = Path(args.db)
    else:
        from mnemo.config import Settings

        db_path = Settings().get_db_path()
    store = MemoryDB(db_path, embedding_dims=0)
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

                from mnemo.providers import BoundedReflectProvider
                from mnemo.runtime import cell_configured

                api_key = os.getenv("HULL_CHAT_API_KEY")
                if not cell_configured("chat") and not api_key:
                    envelope = results.err(
                        results.AUTH_DENIED,
                        "--paid requires the [models.chat] cell "
                        "(api_key in ~/.mnemo/config.toml or HULL_CHAT_API_KEY)",
                    )
                else:
                    provider = BoundedReflectProvider(
                        model=os.getenv("MNEMO_REFLECT_MODEL", ""),
                        api_key=api_key or "",
                        cap_usd=float(os.getenv("MNEMO_REFLECT_CAP_USD", "5.00")),
                    )
            if provider is not None or not getattr(args, "paid", False):
                envelope = operations.reflect(
                    store, args.subject, args.query, k=args.k, provider=provider
                )
        elif args.command == "recall":
            envelope = operations.recall(
                store,
                args.subject,
                args.query,
                k=args.k,
                context=args.context,
                compact=args.compact,
                since=args.since,
                until=args.until,
            )
        elif args.command == "forget":
            envelope = operations.forget(
                store, args.subject, args.memory_id, hard=args.hard
            )
        elif args.command == "timeline":
            envelope = operations.timeline(
                store,
                args.subject,
                entity=args.entity,
                since=args.since,
                until=args.until,
                include_superseded=not args.active_only,
                limit=args.limit,
            )
        elif args.command == "graph":
            envelope = operations.entity_graph(
                store, args.subject, args.entity_query, limit=args.limit
            )
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
