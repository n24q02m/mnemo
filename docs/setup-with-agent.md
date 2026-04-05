# Mnemo MCP -- Agent Setup Guide

> Give this file to your AI agent to automatically set up mnemo-mcp.

## Option 1: Claude Code Plugin (Recommended)

```bash
# Install from marketplace (includes skills: /session-handoff, /knowledge-audit)
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins
```

No further configuration needed. The server auto-configures via relay on first run.

## Option 2: MCP Direct

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

## Option 3: Docker

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

### General

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `MCP_RELAY_URL` | No | `https://mnemo-mcp.n24q02m.com` | Relay server URL for zero-config setup |

## Authentication

### Zero-Config Relay (BETA, Optional)

> **Note**: Relay is a **BETA** credential provisioning flow. For stable production use, prefer **Environment Variables** above. The relay blocks server startup on first run and may time out in some MCP clients.

On first run without any API keys in environment:

1. Server starts and creates a relay session
2. A setup URL is printed to stderr
3. Open the URL in any browser
4. Fill in API keys on the guided form (all optional)
5. Credentials are encrypted and stored locally at `~/.config/mcp/config.enc`
6. Subsequent runs load saved credentials automatically

The relay form has 4 optional fields:
- **Jina AI API Key** -- embedding + reranking (highest priority)
- **Gemini API Key** -- LLM + embedding (free tier available)
- **OpenAI API Key** -- LLM + embedding
- **Cohere API Key** -- embedding + reranking

Leave all empty to use pure local mode (Qwen3 ONNX models).

### Google Drive Sync (Optional)

After relay setup, if `GOOGLE_DRIVE_CLIENT_ID` is configured, OAuth Device Code flow starts automatically. For other providers (Dropbox, S3), set `SYNC_PROVIDER` and `SYNC_REMOTE`.

### Environment Variables (Recommended)

Set API keys directly as environment variables to skip relay entirely.

## Verification

After setup, verify the server is working by calling the `memory` tool:

```
memory(action="stats")
```

Expected: returns database statistics including total memories count and categories.
