# Mnemo MCP -- Agent Setup Guide

> Give this file to your AI agent to automatically set up mnemo-mcp.

> **2026-05-02 Update (v<auto>+)**: Plugin install (Option 1) now uses pure stdio mode with local SQLite storage. No required env vars -- mnemo works out-of-box.
> The previous "Zero-Config Relay" auto-spawn pattern has been removed.
> Optional cloud providers (Jina/Gemini/OpenAI/Cohere) and Google Drive sync are still supported -- set them via env vars (Option 1/2) or configure them through the relay form in HTTP mode (see setup-manual.md "Method 5: Self-Hosting HTTP Mode").

## Method overview

This plugin supports 3 install methods. Pick the one that matches your use case:

| Priority | Method | Transport | Best for |
|---|---|---|---|
| **1. Default** | Plugin install (`uvx`/`npx`) | stdio | Quick local start, single workstation, no OAuth/HTTP needed. |
| **2. Fallback** | Docker stdio (`docker run -i --rm`) | stdio | Windows/macOS where native uvx/npx hits PATH or Python version issues. |
| **3. Recommended** | Docker HTTP (`docker run -p 8080:8080`) | HTTP | Multi-device, OAuth/relay-form auth, team self-host, claude.ai web compatibility. |

All MCP servers across this stack share this priority hierarchy. Note: 2 plugins (`better-godot-mcp` and `better-code-review-graph`) only support Method 1 (stdio) -- they need direct host access to project files / repo paths and don't ship Docker / HTTP variants.

## Option 1: Claude Code Plugin (Recommended)

Plugin marketplace install runs the server in **pure stdio mode**. mnemo works with **zero required env vars** -- it falls back to local SQLite + local Qwen3 ONNX embedding. Cloud providers and GDrive sync are optional.

```bash
# Install from marketplace (includes skills: /session-handoff, /knowledge-audit)
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins
```

Optional: add cloud API keys to plugin config for higher-quality embeddings/reranking:

```json
{
  "mcpServers": {
    "mnemo-mcp": {
      "env": {
        "JINA_AI_API_KEY": "jina_...",
        "GEMINI_API_KEY": "AIza..."
      }
    }
  }
}
```

## Option 2: MCP Direct (Stdio + uvx)

**Python 3.13 required** -- Python 3.14+ is NOT supported.

### Claude Code (settings.json)

Add to `~/.claude/settings.local.json` under `"mcpServers"`:

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["--python", "3.13", "mnemo-mcp"]
    }
  }
}
```

### Codex CLI (config.toml)

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.mnemo]
command = "uvx"
args = ["--python", "3.13", "mnemo-mcp"]
```

### OpenCode (opencode.json)

Add to `opencode.json` in the project root:

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["--python", "3.13", "mnemo-mcp"]
    }
  }
}
```

## Option 3: Docker (Stdio)

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

Or as an MCP server config:

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

## Why upgrade to HTTP mode?

Stdio is the default and works fine for single-user local setups. You may want to switch to HTTP mode (self-host) when you need any of the following:

- **claude.ai web compatibility** -- claude.ai (the web UI) supports HTTP MCP servers but cannot spawn local stdio processes.
- **One server shared across N Claude Code sessions** -- a single HTTP instance serves multiple terminals/IDEs without re-spawning per session, sharing the same memory database.
- **Browser-based GDrive OAuth** -- enable Google Drive sync without manually exchanging an OAuth token in the env (the relay form completes the OAuth flow in your browser).
- **Multi-device credential sync** -- configure cloud API keys / GDrive once, the server uses them for any device/session that connects.
- **Multi-user team sharing** -- a self-hosted server can serve multiple memory databases, each isolated per JWT-sub.
- **Always-on persistent process for webhooks/agents** -- HTTP servers stay alive between sessions, enabling background sync, scheduled archive runs, or background memory consolidation.

For self-hosting HTTP mode (your own multi-user mnemo server with bundled GDrive OAuth), see [setup-manual.md](setup-manual.md) "Method 5: Self-Hosting HTTP Mode".

### Edge auth: relay password

Public HTTP deployments expose `<your-domain>/authorize` to URL discovery. To prevent random Internet users from accessing the relay form, mint a relay password:

```bash
openssl rand -hex 32
# Save in your skret / .env as:
MCP_RELAY_PASSWORD=<generated-32-byte-hex>
```

Share this password out-of-band (Signal/email/SMS) with anyone you invite to use your server. They will see a login form when first opening `/authorize`; once logged in, the cookie persists 24 hours.

**Single-user dev exception**: If `PUBLIC_URL=http://localhost:8080`, you can leave `MCP_RELAY_PASSWORD` empty to disable the gate. The server logs a warning if you skip the password with a non-localhost `PUBLIC_URL`.

## Environment Variables

All environment variables are **optional**. The server works in local mode (ONNX embedding) with zero configuration.

### API Keys (Cloud Providers)

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `JINA_AI_API_KEY` | No | -- | Jina AI key: embedding + reranking (highest priority) |
| `GEMINI_API_KEY` | No | -- | Google Gemini key: LLM (importance scoring, graph extraction) + embedding |
| `OPENAI_API_KEY` | No | -- | OpenAI key: LLM + embedding (lower priority than Gemini) |
| `COHERE_API_KEY` | No | -- | Cohere key: embedding + reranking |

### Database and Storage

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `DB_PATH` | No | `~/.mnemo-mcp/memories.db` | Database location |

### Embedding and Reranking

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `EMBEDDING_BACKEND` | No | auto-detect | `cloud` or `local` (Qwen3). Auto: API keys present -> cloud, else local |
| `EMBEDDING_MODEL` | No | auto-detect | Cloud embedding model name |
| `EMBEDDING_DIMS` | No | `0` (auto=768) | Embedding dimensions |
| `RERANK_ENABLED` | No | `true` | Enable reranking (improves search precision) |
| `RERANK_BACKEND` | No | auto-detect | `cloud` or `local`. Auto: Jina/Cohere key -> cloud, else local |
| `RERANK_MODEL` | No | auto-detect | Cloud reranker model name |
| `RERANK_TOP_N` | No | `10` | Number of top results after reranking |

### LLM

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `LLM_MODELS` | No | auto-detect | LLM model for importance scoring, graph extraction, consolidation (LiteLLM format) |

### Memory Management

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `ARCHIVE_ENABLED` | No | `true` | Enable auto-archiving of old low-importance memories |
| `ARCHIVE_AFTER_DAYS` | No | `90` | Days before a memory is eligible for auto-archive |
| `ARCHIVE_IMPORTANCE_THRESHOLD` | No | `0.3` | Memories below this importance score are auto-archived |
| `DEDUP_THRESHOLD` | No | `0.9` | Similarity threshold to block duplicate memories |
| `DEDUP_WARN_THRESHOLD` | No | `0.7` | Similarity threshold to warn about similar memories |
| `RECENCY_HALF_LIFE_DAYS` | No | `7` | Half-life for temporal decay in search scoring |

### Sync

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `SYNC_ENABLED` | No | `false` | Enable rclone sync |
| `SYNC_PROVIDER` | No | `drive` | rclone provider type (drive, dropbox, s3, etc.) |
| `SYNC_REMOTE` | No | `gdrive` | rclone remote name |
| `SYNC_FOLDER` | No | `mnemo-mcp` | Remote folder name |
| `SYNC_INTERVAL` | No | `300` | Auto-sync interval in seconds (0=manual) |

### HTTP Mode (Self-Hosting Only)

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `TRANSPORT_MODE` | No (`stdio`) | `stdio` | Set to `http` to enable HTTP transport (multi-user, bundled GDrive OAuth). |
| `PUBLIC_URL` | Yes (http) | -- | Server's public URL for OAuth redirects and `/authorize` setup page. |
| `DCR_SERVER_SECRET` | Yes (http) | -- | HMAC secret for stateless Dynamic Client Registration. Generate via `openssl rand -hex 32`. |
| `PORT` | No | `8080` | Server port (http mode only). |

### General

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `LOG_LEVEL` | No | `INFO` | Logging level |

## Authentication

### Stdio Mode (Local SQLite + Optional Env Cloud Keys)

mnemo works without any credentials -- it falls back to local SQLite + local Qwen3 ONNX embedding. Optionally set cloud API keys (Jina/Gemini/OpenAI/Cohere) as env vars for higher-quality results.

For Google Drive sync in stdio mode, manually create the OAuth token at `~/.mnemo-mcp/tokens/google_drive.json` (chmod 600). For browser-based OAuth, use HTTP mode.

### HTTP Mode (Bundled GDrive OAuth + Per-JWT-Sub Isolation)

The server hosts a `/authorize` page that lets each user paste their cloud API keys and complete Google Drive OAuth in the browser. The Google Desktop OAuth public client is bundled (same pattern as `wet-mcp`); no separate Google Cloud Console registration is required.

Credentials are stored encrypted at `~/.mnemo-mcp/subs/<sub>/`, isolated per JWT-sub.

## Verification

After setup, verify the server is working by calling the `memory` tool:

```
memory(action="stats")
```

Expected: returns database statistics including total memories count and categories.
