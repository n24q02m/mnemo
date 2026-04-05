# Mnemo MCP -- Manual Setup Guide

## Prerequisites

- **Python 3.13** (3.14+ is NOT supported)
- `uv` or `uvx` installed ([docs](https://docs.astral.sh/uv/getting-started/installation/))
- Docker (optional, for containerized setup)

## Method 1: Plugin Install

For Claude Code users, the plugin approach is the simplest.

1. Open Claude Code
2. Run the following commands:
   ```bash
   /plugin marketplace add n24q02m/claude-plugins
   /plugin install mnemo-mcp@n24q02m-plugins
   ```
3. The server starts automatically when Claude Code launches
4. On first run, a relay setup URL appears -- open it to configure API keys (optional)

## Method 2: uvx Direct

1. Add to your MCP client configuration file:

   **Claude Code** (`~/.claude/settings.local.json`):
   ```json
   {
     "mcpServers": {
       "mnemo": {
         "command": "uvx",
         "args": ["--python", "3.13", "mnemo-mcp"]
       }
     }
   }
   ```

   **Codex CLI** (`~/.codex/config.toml`):
   ```toml
   [mcp_servers.mnemo]
   command = "uvx"
   args = ["--python", "3.13", "mnemo-mcp"]
   ```

   **OpenCode** (`opencode.json` in project root):
   ```json
   {
     "mcpServers": {
       "mnemo": {
         "command": "uvx",
         "args": ["--python", "3.13", "mnemo-mcp"]
       }
     }
   }
   ```

2. Restart your MCP client
3. On first run, the embedding model is downloaded (~570MB)
4. A relay setup URL appears in stderr -- open it to configure cloud API keys (optional)

## Method 3: Docker

1. Pull the image:
   ```bash
   docker pull n24q02m/mnemo-mcp:latest
   ```

2. Run with environment variables:
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

## Method 4: Build from Source

1. Clone the repository:
   ```bash
   git clone https://github.com/n24q02m/mnemo-mcp.git
   cd mnemo-mcp
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

3. Run the server:
   ```bash
   uv run mnemo-mcp
   ```

## Credential Setup

### Option A: Environment Variables (Recommended)

Set API keys in your shell profile or MCP client settings:

```bash
export JINA_AI_API_KEY="jina_..."
export GEMINI_API_KEY="AIza..."
```

When environment variables are set, the relay is skipped entirely.

### Option B: Zero-Config Relay (BETA)

> **Note**: Relay is a **BETA** credential provisioning flow. For stable production use, prefer **Option A: Environment Variables**. The relay currently blocks MCP server startup on first run and may time out in some MCP clients -- see [upcoming redesign](https://github.com/n24q02m/claude-plugins/issues).

No manual configuration needed. On first start:

1. The server prints a setup URL to stderr (e.g., `https://mnemo-mcp.n24q02m.com/setup/...`)
2. Open the URL in any browser
3. Fill in your API keys on the guided form:
   - **Jina AI API Key** -- enables embedding and reranking ([get key](https://jina.ai/api-key))
   - **Gemini API Key** -- enables LLM and embedding, free tier available ([get key](https://aistudio.google.com/apikey))
   - **OpenAI API Key** -- enables LLM and embedding ([get key](https://platform.openai.com/api-keys))
   - **Cohere API Key** -- enables embedding and reranking ([get key](https://dashboard.cohere.com/api-keys))
4. All fields are optional -- leave empty for pure local mode
5. Credentials are encrypted and stored at `~/.config/mcp/config.enc`

### Sync Setup (Optional)

To sync memories across machines:

1. Set environment variables:
   ```bash
   export SYNC_ENABLED=true
   ```

2. On first sync, rclone is auto-downloaded and a browser opens for OAuth
3. For non-Google Drive providers:
   ```bash
   export SYNC_PROVIDER=dropbox
   export SYNC_REMOTE=dropbox
   ```

4. Or use the MCP tool: `config(action="setup_sync")`

## Environment Variable Reference

All environment variables are **optional**. See [docs/setup-with-agent.md](setup-with-agent.md#environment-variables) for the complete table.

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

### Relay setup URL does not appear

The relay URL only appears when no API keys are set in environment. If you have any of `JINA_AI_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `COHERE_API_KEY` set, the relay is skipped.

To force relay setup, use the MCP tool: `config(action="setup_relay")`

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
