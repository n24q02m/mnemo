"""Console-script entry for mnemo (de-host HTTP-only).

Bare invocation starts the HTTP MCP server; subcommands run one-shot
operator actions (auth token hashing, warmup, config bootstrap and edits).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _serve(argv: list[str]) -> int | None:
    from mnemo.server import main as server_main

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
        print("mnemo: empty token", file=sys.stderr)
        return 2
    print(hash_token(token))
    return 0


def _handle_token_verify(args: argparse.Namespace) -> int:
    """Verify a candidate token against a ``scrypt$...`` string."""
    from hull_core.auth.tokens import verify_token

    try:
        ok = verify_token(args.token, args.encoded)
    except Exception as exc:  # hull_core.auth.tokens.TokenHashError
        print(f"mnemo: {exc}")
        return 2
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


def _handle_warmup(args: argparse.Namespace) -> int:
    from mnemo.setup_tool import run_warmup

    result = asyncio.run(run_warmup())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


def _handle_config_init(args: argparse.Namespace) -> int:
    from mnemo.runtime import write_default_config

    try:
        path = write_default_config(force=args.force)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {path}")
    return 0


def _handle_config(args: argparse.Namespace) -> int:
    """``mnemo config init|path|show|get|set`` -- same surface as hull/wet/crg.

    The edits themselves come from ``hull_core.config.tomledit`` so quoting,
    secret masking and error text are identical across the stack.
    """
    from hull_core.config import tomledit
    from hull_core.config.settings import ConfigError

    from mnemo.runtime import CONFIG_TEMPLATE, mnemo_config_path, write_default_config

    path = mnemo_config_path()
    action = args.config_action
    if action == "init":
        try:
            written = write_default_config(force=args.force)
        except FileExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"Wrote {written}")
        return 0
    if action == "path":
        print(path)
        return 0
    if action == "show":
        print(path.read_text(encoding="utf-8") if path.is_file() else CONFIG_TEMPLATE, end="")
        return 0
    if action == "get":
        try:
            value = tomledit.get_value(path, args.key)
        except (ConfigError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if tomledit.looks_secret(args.key):
            print("*** (value not echoed)")
        else:
            print(tomledit.format_value(value))
        return 0
    try:
        tomledit.set_value(path, args.key, args.value)
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    shown = (
        "*** (value not echoed)"
        if tomledit.looks_secret(args.key)
        else tomledit.toml_scalar(args.value)
    )
    print(f"set {args.key} = {shown} in {path}")
    return 0


def _version() -> str:
    from mnemo import __version__

    return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemo",
        description="mnemo: HTTP MCP memory server (de-host).",
    )
    parser.add_argument("--version", action="version", version=f"mnemo {_version()}")
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

    cfg = sub.add_parser("config", help="Config file utilities (init, path, show, get, set)")
    cfg_sub = cfg.add_subparsers(dest="config_action", required=True)
    cfg_init = cfg_sub.add_parser("init", help="Write the default config template (--force)")
    cfg_init.add_argument("--force", action="store_true")
    cfg_init.set_defaults(func=_handle_config)
    cfg_sub.add_parser("path", help="Print the config file path").set_defaults(
        func=_handle_config
    )
    cfg_sub.add_parser("show", help="Print the config file (template if absent)").set_defaults(
        func=_handle_config
    )
    cfg_get = cfg_sub.add_parser("get", help="Print one value (dotted key, e.g. server.port)")
    cfg_get.add_argument("key")
    cfg_get.set_defaults(func=_handle_config)
    cfg_set = cfg_sub.add_parser("set", help="Set one value in place, keeping comments")
    cfg_set.add_argument("key")
    cfg_set.add_argument("value")
    cfg_set.set_defaults(func=_handle_config)

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
