"""Pin the console-script mapping declared in pyproject.toml (ADR 0001)."""

import tomllib
from pathlib import Path

SCRIPTS = tomllib.loads(
    (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
        encoding="utf-8"
    )
)["project"]["scripts"]


def test_canonical_and_legacy_names_start_the_server():
    assert SCRIPTS["n24q02m-mnemo"] == "mnemo.cli:main"
    assert SCRIPTS["mnemo-mcp"] == "mnemo.cli:main"


def test_short_names_are_cli_first():
    assert SCRIPTS["mnemo"] == "mnemo_cli.__main__:main"
    assert SCRIPTS["mnemo-pilot"] == "mnemo_cli.__main__:main"
