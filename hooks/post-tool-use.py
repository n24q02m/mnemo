#!/usr/bin/env python3
"""mnemo PostToolUse hook (opt-in via CAPTURE_AUTO_ENABLED=true).

When opt-in is enabled and the just-completed tool call wrote to a
decision-like file (CLAUDE.md, AGENTS.md, ARCHITECTURE.md, docs/*.md),
emit a hint so Claude considers invoking memory-commit. The hook does
not auto-capture by itself - that would create token noise and
duplicate captures on every save. The agent decides whether to call
memory(action="capture") based on the hint.

Behaviour:
  - Exits 0 immediately when CAPTURE_AUTO_ENABLED is unset/false.
  - Always exits 0; never blocks tool execution.
"""

import os
import re
import sys

# CLAUDE_TOOL_USE_CONTEXT is provided by Claude Code when available and
# contains the JSON envelope describing the tool invocation. Match
# decision-like file paths conservatively, one line at a time; the
# envelope is not parsed to keep the hook dependency-free.
DECISION_FILE_RE = re.compile(
    r'(CLAUDE\.md|AGENTS\.md|ARCHITECTURE\.md|docs/[^"]*\.md)'
)

HINT = """[mnemo] Decision-like file edited. If this change reflects a deliberate
preference, decision, or new fact worth persisting across sessions,
invoke the mnemo:memory-commit skill to capture it with the appropriate
context_type. (Set CAPTURE_AUTO_ENABLED=false to silence these hints.)
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
    if os.environ.get("CAPTURE_AUTO_ENABLED", "false") != "true":
        return 0
    context = os.environ.get("CLAUDE_TOOL_USE_CONTEXT", "")
    if not context:
        return 0
    if any(DECISION_FILE_RE.search(line) for line in context.splitlines()):
        _emit(HINT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
