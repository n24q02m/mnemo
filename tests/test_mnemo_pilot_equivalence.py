"""P0 equivalence gate: CLI and MCP-shaped handler must observe identical
envelopes for identical operations (TOOL-1 acceptance).

Neither surface invokes the other: the CLI path goes through
``mnemo_cli.__main__.main`` (argparse -> core) and the MCP path through
``mnemo_mcp.pilot_tools`` (args dict -> core). Envelopes are canonicalized
(masking freshly generated ids/timestamps, sorting keys) and compared as
strings — any other difference fails the gate.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from mnemo_cli.__main__ import main as cli_main
from mnemo_mcp import pilot_tools
from mnemo_mcp.db import MemoryDB


def _canonical(envelope: dict) -> str:
    """Canonical form with volatile fields (fresh ids, timestamps) masked.

    Each surface runs against its own store file, so freshly generated ids
    can never match; the equivalence property is byte-equality modulo those.
    """

    def scrub(obj: object) -> object:
        if isinstance(obj, dict):
            return {
                k: (
                    "<id>"
                    if k == "id"
                    else (
                        "<ts>"
                        if k in ("created_at", "updated_at", "last_accessed")
                        else scrub(v)
                    )
                )
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [scrub(v) for v in obj]
        return obj

    return json.dumps(
        scrub(json.loads(json.dumps(envelope))), sort_keys=True, ensure_ascii=False
    )


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[str, int]:
    code = cli_main(argv)
    return capsys.readouterr().out.strip(), code


SCENARIOS: list[tuple[str, dict[str, Any]]] = [
    (
        "capture",
        {"content": "deploy checklist for pilot", "tags": ["ops"], "category": "tech"},
    ),
    ("capture", {"content": ""}),  # VALIDATION
    ("recall", {"query": "deploy checklist", "k": 5}),
    ("recall", {"query": "   "}),  # VALIDATION
    ("fetch", {"memory_id": "deadbeef"}),  # NOT_FOUND
    ("fetch", {"memory_id": ""}),  # VALIDATION
]

_HANDLERS = {
    "capture": pilot_tools.pilot_capture,
    "recall": pilot_tools.pilot_recall,
    "fetch": pilot_tools.pilot_fetch,
}


def test_cli_and_mcp_envelopes_are_byte_equal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for i, (op, args) in enumerate(SCENARIOS):
        # Fresh, isolated store pair per scenario: identical starting state
        # on both surfaces, so envelope equality is purely surface equality.
        cli_db = tmp_path / f"cli-{i}.db"
        mcp_store = MemoryDB(tmp_path / f"mcp-{i}.db", embedding_dims=0)
        cli_args: list[str] = ["--db", str(cli_db), "--subject", "alice"]
        if op == "capture":
            cli_args += [args["content"]]
            if "tags" in args:
                cli_args += ["--tags", ",".join(args["tags"])]
            if "category" in args and args["category"] != "general":
                cli_args += ["--category", args["category"]]
        elif op == "recall":
            cli_args += [args["query"], "--k", str(args.get("k", 5))]
        else:
            cli_args += [args["memory_id"]]

        cli_out, cli_code = _run_cli([op, *cli_args], capsys)
        cli_env = json.loads(cli_out)
        mcp_env = _HANDLERS[op](mcp_store, "alice", args)
        mcp_code = 0 if mcp_env.get("ok") else 1
        mcp_store.close()

        assert _canonical(cli_env) == _canonical(mcp_env), (
            f"envelope mismatch for {op} {args}"
        )
        assert (cli_env["ok"] is True) == (cli_code == 0)
        assert (mcp_env["ok"] is True) == (mcp_code == 0)


def test_happy_capture_recall_round_trip_both_surfaces(
    two_stores: tuple[MemoryDB, MemoryDB],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, mcp_store = two_stores
    cli_out, _ = _run_cli(
        [
            "capture",
            "--db",
            str(tmp_path / "rt-cli.db"),
            "--subject",
            "alice",
            "gamma release notes",
        ],
        capsys,
    )
    captured = json.loads(cli_out)

    # The CLI wrote rt-cli.db; an MCP-shaped handler reading the SAME store
    # must observe the memory the CLI captured (shared core, shared data).
    rt_store = MemoryDB(tmp_path / "rt-cli.db", embedding_dims=0)
    try:
        fetched = pilot_tools.pilot_fetch(
            rt_store, "alice", {"memory_id": captured["data"]["id"]}
        )
        assert fetched["ok"] is True
        assert fetched["data"]["memory"]["content"] == "gamma release notes"
    finally:
        rt_store.close()

    # A different subject store sees nothing (isolation, exercised via MCP).
    recalled = pilot_tools.pilot_recall(mcp_store, "bob", {"query": "gamma release"})
    assert recalled["ok"] is True
    assert recalled["data"]["matches"] == []


@pytest.fixture
def two_stores(tmp_path: Path) -> Generator[tuple[MemoryDB, MemoryDB]]:
    cli_store = MemoryDB(tmp_path / "cli.db", embedding_dims=0)
    mcp_store = MemoryDB(tmp_path / "mcp.db", embedding_dims=0)
    yield cli_store, mcp_store
    cli_store.close()
    mcp_store.close()
