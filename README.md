# Mnemo MCP Server

Persistent AI memory with hybrid search and embedded sync. Open, free, unlimited.

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

# With pip
pip install mnemo-mcp
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

### With embeddings (semantic search)

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

This downloads rclone, opens a browser for Google Drive auth, and outputs a ready-to-paste MCP config with the properly escaped token.

**Step 2**: Copy the output JSON into your MCP config file.

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp"],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        "SYNC_ENABLED": "true",
        "SYNC_REMOTE": "gdrive",
        "SYNC_INTERVAL": "300",
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<paste token JSON>"
      }
    }
  }
}
```

Remote is configured via env vars — works in any environment (local, Docker, CI).

### With Docker

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "API_KEYS=GOOGLE_API_KEY:AIza...",
        "-v", "mnemo-data:/data",
        "-e", "DB_PATH=/data/memories.db",
        "n24q02m/mnemo-mcp:latest"
      ]
    }
  }
}
```

For sync in Docker, add `-e SYNC_ENABLED=true`, `-e SYNC_REMOTE=gdrive`, and `RCLONE_CONFIG_*` env vars to args.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | Database location |
| `API_KEYS` | — | API keys (`ENV:key,ENV:key`) |
| `EMBEDDING_MODEL` | auto-detect | LiteLLM model name |
| `EMBEDDING_DIMS` | `768` | Embedding dimensions (fixed, override if needed) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | — | rclone remote name |
| `SYNC_FOLDER` | `mnemo-mcp` | Remote folder |
| `SYNC_INTERVAL` | `0` | Auto-sync seconds (0=manual) |
| `LOG_LEVEL` | `INFO` | Log level |

### Supported Embedding Providers

The server auto-detects embedding models by trying each provider in order:

| Priority | Env Var (LiteLLM) | Model | Native Dims | Stored |
|----------|-------------------|-------|-------------|--------|
| 1 | `GEMINI_API_KEY` | `gemini/gemini-embedding-001` | 3072 | 768 |
| 2 | `OPENAI_API_KEY` | `text-embedding-3-small` | 1536 | 768 |
| 3 | `MISTRAL_API_KEY` | `mistral/mistral-embed` | 1024 | 768 |
| 4 | `COHERE_API_KEY` | `embed-english-v3.0` | 1024 | 768 |

All embeddings are truncated to **768 dims** (default) for storage. This ensures switching models never breaks the vector table. Override with `EMBEDDING_DIMS` if needed.

`API_KEYS` format maps your env var to LiteLLM's expected var (e.g., `GOOGLE_API_KEY:key` auto-sets `GEMINI_API_KEY`). Set `EMBEDDING_MODEL` explicitly for other providers.

No API keys = FTS5-only mode (text search works perfectly, just no semantic similarity).

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
| `import` | `data` | `mode` (merge/replace) |
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
              LiteLLM embed
                    |
        Gemini / OpenAI / Mistral / Cohere

        Sync: rclone (embedded) → Google Drive / S3 / ...
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
