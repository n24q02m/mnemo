#!/usr/bin/env bash
# mnemo-mcp SessionStart hook.
#
# Emits a non-blocking nudge so Claude Code knows mnemo is available and
# how to use the recall-context skill at the start of a session. The hook
# does not query mnemo directly here - that requires an MCP client and is
# handled by the recall-context skill once the agent decides to look up
# prior context.
#
# Behaviour:
#   - Always exits 0 (never blocks session start).
#   - Prints a short instruction block to stdout that Claude Code surfaces
#     into the session context.
#   - Skips silently when CLAUDE_PROJECT_DIR is missing (e.g. one-off
#     invocations).
set -e

CWD="${CLAUDE_PROJECT_DIR:-${PWD:-}}"
if [ -z "${CWD}" ]; then
  exit 0
fi

cat <<INSTRUCTIONS
[mnemo] Persistent memory available. Project context: ${CWD}

When starting a new task or before significant decisions, invoke the
mnemo:recall-context skill (or call memory(action="search", query="<topic>"))
to load prior decisions, preferences, and open questions tied to this project.

When the user says "remember this", "save this", "ghi nho", or "luu lai",
invoke the mnemo:memory-commit skill to capture with the right context_type.
INSTRUCTIONS

exit 0
