# Config Tool - Full Documentation

## Overview

The `config` tool shows server status, manages runtime configuration, and
handles server setup tasks (model warmup, credential setup, Google Drive
sync). The previously separate `setup` help topic is now redirected to this
document - all setup actions live on the `config` tool.

## Actions

Active actions: `status`, `sync`, `set`, `warmup`, `setup_sync`,
`setup_status`, `setup_start`, `setup_skip`, `setup_reset`,
`setup_complete`, `setup_relay`, `sync_now`, `export_passport`,
`import_passport`.

> Phase 2 actions (`sync_now`, `export_passport`, `import_passport`)
> require `SYNC_PASSPHRASE` to be set in the process environment (stdio
> mode) or supplied via the relay form passphrase field (HTTP mode). The
> raw passphrase is held in process memory only; only the
> Argon2id-derived hash lands in `config.enc`.

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

### `setup_status` - Inspect credential / setup state

Returns the current credential state machine snapshot (one of
`awaiting_setup`, `setup_in_progress`, `configured`, `skipped`) plus a
human-readable message. Used by clients to decide whether to surface the
relay setup form or proceed directly to memory operations.

**Parameters:** None

**Example:**
```json
{"action": "setup_status"}
```

### `setup_start` - Begin or restart the relay setup flow

Transitions the server into `setup_in_progress` state and (when running in
HTTP mode) emits the relay form URL the user should open. Pass
`key="force"` to forcibly re-issue a relay session even if credentials are
already configured.

**Parameters:**
- `key` (optional): `"force"` to bypass the configured-state guard.

**Example:**
```json
{"action": "setup_start"}
```

### `setup_skip` - Defer setup until later

Marks the credential state as `skipped` so subsequent tool calls do not
re-prompt for setup in the current session. Memory operations remain
available in FTS5-only mode (no embedding/rerank/LLM features).

**Parameters:** None

### `setup_reset` - Clear stored credentials

Wipes the relay-issued credentials from local secure storage and resets
the credential state to `awaiting_setup`. The next tool call will offer
setup again.

**Parameters:** None

### `setup_complete` - Refresh credential state after relay submission

Called by the relay flow (or invoked manually) to re-resolve the
credential state, set up provider clients, and re-initialize the embedding
backend if needed. Returns the updated `state` value.

**Parameters:** None (uses request `ctx`)

### `setup_relay` - Backward-compatible alias for `setup_start`

Equivalent to `setup_start(key="force")`. Kept for older clients.

**Parameters:** None

### `sync_now` - Push delta passport to a backend (Phase 2)

Triggers an explicit sync cycle against one configured backend. Picks
delta-push (common case) or full-pull-push (sequence gap) automatically.

**Parameters:**
- `key` (optional): backend name (`"s3"` or `"gdrive"`). Defaults to the
  first entry of `SYNC_BACKEND` env (default `"gdrive"`).

**Returns:**
- `backend`: backend name used.
- `mode`: `"delta"` or `"full-pull-push"`.
- `cursor`: new monotonic upload cursor.
- `rows` or `merge`: row count for delta, or merge counts
  (`{inserted, updated, skipped, row_count}`) for full-pull-push.

**Example:**
```json
{"action": "sync_now", "key": "s3"}
```

### `export_passport` - Write encrypted passport to disk (Phase 2)

Builds a full passport bundle and writes it to
`<data_dir>/passport-<unix-ts>.mnemo`. Useful for offline backup or
manual transfer to another machine.

**Parameters:** None (uses `SYNC_PASSPHRASE`)

**Returns:**
- `status`: `"exported"`.
- `path`: absolute path to the `.mnemo` file.
- `size`: bundle size in bytes.

**Example:**
```json
{"action": "export_passport"}
```

### `import_passport` - Pull + apply remote passport (Phase 2)

Pulls the latest passport bundle from the named backend, decrypts with
`SYNC_PASSPHRASE`, and applies each row via last-write-wins per row.
Local rows newer than the bundle row are preserved + an audit row is
written to `sync_overrides`.

**Parameters:**
- `key` (optional): backend name (`"s3"` or `"gdrive"`). Defaults to the
  first entry of `SYNC_BACKEND` env.

**Returns:**
- `status`: `"imported"` or `"no_passport"`.
- `backend`: backend name used.
- `inserted` / `updated` / `skipped` / `row_count`: per-row LWW counts.
- `manifest`: decoded bundle manifest.

**Example:**
```json
{"action": "import_passport", "key": "s3"}
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
| `COMPRESSION_ENABLED` | `true` | Phase 2: enable LLM compression on capture |
| `COMPRESSION_PROVIDER` | (auto) | Phase 2: explicit provider override (gemini/openai/anthropic/xai) |
| `COMPRESSION_MODEL` | (auto) | Phase 2: explicit model override |
| `SYNC_BACKEND` | `gdrive` | Phase 2: comma-separated backends (e.g. `s3,gdrive`) |
| `SYNC_S3_BUCKET` | (none) | Phase 2: S3 bucket name (required for s3 backend) |
| `SYNC_S3_REGION` | `us-east-1` | Phase 2: S3 region (use `auto` for R2) |
| `SYNC_S3_ENDPOINT` | (none) | Phase 2: custom endpoint URL for R2 / B2 / MinIO |
| `SYNC_S3_ACCESS_KEY_ID` | (none) | Phase 2: S3 access key |
| `SYNC_S3_SECRET_ACCESS_KEY` | (none) | Phase 2: S3 secret key |
| `SYNC_S3_PREFIX` | `passport/` | Phase 2: object key prefix |
| `SYNC_PASSPHRASE` | (none) | Phase 2: raw passphrase for AES-256-GCM (in-process only) |

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
