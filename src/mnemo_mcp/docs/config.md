# Config Tool - Full Documentation

## Overview

The `config` tool shows server status and manages runtime configuration.

## Actions

### `status` - Show current configuration

Returns database stats, embedding model info, sync status, and API key status.

**Parameters:** None

**Returns:**
- `db_path`: Path to SQLite database
- `total_memories`: Total memory count
- `categories`: Memory count by category
- `embedding`: Model name, dimensions, availability
- `sync`: Enabled, remote, folder, interval, rclone status

### `sync` - Trigger manual sync

Performs a full sync cycle: pull remote changes, merge, push local changes.
Requires `SYNC_ENABLED=true` and `SYNC_REMOTE` configured.

**Parameters:** None

**Returns:**
- `pull`: Number of memories imported/skipped from remote
- `push`: Success/failure of push operation

**Sync prerequisites:**
1. Get a token: `uvx mnemo-mcp setup-sync drive` (downloads rclone + opens browser)
2. Set env vars in MCP config:
   - `RCLONE_CONFIG_<REMOTE>_TYPE`: remote type (e.g., `drive`, `s3`)
   - `RCLONE_CONFIG_<REMOTE>_TOKEN`: token JSON from step 1
3. `SYNC_ENABLED=true` and `SYNC_REMOTE=<remote_name>` in environment

### `set` - Update a configuration value

Change runtime settings. Changes persist for the current session.

**Parameters:**
- `key` (required): Setting name
- `value` (required): New value

**Available settings:**
- `sync_enabled`: Enable/disable sync ("true" / "false")
- `sync_remote`: Rclone remote name
- `sync_folder`: Remote folder name
- `sync_interval`: Auto-sync interval in seconds (0 = manual)
- `log_level`: Logging level ("DEBUG", "INFO", "WARNING", "ERROR")

**Example:**
```json
{"action": "set", "key": "sync_interval", "value": "300"}
```

## Environment Variables

Configure via environment variables before starting the server:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | SQLite database path |
| `API_KEYS` | (none) | API keys: `ENV_VAR:key,ENV_VAR:key` |
| `EMBEDDING_MODEL` | (auto-detect) | LiteLLM model name |
| `EMBEDDING_DIMS` | `768` | Fixed embedding dimensions (all vectors truncated to this size) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | (none) | Rclone remote name |
| `SYNC_FOLDER` | `mnemo-mcp` | Remote folder name |
| `SYNC_INTERVAL` | `0` | Auto-sync interval (seconds) |
| `LOG_LEVEL` | `INFO` | Log level |

### API_KEYS Format

```
API_KEYS="GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-..."
```

The server auto-detects which embedding model to use by trying providers in order:
1. `gemini/gemini-embedding-001` (requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`)
2. `text-embedding-3-small` (requires `OPENAI_API_KEY`)
3. `mistral/mistral-embed` (requires `MISTRAL_API_KEY`)
4. `embed-english-v3.0` (requires `COHERE_API_KEY`)

Set `EMBEDDING_MODEL` explicitly to use a specific model.

No API keys = FTS5-only mode (text search without semantic search).
