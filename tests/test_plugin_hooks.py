"""The plugin manifest must wire every hook to the script it ships.

``hooks/hooks.json`` is what turns ``hooks/*.sh`` into live hooks: the host runs
exactly the commands declared there, so a renamed script or a stale path leaves
the hook silently dead -- no error, just no run. Mnemo shipped both hook scripts
with no test at all; these resolve every declared command against the repo so
that gap fails loudly instead.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "hooks"
HOOKS_MANIFEST = HOOKS_DIR / "hooks.json"
PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"
SESSION_START_HOOK = "hooks/session-start.sh"


def _commands() -> list[str]:
    manifest = json.loads(HOOKS_MANIFEST.read_text(encoding="utf-8"))
    return [
        hook["command"]
        for groups in manifest["hooks"].values()
        for group in groups
        for hook in group["hooks"]
        if hook["type"] == "command"
    ]


def _script_paths() -> list[str]:
    """Repo-relative script paths a command would execute, quotes removed."""
    paths: list[str] = []
    for command in _commands():
        for token in shlex.split(command):
            if token.startswith(f"{PLUGIN_ROOT_VAR}/"):
                paths.append(token.removeprefix(f"{PLUGIN_ROOT_VAR}/"))
    return paths


def test_manifest_wires_the_session_start_hook():
    assert SESSION_START_HOOK in _script_paths()


def test_every_hook_command_points_at_an_existing_script():
    for rel in _script_paths():
        assert (REPO_ROOT / rel).is_file(), rel


def test_hooks_manifest_wires_every_shipped_script():
    shipped = sorted(
        path.name
        for path in HOOKS_DIR.iterdir()
        if path.is_file() and path.suffix != ".json"
    )
    assert sorted(Path(rel).name for rel in _script_paths()) == shipped


def test_plugin_root_paths_are_quoted():
    """A plugin root containing spaces must stay a single shell token."""
    for command in _commands():
        if PLUGIN_ROOT_VAR in command:
            assert f'"{PLUGIN_ROOT_VAR}/' in command, command
