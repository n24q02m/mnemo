# CLAUDE.md - mnemo-mcp

MCP Server cho AI memory. Python 3.13, uv, hatchling, src layout.
Hybrid search: FTS5 + sqlite-vec semantic. 3 tools: memory, config, help.
2-mode embedding: Cloud (Jina > Gemini > OpenAI > Cohere) > Local (Qwen3 ONNX). LLM: google-genai + openai.

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
uv run mnemo-mcp                    # run server (warmup/setup_sync via config tool)

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
- Default: `-m 'not integration and not live and not full'`
- Snapshot testing: syrupy

## Cau truc thu muc

```
src/mnemo_mcp/
  __main__.py      # python -m mnemo_mcp entrypoint
  config.py        # Pydantic Settings (singleton), env vars khong co prefix
  server.py        # FastMCP server, tools, resources, prompts
  setup_tool.py    # Warmup + setup-sync logic (config tool actions)
  db.py            # SQLite: CRUD, FTS5, vector search (sqlite-vec)
  embedder.py      # Dual-backend: multi-provider cloud (Jina/Gemini/OpenAI/Cohere) + qwen3-embed local
  reranker.py      # Dual-backend reranking: cloud (Jina/Cohere) + local (qwen3-embed cross-encoder)
  graph.py         # Knowledge graph: entity/relation extraction via LLM
  relay_setup.py   # Zero-config relay: create session, poll for config
  relay_schema.py  # Relay form schema (local + cloud modes)
  sync.py          # Google Drive sync (OAuth Device Code, httpx)
  token_store.py   # OAuth token storage (secure file-based, chmod 600)
  docs/            # Tool documentation markdown
tests/             # 1:1 mapping voi source modules
```

## Env vars

Khong co prefix (khac voi cac project khac):
- `DB_PATH` -- default `~/.mnemo-mcp/memories.db`
- `JINA_AI_API_KEY` -- Jina AI API key (embedding + reranking, highest priority)
- `GEMINI_API_KEY` -- Google Gemini API key (embedding + LLM)
- `OPENAI_API_KEY` -- OpenAI API key (embedding)
- `COHERE_API_KEY` -- Cohere API key (embedding + reranking)
- `XAI_API_KEY` -- xAI/Grok API key (LLM)
- `EMBEDDING_BACKEND` -- `cloud` hoac `local` (auto-detect)
- `EMBEDDING_MODEL` -- Cloud embedding model name
- `EMBEDDING_DIMS` -- default 768 (0 = auto)
- `SYNC_ENABLED` -- `true`/`false`, default false
- `GOOGLE_DRIVE_CLIENT_ID` -- OAuth client ID (required for sync)
- `SYNC_FOLDER` -- Google Drive folder name (default: `mnemo-mcp`)
- `SYNC_INTERVAL` -- seconds (0 = manual only, default: 300)
- `RERANK_ENABLED` -- `true`/`false`, default true
- `RERANK_BACKEND` -- `cloud`, `local`, hoac auto-detect
- `RERANK_MODEL` -- Cloud rerank model name (auto-detected: Jina > Cohere)
- `RERANK_TOP_N` -- so ket qua rerank giu lai (default: 10)
- `ARCHIVE_ENABLED` -- `true`/`false`, default true
- `ARCHIVE_AFTER_DAYS` -- so ngay truoc khi archive (default: 90)
- `ARCHIVE_IMPORTANCE_THRESHOLD` -- nguong importance de giu lai (default: 0.3)
- `DEDUP_THRESHOLD` -- nguong similarity de coi la duplicate (default: 0.9)
- `DEDUP_WARN_THRESHOLD` -- nguong similarity de canh bao (default: 0.7)
- `RECENCY_HALF_LIFE_DAYS` -- half-life cho temporal decay scoring (default: 7)
- `LLM_MODELS` -- danh sach LLM models, format `provider/model,...` (default: gemini + openai)
- `LOG_LEVEL` -- log level (default: INFO)

## Embedding architecture

1. **Cloud** (API_KEYS) -- Jina > Gemini > OpenAI > Cohere
2. **Local** -- Qwen3-Embedding-0.6B ONNX, zero config, luon available
- Tat ca embeddings luu tai 768 dims. Doi provider khong break vector table.

## CD Pipeline

PSR v10 (workflow_dispatch) -> PyPI + Docker (amd64+arm64) + GHCR + MCP Registry.

## Luu y

- Tools tra ve `_json({"error": "..."})`, khong raise exception.
- `match action:` pattern cho routing.
- `asyncio.to_thread()` cho blocking I/O (SQLite, embedding).
- Sync: Google Drive API (httpx), JSONL-based merge. OAuth Device Code flow, token luu tai `~/.mnemo-mcp/tokens/google_drive.json` (600).
- Local embedding: first run download ~570MB model, cached.
- Dependencies: `qwen3-embed>=1.5.1`, `cohere`, `sqlite-vec`.
- Pre-commit: ruff lint + format, ty check, pytest.
- Infisical project: `65a85ae6-61e2-4188-9266-00dca21b9c00`
