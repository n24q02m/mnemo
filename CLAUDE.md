# CLAUDE.md - mnemo-mcp

MCP Server cho AI memory. Python 3.13, uv, hatchling, src layout.
Hybrid search: FTS5 + sqlite-vec semantic. 4 tools: memory, config, setup, help.
2-mode embedding: Proxy/SDK (LiteLLM) > Local (Qwen3 ONNX).

## Commands

```bash
# Setup
uv sync --group dev

# Lint & Type check
uv run ruff check .
uv run ruff format --check .
uv run ty check

# Fix
uv run ruff check --fix .
uv run ruff format .

# Test (integration excluded by default)
uv run pytest
uv run pytest tests/test_db.py -v                          # single file
uv run pytest tests/test_db.py::TestSearch::test_basic -v  # single test

# Build & Run
uv build
uv run mnemo-mcp                    # run server (warmup/setup via MCP setup tool)

# Mise shortcuts
mise run setup     # full dev setup
mise run lint      # ruff check + format check + ty check
mise run test      # pytest
mise run fix       # ruff fix + format
```

## Pytest

- `asyncio_mode = "auto"` -- khong can `@pytest.mark.asyncio`
- Timeout: 30s/test
- Integration marker: `@pytest.mark.integration` (can network/services)
- Default: `-m 'not integration'`
- Snapshot testing: syrupy

## Cau truc thu muc

```
src/mnemo_mcp/
  config.py        # Pydantic Settings (singleton), env vars khong co prefix
  server.py        # FastMCP server, tools, resources, prompts
  setup_tool.py    # Warmup + setup-sync logic (MCP setup tool)
  db.py            # SQLite: CRUD, FTS5, vector search (sqlite-vec)
  embedder.py      # Dual-backend: LiteLLM + qwen3-embed local
  sync.py          # Rclone sync (embedded, auto-download)
  docs/            # Tool documentation markdown
tests/             # 1:1 mapping voi source modules
```

## Env vars

Khong co prefix (khac voi cac project khac):
- `DB_PATH` -- default `~/.mnemo-mcp/memories.db`
- `LITELLM_PROXY_URL` + `LITELLM_PROXY_KEY` -- proxy mode
- `API_KEYS` -- SDK mode, format `ENV:key,ENV:key` (VD: `GOOGLE_API_KEY:AIza...`)
- `EMBEDDING_BACKEND` -- `litellm` hoac `local` (auto-detect)
- `EMBEDDING_MODEL` -- LiteLLM model name
- `EMBEDDING_DIMS` -- default 768 (0 = auto)
- `SYNC_ENABLED` -- `true`/`false`, default false
- `SYNC_PROVIDER` -- rclone provider (default: `drive`)
- `SYNC_REMOTE` -- rclone remote name (default: `gdrive`)
- `SYNC_FOLDER` -- remote folder (default: `mnemo-mcp`)
- `SYNC_INTERVAL` -- seconds (0 = manual only, default: 300)

## Embedding architecture

1. **Proxy** (LITELLM_PROXY_URL) -- production, selfhosted gateway
2. **SDK** (API_KEYS) -- dev, direct API. Cloud providers: Gemini > OpenAI > Cohere
3. **Local** -- Qwen3-Embedding-0.6B ONNX, zero config, luon available
- Tat ca embeddings luu tai 768 dims. Doi provider khong break vector table.
- Khong co cross-mode fallback (proxy fail -> khong tu xuong SDK).

## CD Pipeline

PSR v10 (workflow_dispatch) -> PyPI + Docker (amd64+arm64) + GHCR + MCP Registry.

## Luu y

- Tools tra ve `_json({"error": "..."})`, khong raise exception.
- `match action:` pattern cho routing.
- `asyncio.to_thread()` cho blocking I/O (SQLite, embedding).
- Sync: rclone auto-downloaded, JSONL-based merge. OAuth token luu tai `~/.mnemo-mcp/tokens/` (600).
- Local embedding: first run download ~570MB model, cached.
- Dependencies: `qwen3-embed>=1.2.0`, `litellm`, `sqlite-vec`.
- Pre-commit: ruff lint + format, ty check, pytest.
- Infisical project: `65a85ae6-61e2-4188-9266-00dca21b9c00`
