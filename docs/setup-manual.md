# Mnemo MCP -- Manual Setup Guide

> **2026-05-02 Update (v<auto>+)**: Plugin install (Method 1) now uses pure stdio mode with local SQLite storage. No required env vars -- mnemo works out-of-box.
> The previous "Zero-Config Relay" auto-spawn pattern has been removed.
> Optional cloud providers (Jina/Gemini/OpenAI/Cohere) and Google Drive sync are still supported -- set them via env vars (Method 1) or configure them through the relay form in HTTP mode (Method 3 self-host).

## Method overview

This plugin supports 3 install methods. Pick the one that matches your use case:

| Priority | Method | Transport | Best for |
|---|---|---|---|
| **1. Default** | Plugin install (`uvx`/`npx`) | stdio | Quick local start, single workstation, no OAuth/HTTP needed. |
| **2. Fallback** | Docker stdio (`docker run -i --rm`) | stdio | Windows/macOS where native uvx/npx hits PATH or Python version issues. |
| **3. Recommended** | Docker HTTP (`docker run -p 8080:8080`) | HTTP | Multi-device, OAuth/relay-form auth, team self-host, claude.ai web compatibility. |

All MCP servers across this stack share this priority hierarchy. Note: 2 plugins (`better-godot-mcp` and `better-code-review-graph`) only support Method 1 (stdio) -- they need direct host access to project files / repo paths and don't ship Docker / HTTP variants.

> **⚠️ Mutually exclusive — pick ONE per plugin**: If you choose Method 2 (Docker stdio override) OR Method 3 (HTTP), do NOT also `/plugin install` this plugin via marketplace. Both load simultaneously and create duplicate entries in `/mcp` dialog (plugin's stdio + your override). Plugin matching is by **endpoint** (URL or command string) per CC docs, not by name — and `npx`/`uvx` ≠ `docker` ≠ HTTP URL, so all three are distinct endpoints. Trade-off: choosing Method 2 or Method 3 means you lose this plugin's skills/agents/hooks/commands. For full plugin features, use Method 1 (default plugin install) with `userConfig` credentials prompted at install time.

## Prerequisites

- **Python 3.13** (3.14+ is NOT supported)
- `uv` or `uvx` installed ([docs](https://docs.astral.sh/uv/getting-started/installation/))
- Docker (optional, for containerized setup)

## Method 1: Claude Code Plugin (Recommended)

Plugin marketplace install runs the server in **pure stdio mode**. mnemo works with **zero required env vars** -- it falls back to local SQLite + local Qwen3 ONNX embedding. Cloud providers and GDrive sync are optional.

### Credential prompts at install

When you run `/plugin install`, Claude Code prompts you for the following credentials (declared in `userConfig` per CC docs). Sensitive values are stored in your system keychain and persist across `/plugin update`:

| Field | Required | Where to obtain |
|---|---|---|
| `JINA_AI_API_KEY` | Optional | https://jina.ai/api-key |
| `GEMINI_API_KEY` | Optional | https://aistudio.google.com/apikey |
| `OPENAI_API_KEY` | Optional | https://platform.openai.com/api-keys |
| `COHERE_API_KEY` | Optional | https://dashboard.cohere.com/api-keys |

### Steps

1. Open Claude Code in your terminal.
2. Install the plugin (Claude Code prompts for `JINA_AI_API_KEY` -- press Enter to skip):
   ```bash
   /plugin marketplace add n24q02m/claude-plugins
   /plugin install mnemo-mcp@n24q02m-plugins
   ```
3. Restart Claude Code.

> **Note**: This installs the full plugin (skills + agents + hooks + commands + stdio MCP server). If you'd rather use Method 2 (Docker stdio) or Method 3 (HTTP) below, DO NOT `/plugin install` this plugin — pick Method 2 or Method 3 instead. All three methods are mutually exclusive (see Method overview).

## Method 2: Docker stdio (fallback)

> **⚠️ Before adding the Docker stdio override below, ensure this plugin is NOT installed via marketplace**: Run `/plugin uninstall mnemo-mcp@n24q02m-plugins` first if you previously ran `/plugin install`. Otherwise both entries (plugin's `npx`/`uvx` stdio + your `docker run` stdio) will load simultaneously since plugin matches by endpoint (command string), not by name.
>
> **Trade-off accepted**: Choosing this method means you lose this plugin's skills/agents/hooks/commands. Use Method 1 instead if you want full plugin features.

1. Pull the image:
   ```bash
   docker pull n24q02m/mnemo-mcp:latest
   ```

2. Run with optional environment variables:
   ```bash
   docker run -i --rm \
     --name mcp-mnemo \
     -v mnemo-data:/data \
     -e JINA_AI_API_KEY=your_key_here \
     -e GEMINI_API_KEY=your_key_here \
     n24q02m/mnemo-mcp:latest
   ```

3. Or add to your MCP client config:
   ```json
   {
     "mcpServers": {
       "mnemo": {
         "command": "docker",
         "args": [
           "run", "-i", "--rm",
           "--name", "mcp-mnemo",
           "-v", "mnemo-data:/data",
           "-e", "JINA_AI_API_KEY",
           "-e", "GEMINI_API_KEY",
           "n24q02m/mnemo-mcp:latest"
         ]
       }
     }
   }
   ```

## Why upgrade to HTTP mode?

Stdio is the default and works fine for single-user local setups. You may want to switch to HTTP mode (Method 3 self-host) when you need any of the following:

- **claude.ai web compatibility** -- claude.ai (the web UI) supports HTTP MCP servers but cannot spawn local stdio processes.
- **One server shared across N Claude Code sessions** -- a single HTTP instance serves multiple terminals/IDEs without re-spawning per session, sharing the same memory database.
- **Browser-based GDrive OAuth** -- enable Google Drive sync without manually exchanging an OAuth token in the env (the relay form completes the OAuth flow in your browser).
- **Multi-device credential sync** -- configure cloud API keys / GDrive once, the server uses them for any device/session that connects.
- **Multi-user team sharing** -- a self-hosted server can serve multiple memory databases, each isolated per JWT-sub.
- **Always-on persistent process for webhooks/agents** -- HTTP servers stay alive between sessions, enabling background sync, scheduled archive runs, or background memory consolidation.

## Method 3: Docker HTTP (recommended)

> **⚠️ Before adding the HTTP override below, ensure this plugin is NOT installed via marketplace**: Run `/plugin uninstall mnemo-mcp@n24q02m-plugins` first if you previously ran `/plugin install`. Otherwise both entries (plugin's stdio + your HTTP override) will load simultaneously since plugin matches by endpoint, not name.
>
> **Trade-off accepted**: Choosing this method means you lose this plugin's skills/agents/hooks/commands. For example, the `mnemo-mcp:knowledge-audit` skill will no longer be available. Use Method 1 instead if you want full plugin features.

> **Switching transport vs. setting credentials**: The `userConfig` prompt only configures credentials for stdio mode (Method 1 / Option 1). To switch transport to HTTP, override `mcpServers` in your client settings per the snippets below -- this is a separate path from `userConfig` and is not driven by the install prompt.

### 3.2. Self-host with docker-compose

Host your own multi-user mnemo server. Always-multi-user (per-JWT-sub credential isolation) -- a single multi-user mode, no `MCP_MODE` selector. Google Drive OAuth uses a **bundled Desktop OAuth public client** (same pattern as `wet-mcp`); no separate Google Cloud Console registration is required.

### Required Env

| Variable | Description |
|:---------|:------------|
| `TRANSPORT_MODE=http` | Selects HTTP transport. |
| `PUBLIC_URL` | Public URL of your server (e.g. `https://your-domain.com`). Used for OAuth redirects and the `/authorize` setup page. |
| `DCR_SERVER_SECRET` | HMAC secret for stateless Dynamic Client Registration. Generate via `openssl rand -hex 32`. |
| `PORT` | (optional, default `8080`) Server port. |

### Optional Env (per-deployment defaults)

| Variable | Description |
|:---------|:------------|
| `JINA_AI_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `COHERE_API_KEY` | Default cloud API keys for the deployment (per-user values can override via the relay form). |
| `SYNC_ENABLED=true` | Enable Google Drive sync UI in the relay form. |

### Edge auth: relay password

Public HTTP deployments expose `<your-domain>/authorize` to URL discovery. To prevent random Internet users from accessing the relay form, mint a relay password:

```bash
openssl rand -hex 32
# Save in your skret / .env as:
MCP_RELAY_PASSWORD=<generated-32-byte-hex>
```

Share this password out-of-band (Signal/email/SMS) with anyone you invite to use your server. They will see a login form when first opening `/authorize`; once logged in, the cookie persists 24 hours.

**Single-user dev exception**: If `PUBLIC_URL=http://localhost:8080`, you can leave `MCP_RELAY_PASSWORD` empty to disable the gate. The server logs a warning if you skip the password with a non-localhost `PUBLIC_URL`.

### Run the Server

```bash
docker run -p 8080:8080 \
  -e TRANSPORT_MODE=http \
  -e PUBLIC_URL=https://your-domain.com \
  -e DCR_SERVER_SECRET=$(openssl rand -hex 32) \
  -v mnemo-data:/data \
  n24q02m/mnemo-mcp:latest
```

Point clients to your server:
```json
{
  "mcpServers": {
    "mnemo": {
      "type": "http",
      "url": "https://your-domain.com/mcp"
    }
  }
}
```

### Browser Setup Flow

1. On first tool call from a new client, the server returns a setup URL: `https://your-domain.com/authorize?session=<sid>`.
2. Open the URL in a browser.
3. Fill the relay form:
   - Optional cloud API keys (Jina / Gemini / OpenAI / Cohere)
   - Optional **Google Drive sync** -- click "Connect Google Drive", complete OAuth in browser, the token is stored encrypted per-user.
4. Submit. Credentials are encrypted and stored per JWT-sub at `~/.mnemo-mcp/subs/<sub>/`.
5. Retry the tool call -- it now succeeds with your config.

## Credential Setup

### Option A: Environment Variables (Stdio Mode)

Set API keys in your shell profile or MCP client settings:

```bash
export JINA_AI_API_KEY="jina_..."
export GEMINI_API_KEY="AIza..."
```

### Option B: Relay Form (HTTP Mode)

Use HTTP mode (Method 3 self-host) and complete the form in the browser. No env vars needed beyond the HTTP server's required env (`TRANSPORT_MODE`, `PUBLIC_URL`, `DCR_SERVER_SECRET`).

### Sync Setup (Optional)

To sync memories across machines:

- **Stdio mode**: Set `SYNC_ENABLED=true` and provide a Google Drive OAuth token at `~/.mnemo-mcp/tokens/google_drive.json` (chmod 600). Manual token creation required.
- **HTTP mode**: Set `SYNC_ENABLED=true` on the server, use the relay form's "Connect Google Drive" button -- the bundled Desktop OAuth client completes the flow in your browser.

For other rclone providers (Dropbox, S3), set `SYNC_PROVIDER=dropbox` etc. in env vars.

## Environment Variable Reference

All environment variables are **optional** -- mnemo works with zero env vars in stdio mode (local SQLite + local Qwen3 ONNX). See [docs/setup-with-agent.md](setup-with-agent.md#environment-variables) for the complete table.

### Key Variables

| Variable | Default | Description |
|:---------|:--------|:------------|
| `JINA_AI_API_KEY` | -- | Jina AI: embedding + reranking (highest priority) |
| `GEMINI_API_KEY` | -- | Gemini: LLM + embedding (free tier) |
| `OPENAI_API_KEY` | -- | OpenAI: LLM + embedding |
| `COHERE_API_KEY` | -- | Cohere: embedding + reranking |
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | Database location |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `LOG_LEVEL` | `INFO` | Logging level |

### Provider Priority

- **Embedding**: Jina AI > Gemini > OpenAI > Cohere > Local ONNX (Qwen3)
- **Reranking**: Jina AI > Cohere > Local ONNX (Qwen3)
- **LLM**: Gemini > OpenAI > Disabled (heuristic fallback)

## Troubleshooting

### First run takes a long time

On first start, the server downloads the ONNX embedding model (~570MB). Use the warmup command to pre-download:

```
config(action="warmup")
```

### Database locked errors

If you see SQLite database locked errors, ensure only one instance of mnemo-mcp is running. Check for orphaned processes:

```bash
# Linux/macOS
ps aux | grep mnemo-mcp

# Windows
tasklist | findstr mnemo
```

### Sync conflicts

Sync uses JSONL-based merge strategy. If conflicts occur, the most recent version wins. You can export/import memories manually:

```
memory(action="export")
memory(action="import", file_path="/path/to/memories.jsonl")
```

### Embedding model download fails

If ONNX model download fails behind a proxy, use cloud embedding instead by setting any API key (e.g., `GEMINI_API_KEY`).
