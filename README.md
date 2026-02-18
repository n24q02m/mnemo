# Mnemo MCP Server

**Persistent AI memory with hybrid search and embedded sync. Open, free, unlimited.**

[![PyPI](https://img.shields.io/pypi/v/mnemo-mcp)](https://pypi.org/project/mnemo-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/mnemo-mcp?label=docker)](https://hub.docker.com/r/n24q02m/mnemo-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Hybrid search**: FTS5 full-text + sqlite-vec semantic (when embedding model available)
- **Zero dependency mode**: Works with SQLite FTS5 only — no API keys needed
- **Auto-detect embedding**: Set `API_KEYS` and the server picks the right model
- **Embedded sync**: rclone auto-downloaded and managed as subprocess
- **Multi-machine**: JSONL-based merge sync via rclone (Google Drive, S3, etc.)
- **Proactive memory**: Tool descriptions guide AI to save preferences, decisions, facts

## Install

```bash
# With uv (recommended)
uvx mnemo-mcp

# With local Qwen3 ONNX embedding (no API keys needed)
uvx --extra local mnemo-mcp

# With local GGUF embedding (GPU support via llama-cpp-python)
uvx --extra gguf mnemo-mcp

# With pip
pip install mnemo-mcp

# With local embedding
pip install mnemo-mcp[local]

# With GGUF embedding (GPU)
pip install mnemo-mcp[gguf]
```

## Quick Start

### Minimal (FTS5 only, no API keys)

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp"]
    }
  }
}
```

### With local embedding (no API keys)

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["--extra", "local", "mnemo-mcp"]
      // No API_KEYS needed -- Qwen3-Embedding-0.6B runs locally on CPU
    }
  }
}
```

### With embeddings (cloud API)

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp"],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza..."
      }
    }
  }
}
```

### With sync (multi-machine)

**Step 1**: Get a drive token (one-time, requires browser):

```bash
uvx mnemo-mcp setup-sync drive
```

This downloads rclone, opens a browser for Google Drive auth, and outputs a **base64-encoded token** for `RCLONE_CONFIG_GDRIVE_TOKEN`.

**Step 2**: Copy the token and add it to your MCP config:

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp"],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...", // optional: enables semantic search
        "SYNC_ENABLED": "true",               // required for sync
        "SYNC_REMOTE": "gdrive",               // required: rclone remote name
        "SYNC_INTERVAL": "300",                // optional: auto-sync seconds (default: 0 = manual)
        // "SYNC_FOLDER": "mnemo-mcp",          // optional: remote folder (default: mnemo-mcp)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",  // required: rclone backend type
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<paste base64 token>" // required: from setup-sync
      }
    }
  }
}
```

Both raw JSON and base64-encoded tokens are supported. Base64 is recommended — it avoids nested JSON escaping issues.

Remote is configured via env vars — works in any environment (local, Docker, CI).

### With Docker

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-mnemo",
        "-v", "mnemo-data:/data",
        "-e", "API_KEYS",
        "-e", "DB_PATH",
        "n24q02m/mnemo-mcp:latest"
      ],
      "env": {
        "DB_PATH": "/data/memories.db",
        "API_KEYS": "GOOGLE_API_KEY:AIza..."
      }
    }
  }
}
```

### With sync in Docker

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-mnemo",
        "-v", "mnemo-data:/data",
        "-e", "DB_PATH",
        "-e", "API_KEYS",
        "-e", "SYNC_ENABLED",
        "-e", "SYNC_REMOTE",
        "-e", "SYNC_INTERVAL",     // optional: remove if manual sync only
        "-e", "RCLONE_CONFIG_GDRIVE_TYPE",
        "-e", "RCLONE_CONFIG_GDRIVE_TOKEN",
        "n24q02m/mnemo-mcp:latest"
      ],
      "env": {
        "DB_PATH": "/data/memories.db",
        "API_KEYS": "GOOGLE_API_KEY:AIza...", // optional: enables semantic search
        "SYNC_ENABLED": "true",               // required for sync
        "SYNC_REMOTE": "gdrive",               // required: rclone remote name
        "SYNC_INTERVAL": "300",                // optional: auto-sync seconds (default: 0 = manual)
        // "SYNC_FOLDER": "mnemo-mcp",          // optional: remote folder (default: mnemo-mcp)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",  // required: rclone backend type
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<paste base64 token>" // required: from setup-sync
      }
    }
  }
}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | Database location |
| `API_KEYS` | — | API keys (`ENV:key,ENV:key`). Optional: enables semantic search |
| `EMBEDDING_BACKEND` | (auto-detect) | `litellm` (cloud API) or `local` (Qwen3 ONNX/GGUF). Auto: local > litellm > FTS5-only |
| `EMBEDDING_MODEL` | auto-detect | LiteLLM model name, or `Qwen/Qwen3-Embedding-0.6B-GGUF` for GGUF (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (0 = auto-detect, default 768) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | — | rclone remote name (required when sync enabled) |
| `SYNC_FOLDER` | `mnemo-mcp` | Remote folder (optional) |
| `SYNC_INTERVAL` | `0` | Auto-sync seconds (optional, 0=manual) |
| `LOG_LEVEL` | `INFO` | Log level (optional) |

### Supported Embedding Providers

The server auto-detects the best available embedding backend:

1. **Local (Qwen3 ONNX)** — If `qwen3-embed` is installed (`pip install mnemo-mcp[local]`), uses Qwen3-Embedding-0.6B on CPU. No API keys needed.
2. **Cloud (LiteLLM)** — Detects API keys and picks the best model:

| Priority | Env Var (LiteLLM) | Model | Native Dims | Stored |
|----------|-------------------|-------|-------------|--------|
| 1 | `GEMINI_API_KEY` | `gemini/gemini-embedding-001` | 3072 | 768 |
| 2 | `OPENAI_API_KEY` | `text-embedding-3-small` | 1536 | 768 |
| 3 | `MISTRAL_API_KEY` | `mistral/mistral-embed` | 1024 | 768 |
| 4 | `COHERE_API_KEY` | `embed-english-v3.0` | 1024 | 768 |

All embeddings are truncated to **768 dims** (default) for storage. This ensures switching models never breaks the vector table. Override with `EMBEDDING_DIMS` if needed.

`API_KEYS` format maps your env var to LiteLLM's expected var (e.g., `GOOGLE_API_KEY:key` auto-sets `GEMINI_API_KEY`). Set `EMBEDDING_MODEL` explicitly for other providers.

Override auto-detection with `EMBEDDING_BACKEND=litellm` or `EMBEDDING_BACKEND=local`.

No API keys and no `qwen3-embed` = FTS5-only mode (text search works perfectly, just no semantic similarity).

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
