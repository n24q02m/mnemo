# Mnemo MCP Server

**Persistent AI memory with hybrid search and embedded sync. Open, free, unlimited.**

[![CI](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/n24q02m/mnemo-mcp/graph/badge.svg?token=GELGVQNMUZ)](https://codecov.io/gh/n24q02m/mnemo-mcp)
[![PyPI](https://img.shields.io/pypi/v/mnemo-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/mnemo-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/mnemo-mcp?label=docker&logo=docker&logoColor=white&sort=semver)](https://hub.docker.com/r/n24q02m/mnemo-mcp)
[![License: MIT](https://img.shields.io/github/license/n24q02m/mnemo-mcp)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](#)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](#)
[![MCP](https://img.shields.io/badge/MCP-000000?logo=anthropic&logoColor=white)](#)
[![semantic-release](https://img.shields.io/badge/semantic--release-e10079?logo=semantic-release&logoColor=white)](https://github.com/python-semantic-release/python-semantic-release)
[![Renovate](https://img.shields.io/badge/renovate-enabled-1A1F6C?logo=renovatebot&logoColor=white)](https://developer.mend.io/)

## Features

- **Hybrid search**: FTS5 full-text + sqlite-vec semantic + Qwen3-Embedding-0.6B (built-in)
- **Zero config mode**: Works out of the box — local embedding, no API keys needed
- **Auto-detect embedding**: Set `API_KEYS` for cloud embedding, auto-fallback to local
- **Embedded sync**: rclone auto-downloaded and managed as subprocess
- **Multi-machine**: JSONL-based merge sync via rclone (Google Drive, S3, etc.)
- **Proactive memory**: Tool descriptions guide AI to save preferences, decisions, facts

## Quick Start

The recommended way to run this server is via `uvx`:

```bash
uvx mnemo-mcp@latest
```

> Alternatively, you can use `pipx run mnemo-mcp`.

### Option 1: uvx (Recommended)

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp@latest"],
      "env": {
        // -- optional: cloud embedding (Gemini > OpenAI > Cohere) for semantic search
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
        // -- optional: cloud embedding (Gemini > OpenAI > Cohere) for semantic search
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

### Pre-install (optional)

Pre-download dependencies before adding to your MCP client config. This avoids slow first-run startup:

```bash
# Pre-download embedding model (~570MB) and validate API keys
uvx mnemo-mcp warmup

# With cloud embedding (validates API key, skips local download if cloud works)
API_KEYS="GOOGLE_API_KEY:AIza..." uvx mnemo-mcp warmup
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
| `LITELLM_PROXY_URL` | — | LiteLLM Proxy URL (e.g. `http://10.0.0.20:4000`). Enables proxy mode |
| `LITELLM_PROXY_KEY` | — | LiteLLM Proxy virtual key (e.g. `sk-...`) |
| `API_KEYS` | — | API keys (`ENV:key,ENV:key`). Optional: enables semantic search (SDK mode) |
| `EMBEDDING_API_BASE` | — | Custom embedding endpoint URL (optional, for SDK mode) |
| `EMBEDDING_API_KEY` | — | Custom embedding endpoint key (optional) |
| `EMBEDDING_BACKEND` | (auto-detect) | `litellm` (cloud API) or `local` (Qwen3). Auto: API_KEYS -> litellm, else local (always available) |
| `EMBEDDING_MODEL` | auto-detect | LiteLLM model name (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (0 = auto-detect, default 768) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | — | rclone remote name (required when sync enabled) |
| `SYNC_FOLDER` | `mnemo-mcp` | Remote folder (optional) |
| `SYNC_INTERVAL` | `0` | Auto-sync seconds (optional, 0=manual) |
| `LOG_LEVEL` | `INFO` | Log level (optional) |

### Embedding (3-Mode Architecture)

Embedding is **always available** — a local model is built-in and requires no configuration.

Embedding access supports 3 modes, resolved by priority:

| Priority | Mode | Config | Use case |
|:---------|:-----|:-------|:---------|
| 1 | **Proxy** | `LITELLM_PROXY_URL` + `LITELLM_PROXY_KEY` | Production (OCI VM, selfhosted gateway) |
| 2 | **SDK** | `API_KEYS` or `EMBEDDING_API_BASE` | Dev/local with direct API access |
| 3 | **Local** | Nothing needed | Offline, always available as fallback |

No cross-mode fallback — if proxy is configured but unreachable, calls fail (no silent fallback to direct API).

```jsonc
// In your MCP client config (Claude Desktop, Cursor, etc.):
"env": {
  // === Mode 1: Proxy (production) ===
  "LITELLM_PROXY_URL": "http://10.0.0.20:4000",
  "LITELLM_PROXY_KEY": "sk-your-virtual-key",

  // === Mode 2: SDK (direct API) ===
  "API_KEYS": "GOOGLE_API_KEY:AIza...",

  // === Mode 2: SDK (custom endpoint, e.g. modalcom-ai-workers) ===
  "EMBEDDING_API_BASE": "https://your-worker.modal.run",
  "EMBEDDING_API_KEY": "your-key"

  // === Mode 3: Local — no env needed, always available ===
}
```

- **Local mode**: Qwen3-Embedding-0.6B, always available with zero config.
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
| 2 | `OPENAI_API_KEY` | `text-embedding-3-large` | 3072 | 768 |
| 3 | `COHERE_API_KEY` | `embed-multilingual-v3.0` | 1024 | 768 |

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
  Gemini / OpenAI / Cohere

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

## Related Projects

- **[modalcom-ai-workers](https://github.com/n24q02m/modalcom-ai-workers)** — GPU-accelerated AI workers on Modal.com (embedding, reranking)
- **[qwen3-embed](https://github.com/n24q02m/qwen3-embed)** — Local embedding/reranking library used by mnemo-mcp

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT - See [LICENSE](LICENSE)
