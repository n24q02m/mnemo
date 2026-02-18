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

### Option 1: uvx (Recommended)

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp@latest"],
      "env": {
        // -- optional: cloud embedding (Gemini > OpenAI > Mistral > Cohere) for semantic search
        // -- without this, uses built-in local Qwen3-Embedding-0.6B (ONNX, CPU)
        // -- first run downloads ~570MB model, cached for subsequent runs
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        // -- optional: sync memories across machines via rclone
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_REMOTE": "gdrive",                   // required when SYNC_ENABLED=true
        "SYNC_INTERVAL": "300",                    // optional, auto-sync every 5min (0 = manual only)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",      // required when SYNC_ENABLED=true
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"   // required when SYNC_ENABLED=true, from: uvx mnemo-mcp setup-sync drive
      }
    }
  }
}
```

### Option 2: Docker

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-mnemo",
        "-v", "mnemo-data:/data",                  // persists memories across restarts
        "-e", "API_KEYS",                          // optional: pass-through from env below
        "-e", "SYNC_ENABLED",                      // optional: pass-through from env below
        "-e", "SYNC_REMOTE",                       // required when SYNC_ENABLED=true: pass-through
        "-e", "SYNC_INTERVAL",                     // optional: pass-through from env below
        "-e", "RCLONE_CONFIG_GDRIVE_TYPE",         // required when SYNC_ENABLED=true: pass-through
        "-e", "RCLONE_CONFIG_GDRIVE_TOKEN",        // required when SYNC_ENABLED=true: pass-through
        "n24q02m/mnemo-mcp:latest"
      ],
      "env": {
        // -- optional: cloud embedding (Gemini > OpenAI > Mistral > Cohere) for semantic search
        // -- without this, uses built-in local Qwen3-Embedding-0.6B (ONNX, CPU)
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        // -- optional: sync memories across machines via rclone
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_REMOTE": "gdrive",                   // required when SYNC_ENABLED=true
        "SYNC_INTERVAL": "300",                    // optional, auto-sync every 5min (0 = manual only)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",      // required when SYNC_ENABLED=true
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"   // required when SYNC_ENABLED=true, from: uvx mnemo-mcp setup-sync drive
      }
    }
  }
}
```

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
| `EMBEDDING_BACKEND` | (auto-detect) | `litellm` (cloud API) or `local` (Qwen3). Auto: API_KEYS -> litellm, else local (always available) |
| `EMBEDDING_MODEL` | auto-detect | LiteLLM model name (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (0 = auto-detect, default 768) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | — | rclone remote name (required when sync enabled) |
| `SYNC_FOLDER` | `mnemo-mcp` | Remote folder (optional) |
| `SYNC_INTERVAL` | `0` | Auto-sync seconds (optional, 0=manual) |
| `LOG_LEVEL` | `INFO` | Log level (optional) |

### Embedding

Embedding is **always available** — a local model is built-in and requires no configuration.

- **Default**: Local Qwen3-Embedding-0.6B. Set `API_KEYS` to upgrade to cloud (Gemini > OpenAI > Mistral > Cohere), with automatic local fallback if cloud fails.
- **GPU auto-detection**: If GPU is available (CUDA/DirectML) and `llama-cpp-python` is installed, automatically uses GGUF model (~480MB) instead of ONNX (~570MB) for better performance.
- All embeddings stored at **768 dims** (default). Switching providers never breaks the vector table.
- Override with `EMBEDDING_BACKEND=local` to force local even with API keys.

`API_KEYS` supports multiple providers in a single string:
```
API_KEYS=GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-...,COHERE_API_KEY:co-...
```

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
