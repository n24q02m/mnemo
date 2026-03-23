# Setup Tool - Full Documentation

## Overview

The `setup` tool handles server setup tasks: pre-downloading models and authenticating sync providers.
These actions prepare the server for optimal performance and avoid first-run delays.

## Actions

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

### `setup_sync` - Authenticate sync provider

Downloads rclone and opens a browser for OAuth authentication. Saves the token
locally so no env vars are needed for sync.

**Parameters:**
- `provider` (optional): rclone provider type (default: "drive"). Options: drive, dropbox, s3, onedrive, b2, sftp

**Returns:**
- `status`: "authenticated" or "error"
- `provider`: Provider name
- `remote_name`: rclone remote name
- `token_path`: Path to saved token file
- `next_steps`: Env vars to set in MCP config

**Workflow:**
1. Downloads rclone if not available
2. Runs `rclone authorize` which opens a browser for OAuth
3. Saves the token to `~/.mnemo-mcp/tokens/<provider>.json`
4. Returns env vars to set in your MCP config

**Example:**
```json
{"action": "setup_sync", "provider": "drive"}
```

## CLI Equivalents

These MCP tool actions replace the former CLI subcommands:

| CLI (removed) | MCP Tool |
|:--------------|:---------|
| `uvx mnemo-mcp warmup` | `setup(action="warmup")` |
| `uvx mnemo-mcp setup-sync drive` | `setup(action="setup_sync", provider="drive")` |
