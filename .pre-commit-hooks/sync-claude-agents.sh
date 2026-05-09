#!/usr/bin/env bash
# Verify CLAUDE.md and AGENTS.md stay in sync (excluding the first heading line).
# CLAUDE.md is the canonical source. AGENTS.md mirrors it with only its first
# heading differing (`# AGENTS.md - mnemo-mcp` vs `# mnemo-mcp`).
set -e

if [ ! -f CLAUDE.md ] || [ ! -f AGENTS.md ]; then
  echo "sync-claude-agents: CLAUDE.md or AGENTS.md missing at repo root"
  exit 1
fi

CLAUDE=$(tail -n +2 CLAUDE.md)
AGENTS=$(tail -n +2 AGENTS.md)

if [ "$CLAUDE" != "$AGENTS" ]; then
  echo "CLAUDE.md and AGENTS.md drift detected (excluding first heading)."
  diff <(echo "$CLAUDE") <(echo "$AGENTS") || true
  exit 1
fi
