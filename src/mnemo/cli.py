"""Console-script entry for mnemo (de-host HTTP-only).

Bare invocation starts the HTTP MCP server; subcommands run one-shot
operator actions (auth token hashing, warmup, config bootstrap and edits).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


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
        print(
            path.read_text(encoding="utf-8") if path.is_file() else CONFIG_TEMPLATE,
            end="",
        )
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


def _handle_mcp(args: argparse.Namespace) -> int:
    from mnemo.server import run_server_blocking, run_stdio

    if args.http:
        run_server_blocking(host=args.host, port=args.port)
    else:
        run_stdio()
    return 0


def _store_path(args: argparse.Namespace) -> Path:
    """Resolve the store for ``encrypt``/``decrypt``: ``--db`` or a namespace."""
    from mnemo.runtime import db_path_for_namespace

    if args.db:
        return Path(args.db)
    return db_path_for_namespace(args.namespace or "default")


def _read_encryption_key(confirm: bool) -> str | None:
    """Key from MNEMO_ENCRYPTION_KEY, else from a prompt (twice when confirming).

    Prints the reason and returns None when no usable key was given.
    """
    import getpass
    import os

    from mnemo.crypto import ENCRYPTION_KEY_ENV

    value = os.environ.get(ENCRYPTION_KEY_ENV, "")
    if value.strip():
        return value
    value = getpass.getpass(f"{ENCRYPTION_KEY_ENV}: ")
    if not value.strip():
        print("mnemo: empty key", file=sys.stderr)
        return None
    if confirm and getpass.getpass("repeat the key: ") != value:
        print("mnemo: the keys do not match", file=sys.stderr)
        return None
    return value


def _handle_store_rewrite(args: argparse.Namespace) -> int:
    """``mnemo encrypt`` / ``mnemo decrypt``: rewrite a stopped store in place."""
    from mnemo import store_encryption
    from mnemo.crypto import ENCRYPTION_KEY_ENV
    from mnemo.exceptions import EncryptionError, StoreRewriteError

    encrypt = args.command == "encrypt"
    try:
        path = _store_path(args)
    except ValueError as exc:
        print(f"mnemo: {exc}", file=sys.stderr)
        return 2
    key = _read_encryption_key(confirm=encrypt)
    if key is None:
        return 2
    try:
        if encrypt:
            result = store_encryption.encrypt_store(
                path, key, drop_graph=args.drop_graph
            )
        else:
            result = store_encryption.decrypt_store(path, key)
    except StoreRewriteError as exc:
        print(f"mnemo: {exc}", file=sys.stderr)
        return 1
    except (EncryptionError, FileNotFoundError) as exc:
        print(f"mnemo: {exc}", file=sys.stderr)
        return 2

    if result.action == "already-encrypted":
        print(f"{path} is already encrypted with this key; nothing to do")
        return 0
    if result.action == "not-encrypted":
        print(f"{path} is not encrypted; nothing to do")
        return 0
    verb = "Encrypted" if encrypt else "Decrypted"
    print(f"{verb} {path}: {result.memories} memories, {result.archived} archived rows")
    if result.graph_rows_dropped:
        print(f"Dropped {result.graph_rows_dropped} knowledge-graph rows")
    if encrypt:
        print(
            f"Plaintext backup: {result.backup_path}\n"
            "This backup is NOT encrypted. Check that the server starts with "
            f"{ENCRYPTION_KEY_ENV} set, then delete it securely."
        )
        if result.plaintext_copies:
            print(
                "Copies made earlier by schema migrations, which may hold "
                "plaintext too; delete them securely as well:"
            )
            for copy in result.plaintext_copies:
                print(f"  {copy}")
    else:
        print(
            f"Backup of the encrypted store: {result.backup_path}\n"
            f"Unset {ENCRYPTION_KEY_ENV} before starting the server again."
        )
    return 0


def _version() -> str:
    from mnemo import __version__

    return __version__


def build_parser() -> argparse.ArgumentParser:
    profile_parent = argparse.ArgumentParser(add_help=False)
    profile_parent.add_argument(
        "--profile",
        default=argparse.SUPPRESS,
        help="Named profile under ~/.n24q02m/mnemo/profiles/<name>",
    )
    parser = argparse.ArgumentParser(
        prog="mnemo",
        description="mnemo: MCP memory server (stdio/HTTP + operator CLI).",
        parents=[profile_parent],
    )
    parser.add_argument("--version", action="version", version=f"mnemo {_version()}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "token-hash",
        parents=[profile_parent],
        help="Hash a shared-mode token for [server] token_hash (reads "
        "MNEMO_AUTH_TOKEN or prompts)",
    ).set_defaults(func=_handle_token_hash)

    v = sub.add_parser(
        "token-verify", parents=[profile_parent], help="Verify a token against a hash"
    )
    v.add_argument("token")
    v.add_argument("encoded")
    v.set_defaults(func=_handle_token_verify)

    sub.add_parser(
        "warmup",
        parents=[profile_parent],
        help="Pre-download the local embedding model / probe cells",
    ).set_defaults(func=_handle_warmup)

    c = sub.add_parser(
        "config-init",
        parents=[profile_parent],
        help="Write the default config template",
    )
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=_handle_config_init)

    cfg = sub.add_parser(
        "config",
        parents=[profile_parent],
        help="Config file utilities (init, path, show, get, set)",
    )
    cfg_sub = cfg.add_subparsers(dest="config_action", required=True)
    cfg_init = cfg_sub.add_parser(
        "init",
        parents=[profile_parent],
        help="Write the default config template (--force)",
    )
    cfg_init.add_argument("--force", action="store_true")
    cfg_init.set_defaults(func=_handle_config)
    cfg_sub.add_parser(
        "path", parents=[profile_parent], help="Print the config file path"
    ).set_defaults(func=_handle_config)
    cfg_sub.add_parser(
        "show",
        parents=[profile_parent],
        help="Print the config file (template if absent)",
    ).set_defaults(func=_handle_config)
    cfg_get = cfg_sub.add_parser(
        "get",
        parents=[profile_parent],
        help="Print one value (dotted key, e.g. server.port)",
    )
    cfg_get.add_argument("key")
    cfg_get.set_defaults(func=_handle_config)
    cfg_set = cfg_sub.add_parser(
        "set",
        parents=[profile_parent],
        help="Set one value in place, keeping comments",
    )
    cfg_set.add_argument("key")
    cfg_set.add_argument("value")
    cfg_set.set_defaults(func=_handle_config)

    mcp_parser = sub.add_parser(
        "mcp",
        parents=[profile_parent],
        help="Run MCP server (stdio by default; pass --http for Streamable HTTP)",
    )
    mcp_parser.add_argument(
        "--http",
        action="store_true",
        help="Serve Streamable HTTP instead of stdio",
    )
    mcp_parser.add_argument("--host", default=None, help="Bind host for --http")
    mcp_parser.add_argument(
        "--port", type=int, default=None, help="Bind port for --http"
    )
    mcp_parser.set_defaults(func=_handle_mcp)

    for name, help_text in (
        ("encrypt", "Encrypt a stopped store in place (key: MNEMO_ENCRYPTION_KEY)"),
        ("decrypt", "Decrypt an encrypted store in place, back to plaintext"),
    ):
        rewrite = sub.add_parser(name, parents=[profile_parent], help=help_text)
        target = rewrite.add_mutually_exclusive_group()
        target.add_argument("--db", default=None, help="Path of the store file")
        target.add_argument(
            "--namespace",
            default=None,
            help="Per-namespace store under the mnemo config dir (default: default)",
        )
        if name == "encrypt":
            rewrite.add_argument(
                "--drop-graph",
                action="store_true",
                help="Delete knowledge-graph rows, which encryption does not cover",
            )
        rewrite.set_defaults(func=_handle_store_rewrite)

    def _delegate_core(core_args: argparse.Namespace) -> int:
        from mnemo_cli.__main__ import main as core_main

        return core_main(getattr(core_args, "_raw_argv", None))

    for name, help_text in (
        ("capture", "Store one memory via domain core"),
        ("recall", "Search a subject's memories"),
        ("fetch", "Fetch one memory by id"),
        ("reflect", "Bounded cited reflect over retrieval"),
        ("forget", "Forget (soft-archive or hard-delete) one memory"),
        ("timeline", "Show chronological memory timeline"),
        ("graph", "Show entity graph and evolution timeline"),
    ):
        delegated = sub.add_parser(name, parents=[profile_parent], help=help_text)
        delegated.add_argument("_rest", nargs=argparse.REMAINDER)
        delegated.set_defaults(func=_delegate_core)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:]) if argv is None else list(argv)
    args, unknown = parser.parse_known_args(raw_argv)
    if getattr(args, "command", None) in {
        "capture",
        "recall",
        "fetch",
        "reflect",
        "forget",
        "timeline",
        "graph",
    }:
        rest = list(getattr(args, "_rest", []) or [])
        forwarded = [args.command, *unknown, *rest]
        if getattr(args, "profile", None):
            forwarded.extend(["--profile", args.profile])
        args._raw_argv = forwarded
        return args.func(args)
    if unknown:
        parser.parse_args(raw_argv)
    profile = getattr(args, "profile", None)
    if profile:
        import os

        from mnemo.keys import reset_credential_cache
        from mnemo.runtime import reset_settings_cache

        os.environ["MNEMO_PROFILE"] = profile
        reset_settings_cache()
        reset_credential_cache()
    if getattr(args, "func", None) is not None:
        return args.func(args)
    # Bare invocation (and any leading-dash argv argparse rejects) -> serve.
    return _serve(raw_argv) or 0


if __name__ == "__main__":
    raise SystemExit(main())
