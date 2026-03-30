# Config Tool - Full Documentation

## Overview

The `config` tool shows server status, manages runtime configuration, and handles server setup tasks
(model warmup, sync authentication).

## Actions

### `status` - Show current configuration

Returns database stats, embedding model info, and sync status.

**Parameters:** None

**Returns:**
- `db_path`: Path to SQLite database
- `total_memories`: Total memory count
- `categories`: Memory count by category
- `embedding`: Model name, dimensions, availability
- `sync`: Enabled, provider, folder, interval

### `sync` - Trigger manual sync

Performs a full sync cycle: pull remote changes, merge, push local changes.
Requires `SYNC_ENABLED=true` and `GOOGLE_DRIVE_CLIENT_ID` configured.

**Parameters:** None

**Returns:**
- `pull`: Number of memories imported/skipped from remote
- `push`: Success/failure of push operation

**Sync prerequisites:**
1. Get a token: call `config(action="setup_sync")` (Device Code OAuth flow)
2. Set `SYNC_ENABLED=true` and `GOOGLE_DRIVE_CLIENT_ID` in your MCP config environment
3. The server auto-loads the saved token from `~/.mnemo-mcp/tokens/google_drive.json` -- no extra env vars needed

### `set` - Update a configuration value

Change runtime settings. Changes persist for the current session.

**Parameters:**
- `key` (required): Setting name
- `value` (required): New value

**Available settings:**
- `sync_enabled`: Enable/disable sync ("true" / "false")
- `sync_interval`: Auto-sync interval in seconds (0 = manual)
- `log_level`: Logging level ("DEBUG", "INFO", "WARNING", "ERROR")

**Example:**
```json
{"action": "set", "key": "sync_interval", "value": "300"}
```

### `warmup` - Pre-download embedding model

Downloads the embedding model (~570 MB) so the first real connection does not timeout.
If cloud API keys are configured, validates them instead of downloading the local model.

**Parameters:** None

**Returns:**
- `status`: "ok" or "error"
- `mode`: "cloud" or "local"
- `steps`: List of setup steps with their status
- `embedding`: Model info (when cloud mode)

**Behavior:**
1. If API keys are configured (`API_KEYS` env var), tries cloud embedding models first
2. If cloud models work, returns immediately (no local download needed)
3. If no cloud models or keys, downloads the local Qwen3-Embedding-0.6B ONNX model
4. On corrupted cache, automatically clears and retries

**Example:**
```json
{"action": "warmup"}
```

### `setup_sync` - Authenticate Google Drive

Runs a Device Code OAuth flow to authenticate Google Drive access. Saves the token
locally so no extra env vars are needed for sync.

**Parameters:** None (requires `GOOGLE_DRIVE_CLIENT_ID` env var)

**Returns:**
- `status`: "authenticated" or "error"
- `provider`: "google_drive"
- `token_path`: Path to saved token file
- `next_steps`: Env vars to set in MCP config

**Workflow:**
1. Requests a device code from Google OAuth
2. Displays a URL and code for user to enter in their browser
3. Polls for authorization completion
4. Saves the token to `~/.mnemo-mcp/tokens/google_drive.json`
5. Returns env vars to set in your MCP config

**Example:**
```json
{"action": "setup_sync"}
```

## CLI Equivalents

These MCP tool actions replace the former CLI subcommands:

| CLI (removed) | MCP Tool |
|:--------------|:---------|
| `uvx mnemo-mcp warmup` | `config(action="warmup")` |
| `uvx mnemo-mcp setup-sync` | `config(action="setup_sync")` |

## Environment Variables

Configure via environment variables before starting the server:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | SQLite database path |
| `API_KEYS` | (none) | API keys: `ENV_VAR:key,ENV_VAR:key` |
| `EMBEDDING_BACKEND` | (auto-detect) | `cloud` (API), `local` (qwen3-embed ONNX/GGUF), or empty (auto) |
| `EMBEDDING_MODEL` | (auto-detect) | Provider model name (e.g. jina-embeddings-v5-text-small) or GGUF model ID |
| `EMBEDDING_DIMS` | `0` | Embedding dimensions (0 = auto, resolves to 768) |
| `SYNC_ENABLED` | `false` | Enable Google Drive sync |
| `GOOGLE_DRIVE_CLIENT_ID` | (none) | OAuth client ID for Google Drive |
| `SYNC_FOLDER` | `mnemo-mcp` | Google Drive folder name |
| `SYNC_INTERVAL` | `300` | Auto-sync interval (seconds, 0 = manual) |
| `LOG_LEVEL` | `INFO` | Log level |

### API_KEYS Format

```
API_KEYS="GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-..."
```

The server auto-detects which embedding model to use by trying providers in order:
1. `gemini/gemini-embedding-001` (requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`)
2. `text-embedding-3-large` (requires `OPENAI_API_KEY`)
3. `embed-multilingual-v3.0` (requires `COHERE_API_KEY`)

Set `EMBEDDING_MODEL` explicitly to use a specific model.

For GGUF with GPU support:

```bash
pip install mnemo-mcp[gguf]
# Set EMBEDDING_BACKEND=local and EMBEDDING_MODEL=n24q02m/Qwen3-Embedding-0.6B-GGUF
```

No API keys = local-only mode (uses built-in Qwen3-Embedding-0.6B-ONNX for semantic search).
