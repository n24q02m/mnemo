# Setup Tool - Full Documentation

## Overview

The `setup` tool handles server setup tasks: pre-downloading models and authenticating Google Drive sync.
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
| `uvx mnemo-mcp warmup` | `setup(action="warmup")` |
| `uvx mnemo-mcp setup-sync` | `setup(action="setup_sync")` |
