# Mnemo MCP Server

mcp-name: io.github.n24q02m/mnemo-mcp

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

<a href="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp/badge" alt="Mnemo MCP server" />
</a>

## Features

- **Hybrid search**: FTS5 full-text + sqlite-vec semantic + reranking for precision
- **Reranking**: Dual-backend — Jina/Cohere cloud or Qwen3 local cross-encoder
- **Knowledge graph**: Automatic entity extraction and relation tracking across memories
- **Importance scoring**: LLM-scored 0.0-1.0 per memory for smarter retrieval
- **Auto-archive**: Configurable age + importance threshold to keep memory clean
- **STM-to-LTM consolidation**: LLM summarization of related memories in a category
- **Duplicate detection**: Warns before adding semantically similar memories
- **Configurable temporal decay**: Tune recency bias via `RECENCY_HALF_LIFE_DAYS`
- **Zero config mode**: Works out of the box — local embedding + reranking, no API keys needed
- **Auto-detect providers**: Set `API_KEYS` for cloud embedding/reranking, auto-fallback to local
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
        // -- optional: LiteLLM Proxy (production, selfhosted gateway)
        // "LITELLM_PROXY_URL": "http://10.0.0.20:4000",
        // "LITELLM_PROXY_KEY": "sk-your-virtual-key",
        // -- optional: cloud embedding + reranking (Jina > Gemini > OpenAI > Cohere)
        // -- without this, uses built-in local Qwen3 ONNX models (CPU)
        // -- first run downloads ~570MB model per backend, cached for subsequent runs
        // -- Jina AI recommended: single key for both embedding and reranking
        "API_KEYS": "JINA_AI_API_KEY:jina_...",
        // -- optional: sync memories across machines via rclone
        // -- on first sync, a browser opens for OAuth (auto, no manual setup)
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_INTERVAL": "300"                     // optional, auto-sync every 5min (0 = manual only)
        // "SYNC_REMOTE": "gdrive",                 // optional, default: gdrive
        // "SYNC_PROVIDER": "drive",                // optional, default: drive (Google Drive)
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
        "-e", "LITELLM_PROXY_URL",                 // optional: pass-through from env below
        "-e", "LITELLM_PROXY_KEY",                 // optional: pass-through from env below
        "-e", "API_KEYS",                          // optional: pass-through from env below
        "-e", "SYNC_ENABLED",                      // optional: pass-through from env below
        "-e", "SYNC_INTERVAL",                     // optional: pass-through from env below
        "n24q02m/mnemo-mcp:latest"
      ],
      "env": {
        // -- optional: LiteLLM Proxy (production, selfhosted gateway)
        // "LITELLM_PROXY_URL": "http://10.0.0.20:4000",
        // "LITELLM_PROXY_KEY": "sk-your-virtual-key",
        // -- optional: cloud embedding + reranking (Jina > Gemini > OpenAI > Cohere)
        // -- without this, uses built-in local Qwen3 ONNX models (CPU)
        "API_KEYS": "JINA_AI_API_KEY:jina_...",
        // -- optional: sync memories across machines via rclone
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_INTERVAL": "300"                     // optional, auto-sync every 5min (0 = manual only)
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
API_KEYS="JINA_AI_API_KEY:jina_..." uvx mnemo-mcp warmup
```

### Sync setup

Sync is fully automatic. Just set `SYNC_ENABLED=true` and the server handles everything:

1. **First sync**: rclone is auto-downloaded, a browser opens for OAuth authentication
2. **Token saved**: OAuth token is stored locally at `~/.mnemo-mcp/tokens/` (600 permissions)
3. **Subsequent runs**: Token is loaded automatically — no manual steps needed

For non-Google Drive providers, set `SYNC_PROVIDER` and `SYNC_REMOTE`:

```jsonc
{
  "SYNC_ENABLED": "true",
  "SYNC_PROVIDER": "dropbox",        // rclone provider type
  "SYNC_REMOTE": "dropbox"           // rclone remote name
}
```

> **Advanced**: You can also run `uvx mnemo-mcp setup-sync drive` to pre-authenticate before first use, but this is optional.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | Database location |
| `LITELLM_PROXY_URL` | — | LiteLLM Proxy URL (e.g. `http://10.0.0.20:4000`). Enables proxy mode |
| `LITELLM_PROXY_KEY` | — | LiteLLM Proxy virtual key (e.g. `sk-...`) |
| `API_KEYS` | — | API keys (`ENV:key,ENV:key`). Enables cloud embedding + reranking (SDK mode) |
| `EMBEDDING_BACKEND` | (auto-detect) | `litellm` (cloud API) or `local` (Qwen3). Auto: API_KEYS -> litellm, else local |
| `EMBEDDING_MODEL` | auto-detect | LiteLLM model name (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (0 = auto-detect, default 768) |
| `RERANK_ENABLED` | `true` | Enable reranking (improves search precision) |
| `RERANK_BACKEND` | (auto-detect) | `litellm` (cloud) or `local` (Qwen3). Auto: API_KEYS -> litellm, else local |
| `RERANK_MODEL` | auto-detect | LiteLLM reranker model name (optional) |
| `ARCHIVE_ENABLED` | `true` | Enable auto-archiving of old low-importance memories |
| `ARCHIVE_AFTER_DAYS` | `90` | Days before a memory is eligible for auto-archive |
| `ARCHIVE_IMPORTANCE_THRESHOLD` | `0.3` | Memories below this importance score are auto-archived |
| `DEDUP_THRESHOLD` | `0.9` | Similarity threshold to block duplicate memories |
| `DEDUP_WARN_THRESHOLD` | `0.7` | Similarity threshold to warn about similar memories |
| `RECENCY_HALF_LIFE_DAYS` | `7` | Half-life for temporal decay in search scoring |
| `LLM_MODELS` | `gemini/gemini-3-flash-preview` | LLM model for graph extraction, importance scoring, consolidation |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_PROVIDER` | `drive` | rclone provider type (drive, dropbox, s3, etc.) |
| `SYNC_REMOTE` | `gdrive` | rclone remote name |
| `SYNC_FOLDER` | `mnemo-mcp` | Remote folder |
| `SYNC_INTERVAL` | `300` | Auto-sync seconds (0=manual) |
| `LOG_LEVEL` | `INFO` | Log level |

### Embedding & Reranking (2-Mode Architecture)

Embedding and reranking are **always available** — local models are built-in and require no configuration.

Both embedding and reranking support 2 modes, resolved by priority:

| Priority | Mode | Config | Use case |
|:---------|:-----|:-------|:---------|
| 1 | **Proxy / SDK** | `LITELLM_PROXY_URL` + `LITELLM_PROXY_KEY` or `API_KEYS` | Production or dev with cloud APIs |
| 2 | **Local** | Nothing needed | Offline, always available as fallback |

No cross-mode fallback — if proxy is configured but unreachable, calls fail (no silent fallback to direct API).

- **Local mode**: Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B, always available with zero config.
- **GPU auto-detection**: If GPU is available (CUDA/DirectML) and `llama-cpp-python` is installed, automatically uses GGUF models instead of ONNX for better performance.
- All embeddings stored at **768 dims** (default). Switching providers never breaks the vector table.
- Override with `EMBEDDING_BACKEND=local` or `RERANK_BACKEND=local` to force local even with API keys.

`API_KEYS` supports multiple providers in a single string:
```
API_KEYS=JINA_AI_API_KEY:jina_...,GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-...,COHERE_API_KEY:co-...
```

**Jina AI is the recommended provider** — a single `JINA_AI_API_KEY` enables both embedding (`jina-embeddings-v5-text-small`) and reranking (`jina-reranker-v3`), giving you the best search quality with one key.

Cloud embedding providers (auto-detected from `API_KEYS`, priority order):

| Priority | Env Var | Model | Native Dims | Stored |
|----------|---------|-------|-------------|--------|
| 1 | `JINA_AI_API_KEY` | `jina-embeddings-v5-text-small` | 1024 | 768 |
| 2 | `GEMINI_API_KEY` | `gemini/gemini-embedding-001` | 3072 | 768 |
| 3 | `OPENAI_API_KEY` | `text-embedding-3-large` | 3072 | 768 |
| 4 | `COHERE_API_KEY` | `embed-multilingual-v3.0` | 1024 | 768 |

Cloud reranking providers (auto-detected from `API_KEYS`, priority order):

| Priority | Env Var | Model |
|----------|---------|-------|
| 1 | `JINA_AI_API_KEY` | `jina-reranker-v3` |
| 2 | `COHERE_API_KEY` | `rerank-multilingual-v3.0` |

All embeddings are truncated to **768 dims** (default) for storage. This ensures switching models never breaks the vector table. Override with `EMBEDDING_DIMS` if needed.

`API_KEYS` format maps your env var to LiteLLM's expected var (e.g., `GOOGLE_API_KEY:key` auto-sets `GEMINI_API_KEY`). Set `EMBEDDING_MODEL` or `RERANK_MODEL` explicitly for other providers.

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
| `restore` | `memory_id` | — |
| `archived` | — | `limit` |
| `consolidate` | `category` | — |

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
           /   |   \
       FTS5  sqlite-vec  KnowledgeGraph
                |              |
          EmbeddingBackend   LLM (entity extraction,
          /            \      importance, consolidation)
     LiteLLM        Qwen3 ONNX
        |           (local CPU)      RerankerBackend
  Jina / Gemini /                    /            \
  OpenAI / Cohere               LiteLLM      Qwen3 ONNX
                              Jina/Cohere    (local CPU)

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

## Compatible With

[![Claude Desktop](https://img.shields.io/badge/Claude_Desktop-F9DC7C?logo=anthropic&logoColor=black)](#quick-start)
[![Claude Code](https://img.shields.io/badge/Claude_Code-000000?logo=anthropic&logoColor=white)](#quick-start)
[![Cursor](https://img.shields.io/badge/Cursor-000000?logo=cursor&logoColor=white)](#quick-start)
[![VS Code Copilot](https://img.shields.io/badge/VS_Code_Copilot-007ACC?logo=visualstudiocode&logoColor=white)](#quick-start)
[![Antigravity](https://img.shields.io/badge/Antigravity-4285F4?logo=google&logoColor=white)](#quick-start)
[![Gemini CLI](https://img.shields.io/badge/Gemini_CLI-8E75B2?logo=googlegemini&logoColor=white)](#quick-start)
[![OpenAI Codex](https://img.shields.io/badge/Codex-412991?logo=openai&logoColor=white)](#quick-start)
[![OpenCode](https://img.shields.io/badge/OpenCode-F7DF1E?logoColor=black)](#quick-start)

## Also by n24q02m

| Server | Description | Install |
|--------|-------------|---------|
| [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) | Notion API for AI agents | `npx -y @n24q02m/better-notion-mcp@latest` |
| [wet-mcp](https://github.com/n24q02m/wet-mcp) | Web search, content extraction, library docs | `uvx --python 3.13 wet-mcp@latest` |
| [better-email-mcp](https://github.com/n24q02m/better-email-mcp) | Email (IMAP/SMTP) for AI agents | `npx -y @n24q02m/better-email-mcp@latest` |
| [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) | Godot Engine for AI agents | `npx -y @n24q02m/better-godot-mcp@latest` |
| [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) | Telegram Bot API + MTProto for AI agents | `uvx --python 3.13 better-telegram-mcp@latest` |

## Related Projects

- **[modalcom-ai-workers](https://github.com/n24q02m/modalcom-ai-workers)** — GPU-accelerated AI workers on Modal.com (embedding, reranking)
- **[qwen3-embed](https://github.com/n24q02m/qwen3-embed)** — Local embedding/reranking library used by mnemo-mcp

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT - See [LICENSE](LICENSE)
