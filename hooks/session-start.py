#!/usr/bin/env python3
"""mnemo SessionStart hook.

Emits a non-blocking nudge so Claude Code knows mnemo is available and
how to use the recall-context skill at the start of a session. The hook
does not query mnemo directly here - that requires an MCP client and is
handled by the recall-context skill once the agent decides to look up
prior context.

Behaviour:
  - Always exits 0 (never blocks session start).
  - Prints a short instruction block to stdout that Claude Code surfaces
    into the session context.
  - Skips silently when CLAUDE_PROJECT_DIR is missing (e.g. one-off
    invocations).
"""

import os
import sys

INSTRUCTIONS = """[mnemo] Persistent memory available. Project context: {cwd}

When starting a new task or before significant decisions, invoke the
mnemo:recall-context skill (or call memory(action="search", query="<topic>"))
to load prior decisions, preferences, and open questions tied to this project.

When the user says "remember this", "save this", "ghi nho", or "luu lai",
invoke the mnemo:memory-commit skill to capture with the right context_type.
"""


def _emit(text: str) -> None:
    """Write exactly what the bash heredoc wrote: LF line endings, no CR."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(newline="\n")
        except ValueError:
            pass
    sys.stdout.write(text)


def main() -> int:
    # `${CLAUDE_PROJECT_DIR:-${PWD:-}}` -- bash always has PWD, so fall back to
    # the working directory when the environment does not export it.
    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("PWD") or ""
    if not cwd:
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = ""
    if not cwd:
        return 0
    _emit(INSTRUCTIONS.format(cwd=cwd))
    return 0


if __name__ == "__main__":
    sys.exit(main())
