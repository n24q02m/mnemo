"""Console-script entry for mnemo-mcp (de-host HTTP-only).

Bare invocation starts the HTTP MCP server; subcommands run one-shot
operator actions (auth token hashing, warmup, config bootstrap).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _serve(argv: list[str]) -> int | None:
    from mnemo_mcp.server import main as server_main

    server_main()
    return 0


def _handle_token_hash(args: argparse.Namespace) -> int:
    """Hash a shared-mode token the way hull-core's Authenticator checks it.

    Prints only the hash; the raw token never lands in config.toml.
    """
    import getpass
    import os

    from hull_core.auth.tokens import hash_token

    token = os.environ.get("MNEMO_AUTH_TOKEN") or getpass.getpass("token: ")
    if not token:
        print("mnemo-mcp: empty token", file=sys.stderr)
        return 2
    print(hash_token(token))
    return 0


def _handle_token_verify(args: argparse.Namespace) -> int:
    """Verify a candidate token against a ``scrypt$...`` string."""
    from hull_core.auth.tokens import verify_token

    try:
        ok = verify_token(args.token, args.encoded)
    except Exception as exc:  # hull_core.auth.tokens.TokenHashError
        print(f"mnemo-mcp: {exc}")
        return 2
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


def _handle_warmup(args: argparse.Namespace) -> int:
    from mnemo_mcp.setup_tool import run_warmup

    result = asyncio.run(run_warmup())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


def _handle_config_init(args: argparse.Namespace) -> int:
    from mnemo_mcp.runtime import write_default_config

    path = write_default_config(force=args.force)
    print(f"Wrote {path}")
    return 0


def _version() -> str:
    from mnemo_mcp import __version__

    return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemo-mcp",
        description="mnemo-mcp: HTTP MCP memory server (de-host).",
    )
    parser.add_argument(
        "--version", action="version", version=f"mnemo-mcp {_version()}"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "token-hash",
        help="Hash a shared-mode token for [server] token_hash (reads "
        "MNEMO_AUTH_TOKEN or prompts)",
    ).set_defaults(func=_handle_token_hash)

    v = sub.add_parser("token-verify", help="Verify a token against a hash")
    v.add_argument("token")
    v.add_argument("encoded")
    v.set_defaults(func=_handle_token_verify)

    sub.add_parser(
        "warmup", help="Pre-download the local embedding model / probe cells"
    ).set_defaults(func=_handle_warmup)

    c = sub.add_parser("config-init", help="Write the default config template")
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=_handle_config_init)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "func", None) is not None:
        return args.func(args)
    # Bare invocation (and any leading-dash argv argparse rejects) -> serve.
    return _serve(list(sys.argv[1:])) or 0


if __name__ == "__main__":
    raise SystemExit(main())
