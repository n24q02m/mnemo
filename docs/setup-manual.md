# Mnemo MCP -- Manual Setup Guide

> **2026-05-09 update (Phase 1 / v1.x)**: ships the `memory(action="capture")`
> typed-capture pipeline (6 context_types, dedup, multi-provider LLM auto-detect),
> RRF + cross-encoder rerank + temporal decay retrieval, importance x recency
> archive policy (with restore), Alembic migrations, plus the plugin trinity
> (`recall-context`/`memory-commit` skills + SessionStart/PostToolUse hooks).

> **Phase roadmap badges** (see `README.md`):
>
> - **v1.x** (current) -- typed capture, retrieval polish, archive policy, hygiene.
> - **v1.x+1** (planned) -- LLM-driven compression of older memories + Passport
>   sync (encrypted import/export bundle for cross-machine bootstrap).
> - **v2.0** (planned, BREAKING) -- temporal knowledge graph (bitemporal `as_of`
>   queries, entity timelines).

## Method overview

This plugin supports 3 install methods. Pick the one that matches your use case:

| Priority | Method | Transport | Best for |
|---|---|---|---|
| **1. Default** | Plugin install (`uvx`/`npx`) | stdio | Quick local start, single workstation, no OAuth/HTTP needed. |
| **2. Fallback** | Docker stdio (`docker run -i --rm`) | stdio | Windows/macOS where native uvx/npx hits PATH or Python version issues. |
| **3. Recommended** | Docker HTTP (`docker run -p 8080:8080`) | HTTP | Multi-device, OAuth/relay-form auth, team self-host, claude.ai web compatibility. |

> **Mutually exclusive -- pick ONE per plugin**: Method 2 or Method 3 means
> you lose the plugin's skills/agents/hooks/commands (matched by endpoint per
> Claude Code docs). Use Method 1 for full plugin features.

## Prerequisites

- **Python 3.13** (3.14+ is NOT supported)
- `uv` or `uvx` installed ([docs](https://docs.astral.sh/uv/getting-started/installation/))
- Docker (optional, for containerized setup)

## Method 1: Claude Code Plugin (Recommended)

Plugin marketplace install runs the server in **pure stdio mode**. mnemo
works with **zero required env vars** -- it falls back to local SQLite +
local Qwen3 ONNX embedding. Cloud providers and GDrive sync are optional.

```bash
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins
```

Restart Claude Code. The plugin trinity activates automatically:

- **`/recall-context`** skill: pulls cwd-relevant memories at session start
  or before significant decisions (see `skills/recall-context/SKILL.md`).
- **`/memory-commit`** skill: typed manual capture with the right
  `context_type` when the user says "remember this" / "ghi nho" / etc.
- **SessionStart hook**: nudges Claude to invoke `recall-context` on init.
- **PostToolUse hook** (opt-in via `CAPTURE_AUTO_ENABLED=true`): hints
  `memory-commit` after Write/Edit of decision-like files (CLAUDE.md,
  AGENTS.md, ARCHITECTURE.md, docs/*.md).

### Credential prompts at install

When you run `/plugin install`, Claude Code prompts for these (declared in
`userConfig`). Sensitive values are stored in your system keychain and
persist across `/plugin update`:

| Field | Required | Where to obtain |
|---|---|---|
| `JINA_AI_API_KEY` | Optional | https://jina.ai/api-key |
| `GEMINI_API_KEY` | Optional | https://aistudio.google.com/apikey |
| `OPENAI_API_KEY` | Optional | https://platform.openai.com/api-keys |
| `COHERE_API_KEY` | Optional | https://dashboard.cohere.com/api-keys |

## Method 2: Docker stdio (fallback)

```bash
docker pull n24q02m/mnemo-mcp:latest
docker run -i --rm \
  --name mcp-mnemo \
  -v mnemo-data:/data \
  -e JINA_AI_API_KEY=your_key_here \
  -e GEMINI_API_KEY=your_key_here \
  n24q02m/mnemo-mcp:latest
```

Or as MCP client config:

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

## Method 3: Docker HTTP (recommended for multi-device / claude.ai web)

Self-host your own multi-user mnemo server. Always-multi-user (per-JWT-sub
credential isolation). Google Drive OAuth uses a **bundled Desktop OAuth
public client** (same pattern as `wet-mcp`); no separate Google Cloud
Console registration is required.

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

### Edge auth: relay password

Public HTTP deployments expose `/authorize` to URL discovery. To prevent
random Internet users from accessing the relay form, mint a relay password:

```bash
openssl rand -hex 32
# Save in your secret store / .env as:
MCP_RELAY_PASSWORD=<generated-32-byte-hex>
```

Share out-of-band (Signal/email/SMS) with anyone you invite. Cookie persists
24h. Single-user dev exception: skip `MCP_RELAY_PASSWORD` only when
`PUBLIC_URL=http://localhost:8080`.

### Browser setup flow

1. On first tool call from a new client, the server returns a setup URL:
   `https://your-domain.com/authorize?session=<sid>`.
2. Open the URL in a browser, fill optional cloud API keys, optionally
   click "Connect Google Drive" to complete OAuth.
3. Submit. Credentials are encrypted and stored per JWT-sub at
   `~/.mnemo-mcp/subs/<sub>/`.
4. Retry the tool call -- it now succeeds with your config.

## Environment Variable Reference

All env vars are **optional** -- mnemo works with zero env vars in stdio
mode (local SQLite + local Qwen3 ONNX). The full table:

### Cloud API keys (auto-detected priority)

| Variable | Default | Description |
|---|---|---|
| `JINA_AI_API_KEY` | -- | Jina AI: embedding + reranking (highest priority) |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | -- | Google Gemini: embedding + LLM |
| `OPENAI_API_KEY` | -- | OpenAI: embedding + LLM |
| `COHERE_API_KEY` / `CO_API_KEY` | -- | Cohere: embedding + reranking |
| `XAI_API_KEY` | -- | xAI/Grok: LLM only |

### Database and storage

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | SQLite database location |

### Embedding and reranking

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_BACKEND` | auto | `cloud` or `local` (Qwen3 ONNX). Auto: API keys present -> cloud, else local. |
| `EMBEDDING_MODEL` | auto | Cloud embedding model name (auto-resolved from priority) |
| `EMBEDDING_DIMS` | `0` (=768) | Stored vector dims (MRL truncation across providers) |
| `RERANK_ENABLED` | `true` | Enable cross-encoder rerank stage |
| `RERANK_BACKEND` | auto | `cloud` (Jina/Cohere) or `local` (qwen3-reranker) |
| `RERANK_MODEL` | auto | Cloud reranker model name |
| `RERANK_TOP_N` | `10` | Top-N kept after rerank |

### Capture (Phase 1 v0)

| Variable | Default | Description |
|---|---|---|
| `DEDUP_THRESHOLD` | `0.92` | Embedding similarity threshold above which capture returns the existing memory id instead of inserting a duplicate. |
| `DEDUP_WARN_THRESHOLD` | `0.7` | Lower threshold for "similar memory" warnings on `add`. |
| `CAPTURE_AUTO_ENABLED` | `false` | Opt-in. When `true`, the PostToolUse hook hints `memory-commit` after Write/Edit of decision-like files. |
| `CAPTURE_CONTEXT_TYPE_DEFAULT` | `conversation` | Default `context_type` when the agent does not pass one explicitly. |

### Memory management

| Variable | Default | Description |
|---|---|---|
| `ARCHIVE_ENABLED` | `true` | Background soft-archive of old low-importance memories |
| `ARCHIVE_AFTER_DAYS` | `90` | Days before a memory becomes archive-eligible |
| `ARCHIVE_IMPORTANCE_THRESHOLD` | `0.3` | Importance below this is archive-eligible |
| `ARCHIVE_TRIGGER_EVERY` | `100` | Run an `archive_by_score` sweep every N captures |
| `RECENCY_HALF_LIFE_DAYS` | `7` | Half-life for temporal decay scoring in search |

### LLM dispatch (Phase 1 foundation, used in Phase 2 compression)

| Variable | Default | Description |
|---|---|---|
| `LLM_MODELS` | auto | Comma-list of LLM models (LiteLLM format `provider/model`). When unset, the dispatcher auto-detects from `GEMINI_API_KEY` > `OPENAI_API_KEY` > `ANTHROPIC_API_KEY` > `XAI_API_KEY`. Graceful skip when none present. |

### Sync (Google Drive)

| Variable | Default | Description |
|---|---|---|
| `SYNC_ENABLED` | `true` (when a GDrive client is configured) | Enable JSONL-based merge sync via Google Drive API |
| `SYNC_FOLDER` | `mnemo-mcp` | Drive folder name |
| `SYNC_INTERVAL` | `300` | Auto-sync interval in seconds (0 = manual only) |
| `GOOGLE_DRIVE_CLIENT_ID` | bundled Desktop public client | Override only if self-issuing GCP credentials |
| `GOOGLE_DRIVE_CLIENT_SECRET` | bundled (Desktop public secret per Google docs) | -- |

### HTTP mode (self-host only)

| Variable | Required | Description |
|---|---|---|
| `TRANSPORT_MODE` / `MCP_TRANSPORT` | No (stdio default) | Set to `http` to enable HTTP transport |
| `PUBLIC_URL` | Yes (http) | Server's public URL for OAuth redirects + `/authorize` |
| `DCR_SERVER_SECRET` / `MCP_DCR_SERVER_SECRET` | Yes (http) | HMAC secret for stateless Dynamic Client Registration. Generate via `openssl rand -hex 32`. |
| `MCP_PORT` / `PORT` | No | Server port (default `8080`) |
| `MCP_RELAY_PASSWORD` | Recommended (http) | Edge auth gate for `/authorize` form |

### General

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | TRACE / DEBUG / INFO / SUCCESS / WARNING / ERROR / CRITICAL |

### Provider priority

- **Embedding**: Jina AI > Gemini > OpenAI > Cohere > Local ONNX (Qwen3)
- **Reranking**: Jina AI > Cohere > Local ONNX (qwen3-reranker)
- **LLM**: Gemini > OpenAI > Anthropic > xAI > Disabled (graceful skip;
  capture stores raw text without fact extraction)

## Troubleshooting

### First run takes a long time

On first start, the server downloads the ONNX embedding model (~570MB).
Pre-download via the warmup action:

```
config(action="warmup")
```

### Database locked errors

Ensure only one instance of mnemo-mcp is running. Check for orphaned
processes:

```bash
# Linux/macOS
ps aux | grep mnemo-mcp
# Windows
tasklist | findstr mnemo
```

### Sync conflicts

Sync uses JSONL-based merge strategy; the most recent version wins. Manual
fallback:

```
memory(action="export")
memory(action="import", data="<jsonl-string>")
```

### Embedding model download fails

If the ONNX download fails behind a proxy, set any cloud API key (e.g.
`GEMINI_API_KEY`) to switch to cloud embedding instead.
