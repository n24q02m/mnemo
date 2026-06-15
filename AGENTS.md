# AGENTS.md - mnemo-mcp

MCP Server cho AI memory. Python 3.13, uv, hatchling, src layout.
Hybrid search: FTS5 + sqlite-vec semantic. 15 tools: 11 specialized memory tools (add_memory, search_memory, list_memories, update_memory, delete_memory, export_memories, import_memories, memory_stats, restore_memory, archived_memories, consolidate_memories) + legacy `memory` dispatcher + config + help + config__open_relay.
2-mode embedding: cloud chain (`EMBEDDING_MODELS`) > Local (Qwen3 ONNX khi chain rong). Per-task model chains (`EMBEDDING_MODELS`/`RERANK_MODELS`/`LLM_MODELS`, order = litellm fallback). LLM/Embed/Rerank: litellm passthrough qua `mcp_core.llm` (mcp-core[llm]).

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
  relay_setup.py   # Legacy ECDH relay client (ensure_config); no live caller -- HTTP setup uses the OAuth-AS browser form at <PUBLIC_URL>/authorize
  relay_schema.py  # Relay form schema (local + cloud modes)
  sync/            # Sync backends: gdrive.py (OAuth Device Code, httpx) + s3.py (R2/B2/MinIO) + delta/bundle/base
  token_store.py   # OAuth token storage (secure file-based, chmod 600)
  docs/            # Tool documentation markdown
tests/             # 1:1 mapping voi source modules
```

## Env vars

Khong co prefix (khac voi cac project khac):
- `DB_PATH` -- default `~/.mnemo-mcp/memories.db`
- `EMBEDDING_MODELS` -- chain embedding, CSV `provider/model,provider/model`; order = litellm fallback. Rong = local ONNX (qwen3-embed).
- `RERANK_MODELS` -- chain rerank, CSV `provider/model,...`; order = fallback. Rong = local ONNX cross-encoder.
- `LLM_MODELS` -- chain LLM (graph extraction), CSV `provider/model,...`; order = fallback. Rong = tat feature LLM.
- Provider duoc suy ra tu prefix model. API key theo convention litellm `<PROVIDER>_API_KEY`. 6 provider servers goi y:

  | model prefix | key env var | get it at |
  |---|---|---|
  | `gemini/` | `GEMINI_API_KEY` | aistudio.google.com/apikey |
  | `openai/` (or bare) | `OPENAI_API_KEY` | platform.openai.com |
  | `jina_ai/` | `JINA_AI_API_KEY` | jina.ai/api-key |
  | `cohere/` | `COHERE_API_KEY` | dashboard.cohere.com |
  | `xai/` | `XAI_API_KEY` | console.x.ai |
  | `anthropic/` | `ANTHROPIC_API_KEY` | console.anthropic.com |

  For any other litellm provider (used via env passthrough), see https://docs.litellm.ai/docs/providers/<provider> for its `<PROVIDER>_API_KEY` name.
- Custom endpoint (SSRF-guarded): `LLM_API_BASE`, `EMBEDDING_API_BASE`, `RERANK_API_BASE`
- `EMBEDDING_DIMS` -- default 768 (0 = auto)
- Deprecated (honored mot release voi warning): singular `EMBEDDING_MODEL`/`RERANK_MODEL` + `EMBEDDING_BACKEND`/`RERANK_BACKEND` (backend gio suy ra tu chain rong hay khong). Router auto-detect cu "Jina > Gemini > OpenAI > Cohere" da bo.
- `SYNC_ENABLED` -- `true`/`false`, default true
- `GOOGLE_DRIVE_CLIENT_ID` -- OAuth client ID (required for sync)
- `SYNC_FOLDER` -- Google Drive folder name (default: `mnemo-mcp`)
- `SYNC_INTERVAL` -- seconds (0 = manual only, default: 300)
- `RERANK_ENABLED` -- `true`/`false`, default true
- `RERANK_TOP_N` -- so ket qua rerank giu lai (default: 10)
- `ARCHIVE_ENABLED` -- `true`/`false`, default true
- `ARCHIVE_AFTER_DAYS` -- so ngay truoc khi archive (default: 90)
- `ARCHIVE_IMPORTANCE_THRESHOLD` -- nguong importance de giu lai (default: 0.3)
- `DEDUP_THRESHOLD` -- nguong similarity de coi la duplicate (default: 0.9)
- `DEDUP_WARN_THRESHOLD` -- nguong similarity de canh bao (default: 0.7)
- `RECENCY_HALF_LIFE_DAYS` -- half-life cho temporal decay scoring (default: 7)
- `LOG_LEVEL` -- log level (default: INFO)

### Manual config example

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx", "args": ["mnemo-mcp"],
      "env": {
        "EMBEDDING_MODELS": "jina_ai/jina-embeddings-v5-text-small,gemini/gemini-embedding-001",
        "RERANK_MODELS": "jina_ai/jina-reranker-v3",
        "LLM_MODELS": "gemini/gemini-3-flash-preview",
        "JINA_AI_API_KEY": "jina_xxx",
        "GEMINI_API_KEY": "AIza_xxx"
      }
    }
  }
}
```

## Embedding architecture

1. **Cloud** (`EMBEDDING_MODELS` chain) -- thu lan luot theo thu tu, fallback qua litellm.
2. **Local** -- Qwen3-Embedding-0.6B ONNX, dung khi chain rong, zero config, luon available
- Tat ca embeddings luu tai 768 dims. Doi embedding MODEL = doi vector space -> B2 identity guard chan boot (set REINDEX_ON_MODEL_CHANGE=true de re-embed). 768-dim chung chi giu table khong vo; KHONG cho mix vector 2 model khac nhau (cung dims van rac search).

## CD Pipeline

PSR v10 (workflow_dispatch) -> PyPI + Docker (amd64+arm64) + GHCR + MCP Registry.

## Luu y

- Tools tra ve `_json({"error": "..."})`, khong raise exception.
- `match action:` pattern cho routing.
- `asyncio.to_thread()` cho blocking I/O (SQLite, embedding).
- Sync: Google Drive API (httpx), JSONL-based merge. OAuth Device Code flow, token luu tai `~/.mnemo-mcp/tokens/google_drive.json` (600).
- Local embedding: first run download ~570MB model, cached.
- Dependencies: `qwen3-embed`, `sqlite-vec`, `n24q02m-mcp-core[llm]` (litellm). Native SDK (google-genai/openai/cohere/anthropic) da go -- moi LLM/embed/rerank qua litellm passthrough.
- Pre-commit: ruff lint + format, ty check, pytest.
- Secrets: skret SSM namespace `/mnemo-mcp/prod` (region `ap-southeast-1`)

## E2E

Driven by `mcp-core/scripts/e2e/` (matrix-locked, 15 configs). Run a single config from this repo via `make e2e` (proxy) or directly:

```
cd ../mcp-core && uv run --project scripts/e2e python -m e2e.driver <config-id>
```

Configs for this repo: `mnemo-full`.

t2-interaction: GDrive device-code (900s); per-sub token storage at ``~/.mnemo-mcp/subs/<sub>/tokens/google_drive.json``.

Tier policy:

- **T0** (precommit + CI on PR / main push) - runs without upstream identity. Skret keys not required.
- **T2 non-interaction** (`make e2e-config CONFIG=<id>` locally) - driver pre-fills relay form from skret AWS SSM `/mnemo-mcp/prod` (`ap-southeast-1`). No user gate.
- **T2 interaction** - driver fills relay form, then prints upstream user-gate URL; user signs in / types OTP at provider. Driver enforces per-flow timeouts (device-code 900s, oauth-redirect 300s, browser-form 600s) and emits `[poll] elapsed=Xs remaining=Ys status=<body>` every 30s. On timeout, container logs + last `setup-status` are saved to `<tmp>/e2e-diag/` BEFORE teardown for post-mortem.

Multi-user remote mode (deployment property; not a separate config) requires `MCP_DCR_SERVER_SECRET` in the same skret namespace - driver refuses to start the container without it when `PUBLIC_URL` is set.

References: `mcp-core/scripts/e2e/matrix.yaml`, `~/.claude/skills/mcp-dev/references/e2e-full-matrix.md` (harness-readiness gate), `~/.claude/skills/mcp-dev/references/secrets-skret.md` (per-server credential layout), `~/.claude/skills/mcp-dev/references/multi-user-pattern.md` (per-JWT-sub isolation).
