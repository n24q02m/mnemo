# Config Tool - Full Documentation

> Rewritten 2026-10-05 for the post-de-host architecture (v2.19+). The old
> document described removed features (Google Drive / S3 passport sync,
> Cloudflare D1 deployment, relay credential setup, `API_KEYS`
> multi-provider format, `COMPRESSION_PROVIDER` overrides). Those are gone
> from the code; this page documents what exists.

## Overview

The `config` tool shows server status, updates a few runtime settings, and
pre-downloads the local embedding model.

## Actions

Active actions: `status`, `set`, `warmup`.

### `status` - Show current configuration

Returns database stats, the resolved embedding identity, and dimensions.

**Parameters:** None

**Returns:**
- `path`: the SQLite store backing the server (default `~/.mnemo/memories.db`)
- `total_memories`: total memory count
- `categories`: memory count by category
- `embedding`: the resolved model identity, storage dimensions, and
  availability (`null` model = FTS-only mode)

### `set` - Update a configuration value

Change runtime settings. Changes persist for the current session.

**Parameters:**
- `key` (required): setting name
- `value` (required): new value

**Example:**
```json
{"action": "set", "key": "log_level", "value": "DEBUG"}
```

### `warmup` - Pre-download the local embedding model

Downloads the local ONNX embedding model (~570 MB, via fastretrieval) so
the first real request does not time out. When the `[models.embed]`
provider cell carries an `api_key`, cloud embedding is used and no local
download is needed.

**Parameters:** None

**Example:**
```json
{"action": "warmup"}
```

## Provider configuration (hull per-task cells)

There are no provider API-key env vars and no BYOK. All cloud calls go
through hull-core per-task cells -- each an independent
`base_url` + `api_key` + `model` triple, plain OpenAI-spec HTTP:

| Cell | Used for |
|---|---|
| `[models.chat]` | compression, fact extraction, importance scoring, reflect |
| `[models.embed]` | cloud embedding (local ONNX is the default fallback) |
| `[models.rerank]` | cloud reranking (local fastretrieval reranker is the default fallback) |
| `[models.jev]` | jev-score calls |

OpenRouter is the pre-wired default (`hull config init` writes the config).
To use a different provider -- including a self-hosted Ollama/vLLM -- edit
the cell's `base_url`/`model` in the instance `config.toml`. Keys are
host-only material (instance config, or the `HULL_<TASK>_API_KEY` env
override, e.g. `HULL_EMBED_API_KEY`); end users never supply keys.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MNEMO_HOST` | localhost | HTTP bind host |
| `MNEMO_PORT` | (server default) | HTTP bind port |
| `MNEMO_DB_PATH` | `~/.mnemo/memories.db` | SQLite database path (WAL) |
| `MNEMO_AUTH_TOKEN` | (none) | Shared bearer token (auth mode 2); unset = localhost no-auth (mode 1). Multi-user mode uses `users.toml` (mode 3) |
| `DEDUP_THRESHOLD` | `0.92` | Capture dedup similarity threshold (reject-only) |
| `COMPRESSION_ENABLED` | `true` | LLM compression on capture (needs `[models.chat]` cell) |
| `ARCHIVE_TRIGGER_EVERY` | `100` | Auto-archive sweep every Nth capture |
| `TEMPORAL_ENTITY_RESOLUTION_THRESHOLD` | (code default) | Temporal entity-resolution similarity floor |
| `FASTRETRIEVAL_CACHE_PATH` | (platform cache) | Local ONNX model cache location |
| `LOG_LEVEL` | `INFO` | Server log level |

## Storage and backup

One SQLite file (WAL) under `~/.mnemo/`. There is no built-in sync;
backup/sync with `rclone` outside the server (cron or manual).

## Removed (pre-de-host, historical)

The following were removed in the 2026-09 de-host and no longer exist in
code or docs-as-behavior: Google Drive / S3 passport sync (`sync`,
`setup_sync`, `sync_now`, `export_passport`, `import_passport`,
`SYNC_*`, `GOOGLE_DRIVE_CLIENT_ID`, `SYNC_PASSPHRASE`), Cloudflare
D1/Vectorize/KV deployment (`MEMORY_DB_BACKEND=cf-d1`), relay credential
setup actions (`setup_start`/`setup_skip`/`setup_reset`/`setup_complete`/
`setup_relay`), the `API_KEYS` multi-provider format, and
`COMPRESSION_PROVIDER`/`COMPRESSION_MODEL` overrides. Backup = rclone;
providers = hull per-task cells.
