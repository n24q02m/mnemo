# Mnemo MCP Server

**Persistent AI memory with hybrid search and embedded sync. Open, free, unlimited.**

[![PyPI](https://img.shields.io/pypi/v/mnemo-mcp)](https://pypi.org/project/mnemo-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/mnemo-mcp?label=docker)](https://hub.docker.com/r/n24q02m/mnemo-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Hybrid search**: FTS5 full-text + sqlite-vec semantic + Qwen3-Embedding-0.6B (built-in)
- **Zero config mode**: Works out of the box — local embedding, no API keys needed
- **Auto-detect embedding**: Set `API_KEYS` for cloud embedding, auto-fallback to local
- **Embedded sync**: rclone auto-downloaded and managed as subprocess
- **Multi-machine**: JSONL-based merge sync via rclone (Google Drive, S3, etc.)
- **Proactive memory**: Tool descriptions guide AI to save preferences, decisions, facts

## Quick Start

### Option 1: Minimal uvx (Recommended)

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp@latest"]
      // No API keys needed -- local Qwen3-Embedding-0.6B (ONNX, CPU) for hybrid search (FTS5 + vector)
      // First run downloads ~570MB model, cached for subsequent runs
    }
  }
}
```

### Option 2: Minimal Docker

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-mnemo",
        "-v", "mnemo-data:/data",
        "n24q02m/mnemo-mcp:latest"
      ]
      // Volume persists memories across restarts
      // Same built-in local embedding as uvx
    }
  }
}
```

### Option 3: Full uvx

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp@latest"],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...",     // cloud embedding (Gemini > OpenAI > Mistral > Cohere) for semantic search
        "SYNC_ENABLED": "true",                    // enable sync
        "SYNC_REMOTE": "gdrive",                   // rclone remote name
        "SYNC_INTERVAL": "300",                    // auto-sync every 5min (0 = manual)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"   // from: uvx mnemo-mcp setup-sync drive
      }
    }
  }
}
```

### Option 4: Full Docker

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-mnemo",
        "-v", "mnemo-data:/data",
        "-e", "API_KEYS",
        "-e", "SYNC_ENABLED",
        "-e", "SYNC_REMOTE",
        "-e", "SYNC_INTERVAL",
        "-e", "RCLONE_CONFIG_GDRIVE_TYPE",
        "-e", "RCLONE_CONFIG_GDRIVE_TOKEN",
        "n24q02m/mnemo-mcp:latest"
      ],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        "SYNC_ENABLED": "true",
        "SYNC_REMOTE": "gdrive",
        "SYNC_INTERVAL": "300",
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"
      }
      // Same auto-detection: cloud embedding from API_KEYS, fallback to local
    }
  }
}
```

> The `-v mnemo-data:/data` volume persists memories across restarts.

### Sync setup (one-time)

```bash
# Google Drive
uvx mnemo-mcp setup-sync drive

# Other providers (any rclone remote type)
uvx mnemo-mcp setup-sync dropbox
uvx mnemo-mcp setup-sync onedrive
uvx mnemo-mcp setup-sync s3
```

Opens a browser for OAuth and outputs env vars (`RCLONE_CONFIG_*`) to set. Both raw JSON and base64 tokens are supported.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | Database location |
| `API_KEYS` | — | API keys (`ENV:key,ENV:key`). Optional: enables semantic search |
| `EMBEDDING_BACKEND` | (auto-detect) | `litellm` (cloud API) or `local` (Qwen3 ONNX). Auto: litellm > local |
| `EMBEDDING_MODEL` | auto-detect | LiteLLM model name (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (0 = auto-detect, default 768) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | — | rclone remote name (required when sync enabled) |
| `SYNC_FOLDER` | `mnemo-mcp` | Remote folder (optional) |
| `SYNC_INTERVAL` | `0` | Auto-sync seconds (optional, 0=manual) |
| `LOG_LEVEL` | `INFO` | Log level (optional) |

### Embedding

Auto-detection logic:

- **Embedding**: `API_KEYS` set -> cloud (Gemini > OpenAI > Mistral > Cohere). No API keys -> local Qwen3-Embedding-0.6B (ONNX, CPU).
- All embeddings stored at **768 dims** (default). Switching providers never breaks the vector table.
- Override with `EMBEDDING_BACKEND=local` to force local even with API keys.

Cloud embedding providers (auto-detected from `API_KEYS`, priority order):

| Priority | Env Var (LiteLLM) | Model | Native Dims | Stored |
|----------|-------------------|-------|-------------|--------|
| 1 | `GEMINI_API_KEY` | `gemini/gemini-embedding-001` | 3072 | 768 |
| 2 | `OPENAI_API_KEY` | `text-embedding-3-small` | 1536 | 768 |
| 3 | `MISTRAL_API_KEY` | `mistral/mistral-embed` | 1024 | 768 |
| 4 | `COHERE_API_KEY` | `embed-english-v3.0` | 1024 | 768 |

All embeddings are truncated to **768 dims** (default) for storage. This ensures switching models never breaks the vector table. Override with `EMBEDDING_DIMS` if needed.

`API_KEYS` format maps your env var to LiteLLM's expected var (e.g., `GOOGLE_API_KEY:key` auto-sets `GEMINI_API_KEY`). Set `EMBEDDING_MODEL` explicitly for other providers.

## MCP Tools

### `memory` — Core memory operations

| Action | Required | Optional |
|--------|----------|----------|
| `add` | `content` | `category`, `tags` |
| `search` | `query` | `category`, `tags`, `limit` |
| `list` | — | `category`, `limit` |
| `update` | `memory_id` | `content`, `category`, `tags` |
| `delete` | `memory_id` | — |
| `export` | — | — |
| `import` | `data` (JSONL) | `mode` (merge/replace) |
| `stats` | — | — |

### `config` — Server configuration

| Action | Required | Optional |
|--------|----------|----------|
| `status` | — | — |
| `sync` | — | — |
| `set` | `key`, `value` | — |

### `help` — Full documentation

```
help(topic="memory")  # or "config"
```

### MCP Resources

| URI | Description |
|-----|-------------|
| `mnemo://stats` | Database statistics and server status |
| `mnemo://recent` | 10 most recently updated memories |

### MCP Prompts

| Prompt | Parameters | Description |
|--------|------------|-------------|
| `save_summary` | `summary` | Generate prompt to save a conversation summary as memory |
| `recall_context` | `topic` | Generate prompt to recall relevant memories about a topic |

## Architecture

```
                  MCP Client (Claude, Cursor, etc.)
                         |
                    FastMCP Server
                   /      |       \
             memory    config    help
                |         |        |
            MemoryDB   Settings  docs/
            /     \
        FTS5    sqlite-vec
                    |
              EmbeddingBackend
              /            \
         LiteLLM        Qwen3 ONNX
            |           (local CPU)
  Gemini / OpenAI /
  Mistral / Cohere

        Sync: rclone (embedded) -> Google Drive / S3 / ...
```

## Development

```bash
# Install
uv sync

# Run
uv run mnemo-mcp

# Lint
uv run ruff check src/
uv run ty check src/

# Test
uv run pytest
```

## License

MIT
