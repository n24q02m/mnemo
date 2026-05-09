# Mnemo MCP -- Agent Setup Guide

> Give this file to your AI agent to automatically set up mnemo-mcp.

> **2026-05-09 update (Phase 1 / v1.x)**: typed `memory(action="capture")` +
> RRF/rerank/temporal-decay retrieval + archive policy + plugin trinity
> (`recall-context`/`memory-commit` skills + SessionStart/PostToolUse hooks).

## Method overview

This plugin supports 3 install methods. Pick the one that matches your use
case (mutually exclusive):

| Priority | Method | Transport | Best for |
|---|---|---|---|
| **1. Default** | Plugin install (`uvx`/`npx`) | stdio | Quick local start, single workstation, no OAuth/HTTP needed. |
| **2. Fallback** | Docker stdio (`docker run -i --rm`) | stdio | Windows/macOS where native uvx/npx hits PATH or Python version issues. |
| **3. Recommended** | Docker HTTP (`docker run -p 8080:8080`) | HTTP | Multi-device, OAuth/relay-form auth, team self-host, claude.ai web compatibility. |

> **Trade-off**: Option 2 / Option 3 means you lose the plugin's
> skills/hooks/agents. Use Option 1 for full plugin features.

## Option 1: Claude Code Plugin (Recommended)

```bash
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins
```

Restart Claude Code. The plugin trinity activates automatically (see
README "Plugin trinity" section).

### `mcpServers` stanza (manual install in non-CC clients)

For **Codex / Cursor / Antigravity / Windsurf / mcp.json**, paste:

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["--python", "3.13", "mnemo-mcp"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "JINA_AI_API_KEY": "${env:JINA_AI_API_KEY}",
        "GEMINI_API_KEY": "${env:GEMINI_API_KEY}",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}",
        "COHERE_API_KEY": "${env:COHERE_API_KEY}"
      }
    }
  }
}
```

All API keys are optional. Without them, mnemo runs local-only (Qwen3 ONNX
embedding + reranking).

### Plugin trinity activation (Claude Code only)

When installed via `/plugin install`, two skills become available:

| Skill | Trigger | Purpose |
|---|---|---|
| `mnemo:recall-context` | session start, before significant decisions, "what do I know about X?" | Pulls cwd/topic-relevant memories with `context_type` filtering |
| `mnemo:memory-commit` | "remember this" / "save this" / "ghi nho" / "luu lai" | Typed manual capture with `context_type` decision tree |

Two hooks fire automatically:

- **SessionStart**: prints a one-time nudge so Claude knows mnemo is
  available and how to invoke `recall-context`.
- **PostToolUse** (opt-in via `CAPTURE_AUTO_ENABLED=true`): hints
  `memory-commit` after Write/Edit of CLAUDE.md / AGENTS.md /
  ARCHITECTURE.md / docs/*.md.

## Option 2: Docker stdio (fallback)

```bash
docker run -i --rm \
  --name mcp-mnemo \
  -v mnemo-data:/data \
  -e JINA_AI_API_KEY \
  -e GEMINI_API_KEY \
  -e OPENAI_API_KEY \
  -e COHERE_API_KEY \
  n24q02m/mnemo-mcp:latest
```

Or as MCP server config:

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-mnemo",
        "-v", "mnemo-data:/data",
        "-e", "JINA_AI_API_KEY",
        "-e", "GEMINI_API_KEY",
        "n24q02m/mnemo-mcp:latest"
      ]
    }
  }
}
```

## Option 3: Docker HTTP (recommended for multi-device)

```bash
docker run -p 8080:8080 \
  -e TRANSPORT_MODE=http \
  -e PUBLIC_URL=https://your-domain.com \
  -e DCR_SERVER_SECRET=$(openssl rand -hex 32) \
  -v mnemo-data:/data \
  n24q02m/mnemo-mcp:latest
```

Client config:

```json
{
  "mcpServers": {
    "mnemo": {
      "type": "http",
      "url": "https://your-domain.com/mcp"
    }
  }
}
```

Full HTTP self-host details (relay password, browser OAuth flow,
per-JWT-sub credential isolation): see [setup-manual.md](setup-manual.md)
"Method 3".

## Environment Variables

All env vars are **optional**. The server works in local mode (ONNX
embedding) with zero configuration. Full table: see
[setup-manual.md](setup-manual.md) "Environment Variable Reference".

### Quick reference (most common)

| Variable | Default | Purpose |
|---|---|---|
| `JINA_AI_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `COHERE_API_KEY` | -- | Optional cloud embedding/rerank/LLM |
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | SQLite path |
| `DEDUP_THRESHOLD` | `0.92` | Capture dedup similarity threshold |
| `RECENCY_HALF_LIFE_DAYS` | `7` | Search temporal decay |
| `ARCHIVE_AFTER_DAYS` | `90` | Archive policy age threshold |
| `CAPTURE_AUTO_ENABLED` | `false` | Opt-in PostToolUse hint hook |
| `LLM_MODELS` | auto | LiteLLM-format `provider/model` list (capture LLM dispatch) |
| `LOG_LEVEL` | `INFO` | TRACE / DEBUG / INFO / WARNING / ERROR |

## Verification

After setup, verify the server is working:

```
memory(action="stats")
```

Expected: returns total memories count, categories, and embedding status.

Test the typed capture pipeline:

```
memory(action="capture",
       text="Test capture - confirms typed memory pipeline works end-to-end.",
       context_type="fact")
```

Expected: returns `{"status": "captured", "id": "...", "context_type": "fact", ...}`.

Search with filters:

```
memory(action="search", query="test capture", context_type="fact", limit=3)
```

Expected: returns the just-captured memory with `score` and `rerank_score`
fields populated when reranking is available.
