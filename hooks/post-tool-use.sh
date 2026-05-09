#!/usr/bin/env bash
# mnemo-mcp PostToolUse hook (opt-in via CAPTURE_AUTO_ENABLED=true).
#
# When opt-in is enabled and the just-completed tool call wrote to a
# decision-like file (CLAUDE.md, AGENTS.md, ARCHITECTURE.md, docs/*.md),
# emit a hint so Claude considers invoking memory-commit. The hook does
# not auto-capture by itself - that would create token noise and
# duplicate captures on every save. The agent decides whether to call
# memory(action="capture") based on the hint.
#
# Behaviour:
#   - Exits 0 immediately when CAPTURE_AUTO_ENABLED is unset/false.
#   - Always exits 0; never blocks tool execution.
set -e

if [ "${CAPTURE_AUTO_ENABLED:-false}" != "true" ]; then
  exit 0
fi

# CLAUDE_TOOL_USE_CONTEXT is provided by Claude Code when available and
# contains the JSON envelope describing the tool invocation. We grep for
# decision-like file paths conservatively; do not parse JSON to keep the
# hook dependency-free.
CONTEXT="${CLAUDE_TOOL_USE_CONTEXT:-}"
if [ -z "${CONTEXT}" ]; then
  exit 0
fi

if echo "${CONTEXT}" | grep -Eq '(CLAUDE\.md|AGENTS\.md|ARCHITECTURE\.md|docs/[^"]*\.md)'; then
  cat <<HINT
[mnemo] Decision-like file edited. If this change reflects a deliberate
preference, decision, or new fact worth persisting across sessions,
invoke the mnemo:memory-commit skill to capture it with the appropriate
context_type. (Set CAPTURE_AUTO_ENABLED=false to silence these hints.)
HINT
fi

exit 0
