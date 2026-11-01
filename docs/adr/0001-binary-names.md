# ADR 0001: Distribution and Binary Executable Names for mnemo

## Status
Accepted (amended: `n24q02m-mnemo` is the MCP server entry point)

## Context
Following the stack stabilization plan (Q3, Q13), distribution packages across the n24q02m stack are renamed to use the standard publisher prefix `n24q02m-*` on PyPI to prevent namespace confusion and clarify ownership.

mnemo ships two distinct surfaces:
1. The MCP server (Streamable HTTP) with operator subcommands (`config-init`, `warmup`, `token-hash`, `token-verify`): `mnemo.cli:main`.
2. The CLI-first memory surface that talks straight to the memory DB and never starts a server: `mnemo_cli.__main__:main`.

Existing automation expecting the historical server binary name `mnemo-mcp` must keep working.

## Decision
Entry points in `pyproject.toml`:
- `n24q02m-mnemo` -> `mnemo.cli:main`: canonical server executable, matches the PyPI distribution, so `uvx n24q02m-mnemo` serves MCP without `--from`.
- `mnemo-mcp` -> `mnemo.cli:main`: backward-compatible alias of the server for existing configurations.
- `mnemo` -> `mnemo_cli.__main__:main`: short CLI-first command (no server).
- `mnemo-pilot` -> `mnemo_cli.__main__:main`: alias of `mnemo`.

## Consequences
- PyPI package name is `n24q02m-mnemo`.
- An earlier revision pointed `n24q02m-mnemo` at the CLI-first entry, so `uvx n24q02m-mnemo` never served MCP; `tests/test_entry_points.py` pins the mapping.
- Historical configurations referencing `mnemo-mcp` remain supported.
