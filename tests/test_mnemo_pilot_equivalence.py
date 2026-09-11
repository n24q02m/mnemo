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
import re
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from mnemo_cli.__main__ import main as cli_main
from mnemo_core import operations, results
from mnemo_mcp import pilot_tools
from mnemo_mcp.db import MemoryDB

_ID_RE = re.compile(r"[0-9a-f]{32}")


def _canonical(envelope: dict) -> str:
    """Canonical form with volatile fields (fresh ids, timestamps) masked.

    Each surface runs against its own store file, so freshly generated ids
    can never match -- including ids embedded inside message strings (e.g.
    "memory '<id>' not found"); the equivalence property is byte-equality
    modulo those.
    """

    def scrub(obj: object) -> object:
        if isinstance(obj, str):
            return _ID_RE.sub("<id>", obj)
        if isinstance(obj, dict):
            return {
                k: (
                    "<id>"
                    if k == "id"
                    else (
                        "<ts>"
                        if k in ("created_at", "updated_at", "last_accessed")
                        # Hybrid score folds in recency, which is derived from
                        # the store-local capture clock: two identical seeds
                        # capture microseconds apart, so full precision is
                        # clock noise, not a surface difference. Scorer math
                        # itself is covered by the retrieval suites.
                        else ("<score>" if k == "score" else scrub(v))
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
    ("reflect", {"query": "   "}),  # VALIDATION
    ("reflect", {"query": "deploy checklist"}),  # abstention on empty store
    (
        "reflect",
        {
            "query": "deploy checklist",
            "seed": [{"content": "deploy checklist for pilot", "tags": ["ops"]}],
        },
    ),
]

_HANDLERS = {
    "capture": pilot_tools.pilot_capture,
    "recall": pilot_tools.pilot_recall,
    "fetch": pilot_tools.pilot_fetch,
    "reflect": pilot_tools.pilot_reflect,
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
        for seed in args.get("seed", []):
            seed_args = [
                "capture",
                "--db",
                str(cli_db),
                "--subject",
                "alice",
                seed["content"],
            ]
            seed_out, seed_code = _run_cli(seed_args, capsys)
            assert seed_code == 0, seed_out
            mcp_seed = pilot_tools.pilot_capture(mcp_store, "alice", seed)
            assert mcp_seed["ok"] is True, mcp_seed
        if op == "capture":
            cli_args += [args["content"]]
            if "tags" in args:
                cli_args += ["--tags", ",".join(args["tags"])]
            if "category" in args and args["category"] != "general":
                cli_args += ["--category", args["category"]]
        elif op == "recall":
            cli_args += [args["query"], "--k", str(args.get("k", 5))]
        elif op == "reflect":
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


def test_subject_isolation_envelopes_are_byte_equal_both_surfaces(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """MN-3 wave 3: the subject contract observes identical envelopes on the
    CLI and MCP surfaces. Both stores start from the same seeded state (one
    alice row, one legacy NULL-subject row); every recall/fetch subject case
    must produce byte-equal envelopes across surfaces.
    """
    cli_db = tmp_path / "iso-cli.db"
    mcp_store = MemoryDB(tmp_path / "iso-mcp.db", embedding_dims=0)
    cli_seed = MemoryDB(cli_db, embedding_dims=0)
    operations.capture(cli_seed, "alice", "alice deploy checklist")
    cli_seed.add(content="legacy blob", category="general")
    cli_seed.close()
    operations.capture(mcp_store, "alice", "alice deploy checklist")
    mcp_store.add(content="legacy blob", category="general")

    recall_cases = [
        ("alice", {"query": "deploy checklist", "k": 5}),
        ("bob", {"query": "deploy checklist", "k": 5}),
        ("alice", {"query": "legacy blob", "k": 5}),
        (None, {"query": "legacy blob", "k": 5}),
    ]
    for i, (subject, mcp_args) in enumerate(recall_cases):
        cli_args = ["recall", "--db", str(cli_db)]
        if subject is not None:
            cli_args += ["--subject", subject]
        cli_args += [str(mcp_args["query"]), "--k", str(mcp_args["k"])]
        cli_out, cli_code = _run_cli(cli_args, capsys)
        cli_env = json.loads(cli_out)
        mcp_env = _HANDLERS["recall"](mcp_store, subject, mcp_args)
        assert _canonical(cli_env) == _canonical(mcp_env), f"recall case {i}"
        assert (cli_env["ok"] is True) == (cli_code == 0)

    # Each store holds its own rows (ids differ per surface); resolve the
    # equivalent target id per surface, then compare canonical envelopes --
    # _canonical masks ids, so surface equality still holds.
    def _target_id(store: MemoryDB, subject: str | None, query: str) -> str:
        matches = operations.recall(store, subject, query)["data"]["matches"]
        assert matches, "seed row missing"
        return matches[0]["id"]

    # Resolve both surfaces' target ids up front and symmetrically: search
    # bumps access stats, so an asymmetric lookup order would itself shift
    # the access_count the later fetch envelopes expose.
    cli_prober = MemoryDB(cli_db, embedding_dims=0)
    cli_alice = _target_id(cli_prober, "alice", "deploy checklist")
    cli_legacy = _target_id(cli_prober, None, "legacy blob")
    cli_prober.close()
    mcp_alice = _target_id(mcp_store, "alice", "deploy checklist")
    mcp_legacy = _target_id(mcp_store, None, "legacy blob")

    fetch_cases = [
        # (query naming the row, subject, expected error code or None)
        ("deploy checklist", "bob", results.NOT_FOUND),
        ("legacy blob", "alice", results.NOT_FOUND),
        ("deploy checklist", "alice", None),
        ("legacy blob", None, None),
    ]
    for j, (query, subject, want_code) in enumerate(fetch_cases):
        if query.startswith("deploy"):
            cli_id, mcp_id = cli_alice, mcp_alice
        else:
            cli_id, mcp_id = cli_legacy, mcp_legacy
        cli_args = ["fetch", "--db", str(cli_db)]
        if subject is not None:
            cli_args += ["--subject", subject]
        cli_args += [cli_id]
        cli_out, cli_code = _run_cli(cli_args, capsys)
        cli_env = json.loads(cli_out)
        mcp_env = _HANDLERS["fetch"](mcp_store, subject, {"memory_id": mcp_id})
        assert _canonical(cli_env) == _canonical(mcp_env), f"fetch case {j}"
        if want_code is None:
            assert cli_env["ok"] is True and mcp_env["ok"] is True
        else:
            assert cli_env["error"]["code"] == want_code
            assert mcp_env["error"]["code"] == want_code

    # MN-4: reflect obeys the same subject contract on both surfaces.
    reflect_cases = [
        ("alice", {"query": "deploy checklist", "k": 5}, False),
        ("bob", {"query": "deploy checklist", "k": 5}, True),
        ("alice", {"query": "legacy blob", "k": 5}, True),
        (None, {"query": "legacy blob", "k": 5}, False),
    ]
    for rj, (subject, mcp_args, want_abstain) in enumerate(reflect_cases):
        cli_args = ["reflect", "--db", str(cli_db)]
        if subject is not None:
            cli_args += ["--subject", subject]
        cli_args += [str(mcp_args["query"]), "--k", str(mcp_args["k"])]
        cli_out, cli_code = _run_cli(cli_args, capsys)
        cli_env = json.loads(cli_out)
        mcp_env = _HANDLERS["reflect"](mcp_store, subject, mcp_args)
        assert _canonical(cli_env) == _canonical(mcp_env), f"reflect case {rj}"
        assert (cli_env["ok"] is True) == (cli_code == 0)
        for env in (cli_env, mcp_env):
            assert env["data"]["abstained"] is want_abstain
            assert env["data"]["cost"] == {
                "model_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
            if not want_abstain:
                assert env["data"]["answer"] in [
                    c["content"] for c in env["data"]["citations"]
                ]
    mcp_store.close()


@pytest.fixture
def two_stores(tmp_path: Path) -> Generator[tuple[MemoryDB, MemoryDB]]:
    cli_store = MemoryDB(tmp_path / "cli.db", embedding_dims=0)
    mcp_store = MemoryDB(tmp_path / "mcp.db", embedding_dims=0)
    yield cli_store, mcp_store
    cli_store.close()
    mcp_store.close()
