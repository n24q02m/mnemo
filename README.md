# Mnemo MCP Server

mcp-name: io.github.n24q02m/mnemo-mcp

**Persistent AI memory with hybrid search and embedded sync. Open, free, unlimited.**

<!-- Badge Row 1: Status -->
[![CI](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/n24q02m/mnemo-mcp/graph/badge.svg?token=GELGVQNMUZ)](https://codecov.io/gh/n24q02m/mnemo-mcp)
[![PyPI](https://img.shields.io/pypi/v/mnemo-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/mnemo-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/mnemo-mcp?label=docker&logo=docker&logoColor=white&sort=semver)](https://hub.docker.com/r/n24q02m/mnemo-mcp)
[![License: MIT](https://img.shields.io/github/license/n24q02m/mnemo-mcp)](LICENSE)

<!-- Badge Row 2: Tech -->
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](#)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](#)
[![MCP](https://img.shields.io/badge/MCP-000000?logo=anthropic&logoColor=white)](#)
[![semantic-release](https://img.shields.io/badge/semantic--release-e10079?logo=semantic-release&logoColor=white)](https://github.com/python-semantic-release/python-semantic-release)
[![Renovate](https://img.shields.io/badge/renovate-enabled-1A1F6C?logo=renovatebot&logoColor=white)](https://developer.mend.io/)

<a href="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp/badge" alt="Mnemo MCP server" />
</a>

## Features

- **Hybrid search** -- FTS5 full-text + sqlite-vec semantic + reranking for precision
- **Knowledge graph** -- Automatic entity extraction and relation tracking across memories
- **Importance scoring** -- LLM-scored 0.0-1.0 per memory for smarter retrieval
- **Auto-archive** -- Configurable age + importance threshold to keep memory clean
- **STM-to-LTM consolidation** -- LLM summarization of related memories in a category
- **Duplicate detection** -- Warns before adding semantically similar memories
- **Zero config** -- Built-in local Qwen3 embedding + reranking, no API keys needed. Optional cloud providers (Jina AI, Gemini, OpenAI, Cohere)
- **Multi-machine sync** -- JSONL-based merge sync via embedded rclone (Google Drive, S3, Dropbox)
- **Proactive memory** -- Tool descriptions guide AI to save preferences, decisions, facts

## Quick Start

### Claude Code Plugin (Recommended)

Via marketplace (includes skills: /session-handoff, /knowledge-audit):

```bash
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins
```



Configure env vars in `~/.claude/settings.local.json` or shell profile. See [Environment Variables](#environment-variables).

### Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.mnemo]
command = "uvx"
args = ["--python", "3.13", "mnemo-mcp"]
```

### MCP Server

#### Option 1: uvx

```jsonc
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["--python", "3.13", "mnemo-mcp@latest"]
    }
  }
}
```

#### Option 2: Docker

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
        "n24q02m/mnemo-mcp:latest"
      ]
    }
  }
}
```

Configure env vars in `~/.claude/settings.local.json` or your shell profile. See [Environment Variables](#environment-variables) below.

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `memory` | `add`, `search`, `list`, `update`, `delete`, `export`, `import`, `stats`, `restore`, `archived`, `consolidate` | Core memory CRUD, hybrid search, import/export, archival, and LLM consolidation |
| `config` | `status`, `sync`, `set`, `warmup`, `setup_sync` | Server status, trigger sync, update settings, pre-download embedding model, authenticate sync provider |
| `help` | -- | Full documentation for any tool |

### MCP Resources

| URI | Description |
|:----|:------------|
| `mnemo://stats` | Database statistics and server status |
| `mnemo://recent` | 10 most recently updated memories |

### MCP Prompts

| Prompt | Parameters | Description |
|:-------|:-----------|:------------|
| `save_summary` | `summary` | Generate prompt to save a conversation summary as memory |
| `recall_context` | `topic` | Generate prompt to recall relevant memories about a topic |

## Zero-Config Setup

No environment variables needed. On first start, the server opens a setup page in your browser:

1. Start the server (via plugin, `uvx`, or Docker)
2. A setup URL appears -- open it in any browser
3. Fill in your credentials on the guided form
4. Credentials are encrypted and stored locally

Your credentials never leave your machine. The relay server only sees encrypted data.

For CI/automation, you can still use environment variables (see below).

## Configuration

### Pre-install (optional)

Pre-download the embedding model (~570 MB) to avoid first-run delays.
Use the `config` MCP tool after connecting:

```
config(action="warmup")
```

### Sync setup

Sync is fully automatic. Just set `SYNC_ENABLED=true` and the server handles everything:

1. **First sync**: rclone is auto-downloaded, a browser opens for OAuth authentication
2. **Token saved**: OAuth token is stored locally at `~/.mnemo-mcp/tokens/` (600 permissions)
3. **Subsequent runs**: Token is loaded automatically -- no manual steps needed

For non-Google Drive providers, set `SYNC_PROVIDER` and `SYNC_REMOTE`:

```jsonc
{
  "SYNC_ENABLED": "true",
  "SYNC_PROVIDER": "dropbox",
  "SYNC_REMOTE": "dropbox"
}
```

### Environment Variables

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `API_KEYS` | No | -- | API keys (`ENV:key,ENV:key`). Enables cloud embedding + reranking |
| `COHERE_API_KEY` | No | -- | Cohere API key (embedding + reranking) |
| `JINA_AI_API_KEY` | No | -- | Jina AI API key (embedding + reranking) |
| `GEMINI_API_KEY` | No | -- | Google Gemini API key (LLM + embedding) |
| `OPENAI_API_KEY` | No | -- | OpenAI API key (LLM + embedding) |
| `DB_PATH` | No | `~/.mnemo-mcp/memories.db` | Database location |
| `EMBEDDING_BACKEND` | No | auto-detect | `cloud` (auto-detect from API keys: Jina > Gemini > OpenAI > Cohere) or `local` (Qwen3) |
| `EMBEDDING_MODEL` | No | auto-detect | Cloud embedding model name |
| `EMBEDDING_DIMS` | No | `0` (auto=768) | Embedding dimensions |
| `RERANK_ENABLED` | No | `true` | Enable reranking (improves search precision) |
| `RERANK_BACKEND` | No | auto-detect | `cloud` (auto-detect from API keys: Jina > Cohere) or `local` (Qwen3) |
| `RERANK_MODEL` | No | auto-detect | Cloud reranker model name |
| `RERANK_TOP_N` | No | `10` | Number of top results to keep after reranking |
| `LLM_MODELS` | No | `gemini-3-flash-preview` | LLM model for graph extraction, importance scoring, consolidation (google-genai or openai) |
| `ARCHIVE_ENABLED` | No | `true` | Enable auto-archiving of old low-importance memories |
| `ARCHIVE_AFTER_DAYS` | No | `90` | Days before a memory is eligible for auto-archive |
| `ARCHIVE_IMPORTANCE_THRESHOLD` | No | `0.3` | Memories below this importance score are auto-archived |
| `DEDUP_THRESHOLD` | No | `0.9` | Similarity threshold to block duplicate memories |
| `DEDUP_WARN_THRESHOLD` | No | `0.7` | Similarity threshold to warn about similar memories |
| `RECENCY_HALF_LIFE_DAYS` | No | `7` | Half-life for temporal decay in search scoring |
| `SYNC_ENABLED` | No | `false` | Enable rclone sync |
| `SYNC_PROVIDER` | No | `drive` | rclone provider type (drive, dropbox, s3, etc.) |
| `SYNC_REMOTE` | No | `gdrive` | rclone remote name |
| `SYNC_FOLDER` | No | `mnemo-mcp` | Remote folder |
| `SYNC_INTERVAL` | No | `300` | Auto-sync interval in seconds (0=manual) |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### Embedding & Reranking

Both embedding and reranking are **always available** -- local models are built-in and require no configuration.

- **Jina AI (recommended)**: A single `JINA_AI_API_KEY` enables both embedding and reranking
- **Embedding priority**: Jina AI > Gemini > OpenAI > Cohere. Local Qwen3 fallback always available
- **Reranking priority**: Jina AI > Cohere. Local Qwen3 fallback always available
- **GPU auto-detection**: CUDA/DirectML auto-detected, uses GGUF models for better performance
- All embeddings stored at **768 dims**. Switching providers never breaks the vector table

## Security

- **Graceful fallbacks** -- Cloud → Local embedding, no cross-mode fallback
- **Sync token security** -- OAuth tokens stored at `~/.mnemo-mcp/tokens/` with 600 permissions
- **Input validation** -- Sync provider, folder, remote validated against allowlists
- **Error sanitization** -- No credentials in error messages

## Build from Source

```bash
git clone https://github.com/n24q02m/mnemo-mcp.git
cd mnemo-mcp
uv sync
uv run mnemo-mcp
```

## License

MIT -- See [LICENSE](LICENSE).
