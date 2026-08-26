"""Console-script entry: mounts the shared mcp_core CLI builder.

Bare invocation and any leading-dash argv (e.g. --http) start the server
exactly as before; subcommands run one-shot operator actions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp_core import build_cli


def _serve(argv: list[str]) -> int | None:
    from mnemo_mcp.server import main as server_main

    server_main()
    return 0


def _configure_auth(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "provider", choices=["google"], help="Credential provider to authorize"
    )
    p.add_argument(
        "--client-id",
        default=None,
        help="BYO OAuth client id (must be paired with --client-secret)",
    )
    p.add_argument("--client-secret", default=None, help="BYO OAuth client secret")


def _handle_auth(args: argparse.Namespace) -> int:
    from mnemo_mcp.setup_tool import run_setup_sync

    # Single-user / local machine only: writes the token via the local store.
    # mnemo_mcp.config.settings is a module-level singleton resolved once at
    # import time -- a BYO client pair can never reach it via os.environ
    # after that point. The pair is threaded through run_setup_sync's
    # client_id/client_secret params instead.
    if args.client_id or args.client_secret:
        from mcp_core.auth import resolve_bundled_client

        from mnemo_mcp.config import _GOOGLE_CLIENT_SPEC

        try:
            resolved = resolve_bundled_client(
                _GOOGLE_CLIENT_SPEC,
                cli_id=args.client_id,
                cli_secret=args.client_secret,
            )
        except ValueError as exc:
            print(f"mnemo-mcp: {exc}", file=sys.stderr)
            return 2
        result = asyncio.run(
            run_setup_sync(
                client_id=resolved.client_id, client_secret=resolved.client_secret
            )
        )
    else:
        result = asyncio.run(run_setup_sync())

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "authenticated" else 1


def _handle_logout(args: argparse.Namespace) -> int:
    from mnemo_mcp.token_store import delete_token, load_token

    if load_token("google_drive") is None:
        print("Nothing to log out (no saved Google Drive token).")
        return 0

    delete_token("google_drive")
    print("Logged out. Google Drive sync token cleared.")
    return 0


def _handle_warmup(args: argparse.Namespace) -> int:
    from mnemo_mcp.setup_tool import run_warmup

    result = asyncio.run(run_warmup())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


def _configure_audit(p: argparse.ArgumentParser) -> None:
    """Attach the `audit` subcommand group onto the parser build_cli hands us."""
    sub = p.add_subparsers(dest="audit_action", required=True)
    v = sub.add_parser("verify", help="Verify the per-tenant audit hash chain")
    v.add_argument("--tenant", required=True)
    v.add_argument("--db-path", default=None)


def _handle_audit_verify(args: argparse.Namespace) -> int:
    import os
    from pathlib import Path

    key_hex_or_raw = os.environ.get("MNEMO_AUDIT_HASH_KEY", "")
    if not key_hex_or_raw:
        print("audit key not configured (MNEMO_AUDIT_HASH_KEY empty)")
        return 2
    from mnemo_mcp.config import settings
    from mnemo_mcp.db import MemoryDB

    db_path = Path(args.db_path).expanduser() if args.db_path else None
    if db_path is None:
        db_path = (
            Path(settings.db_path).expanduser()
            if settings.db_path
            else (Path.home() / ".mnemo-mcp" / "memories.db")
        )
    db = MemoryDB(db_path, embedding_dims=0)
    report = db.verify_audit_chain(args.tenant, {"k1": key_hex_or_raw.encode()})
    if report.ok:
        print(f"VERIFY {args.tenant} OK checked={report.checked}")
        return 0
    print(f"VERIFY {args.tenant} FAIL at seq={report.first_bad_seq}: {report.reason}")
    return 1


def _extras() -> dict:
    return {
        "auth": (_configure_auth, _handle_auth),
        "audit": (_configure_audit, _handle_audit_verify),
        "warmup": _handle_warmup,
        "logout": _handle_logout,
    }


def _version() -> str:
    from mnemo_mcp import __version__

    return __version__


def main() -> int:
    return build_cli("mnemo-mcp", serve=_serve, extra=_extras(), version=_version())(
        None
    )
