# Mnemo MCP Server

mcp-name: io.github.n24q02m/mnemo-mcp

**Persistent AI memory with hybrid search and embedded sync. Open, free, unlimited.**

<!-- Badge Row 1: Status -->
[![CI](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/n24q02m/mnemo-mcp/graph/badge.svg?token=GELGVQNMUZ)](https://codecov.io/gh/n24q02m/mnemo-mcp)
[![PyPI](https://img.shields.io/pypi/v/mnemo-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/mnemo-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/mnemo-mcp?label=docker&logo=docker&logoColor=white&sort=semver)](https://hub.docker.com/r/n24q02m/mnemo-mcp)
[![License: MIT](https://img.shields.io/github/license/n24q02m/mnemo-mcp)](LICENSE)
[![SafeSkill 91/100](https://img.shields.io/badge/SafeSkill-91%2F100_Verified%20Safe-brightgreen)](https://safeskill.dev/scan/n24q02m-mnemo-mcp)

<!-- Badge Row 2: Tech -->
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](#)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](#)
[![MCP](https://img.shields.io/badge/MCP-000000?logo=anthropic&logoColor=white)](#)
[![semantic-release](https://img.shields.io/badge/semantic--release-e10079?logo=semantic-release&logoColor=white)](https://github.com/python-semantic-release/python-semantic-release)
[![Renovate](https://img.shields.io/badge/renovate-enabled-1A1F6C?logo=renovatebot&logoColor=white)](https://developer.mend.io/)

<!-- BEGIN: AUTO-GENERATED-CROSS-PROMO -->
<details>
  <summary><strong>Sister projects from n24q02m</strong> (click to expand)</summary>

| Project | Tagline | Tag |
|---|---|---|
| [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph) | Knowledge graph for token-efficient code reviews -- semantic search and call-... | MCP |
| [better-email-mcp](https://github.com/n24q02m/better-email-mcp) | IMAP/SMTP email for AI agents -- read, send, organize folders, and manage att... | MCP |
| [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) | Composite MCP server for Godot Engine -- 17 composite tools for AI-assisted g... | MCP |
| [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) | Markdown-first Notion for AI agents -- pages, databases, blocks, and comments... | MCP |
| [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) | Telegram for AI agents -- messages, chats, media, and contacts across both bo... | MCP |
| [claude-plugins](https://github.com/n24q02m/claude-plugins) | Claude Code plugin marketplace for the n24q02m MCP servers -- install web sea... | Marketplace |
| [imagine-mcp](https://github.com/n24q02m/imagine-mcp) | Image and video understanding + generation for AI agents -- across Gemini, Op... | MCP |
| [jules-task-archiver](https://github.com/n24q02m/jules-task-archiver) | Chrome Extension for bulk operations on Jules tasks via batchexecute API -- a... | Tooling |
| [mcp-core](https://github.com/n24q02m/mcp-core) | Shared foundation for building MCP servers -- Streamable HTTP transport, OAut... | MCP |
| [mnemo-mcp](https://github.com/n24q02m/mnemo-mcp) | Persistent AI memory with hybrid search and embedded sync. Open, free, unlimi... | MCP |
| [qwen3-embed](https://github.com/n24q02m/qwen3-embed) | Lightweight Qwen3 text embedding and reranking via ONNX Runtime and GGUF | Library |
| [skret](https://github.com/n24q02m/skret) | Secrets without the server. | CLI |
| [tacet](https://github.com/n24q02m/tacet) | TACET: a self-distilling neuro-symbolic cascade that amortises LLM cost in kn... | Tooling |
| [web-core](https://github.com/n24q02m/web-core) | Shared web infrastructure package for search, scraping, HTTP security, and st... | Library |
| [wet-mcp](https://github.com/n24q02m/wet-mcp) | Open-source MCP server for AI agents: web search, content extraction, and lib... | MCP |

</details>
<!-- END: AUTO-GENERATED-CROSS-PROMO -->

## Table of contents

- [Roadmap](#roadmap)
- [Features](#features)
- [Quick install](#quick-install)
- [Configuration](#configuration)
- [Comparison vs. peers](#comparison-vs-peers)
- [Status](#status)
- [Documentation](#documentation)
- [Tools](#tools)
- [Security](#security)
- [Build from Source](#build-from-source)
- [Trust Model](#trust-model)
- [License](#license)



<a href="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp/badge" alt="Mnemo MCP server" />
</a>

## Roadmap

All three phases below have shipped. The temporal knowledge graph (Phase 3) is the current major line (v2.x).

| Phase | Version | Status | Highlights |
|---|---|---|---|
| **Phase 1** | v1.x | **Shipped** | Typed `memory(action="capture")` (6 context_types + dedup) -- RRF (k=60) hybrid fusion + cross-encoder rerank + temporal decay -- importance x recency archive policy + restore -- Alembic migrations -- multi-provider LLM dispatch -- plugin trinity (recall-context + memory-commit skills, SessionStart + opt-in PostToolUse hooks) |
| **Phase 2** | v1.x | **Shipped** | LLM-driven compression of older memories + Passport sync (encrypted import/export bundle for cross-machine bootstrap) -- AES-256-GCM + Argon2id, S3 / R2 / B2 / MinIO + GDrive backends, delta-sync with LWW per row |
| **Phase 3** | v2.x | **Shipped (BREAKING)** | Temporal knowledge graph -- bitemporal `valid_from` / `valid_to` columns -- entity resolution via embedding KNN -- `entity_search` / `entity_graph` / `history` actions -- KG-aware passport bundle sections -- `KG_AUTO_ENABLED` opt-in auto-extract on capture |

## Features

- **Hybrid retrieval** -- FTS5 + sqlite-vec, fused via Reciprocal Rank Fusion (k=60), then re-ranked by a configurable rerank chain (`RERANK_MODELS`, order = litellm fallback; empty -> local qwen3-reranker) with temporal decay and importance boost
- **Typed capture** -- `memory(action="capture")` with 6 context_types (`conversation`/`fact`/`preference`/`skill`/`task`/`decision`), embedding-based dedup, and a configurable LLM chain (`LLM_MODELS`, order = litellm fallback)
- **Knowledge graph** -- Automatic entity extraction and relation tracking; top results boosted by graph proximity
- **Importance scoring + archive policy** -- LLM-scored 0.0-1.0 importance; soft-archive when `recency_factor * (1 - importance) > 1.0`; restore action available
- **Auto-archive trigger** -- Background sweep every Nth capture (default 100) -- no cron required
- **STM-to-LTM consolidation** -- LLM summarization of related memories in a category
- **Duplicate detection** -- Warns before adding semantically similar memories
- **Zero config** -- Built-in local Qwen3 ONNX embedding + reranking, no API keys needed. Optional cloud providers (Jina AI, Gemini, OpenAI, Cohere)
- **Multi-machine sync** -- JSONL-based merge sync via Google Drive (bundled Desktop OAuth public client)
- **Plugin trinity** -- Ships `/recall-context` + `/memory-commit` skills and SessionStart + opt-in PostToolUse hooks (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- **Proactive memory** -- Tool descriptions and skills guide AI to save preferences, decisions, facts at the right moment
- **LLM compression** -- Per-turn compression via the multi-provider dispatcher targets ~3x token reduction at >=0.90 fact retention; graceful skip when no provider configured (see [docs/compression.md](docs/compression.md))
- **Encrypted passport sync** -- AES-256-GCM bundles + Argon2id KDF, S3 (R2 / B2 / MinIO) and Google Drive backends, delta-sync with last-write-wins per row (see [docs/passport.md](docs/passport.md)). Bootstrap via the `passport-bootstrap` skill.
- **Temporal knowledge graph** -- Bitemporal columns (`valid_from` / `valid_to` / `superseded_by`) on every memory + entity-resolution dedup (embedding KNN at default 0.85 cosine threshold) + audit trail (`memory_audit` table with prev/new state hashes) + new actions (`entity_search` / `entity_graph` / `history`) + opt-in `KG_AUTO_ENABLED` auto-extract on capture. **BREAKING** for clients that called `memory.get` expecting historical-inclusive results: pass `as_of` for time-travel; default now filters to current-state (`valid_to IS NULL`).

## Quick install

```bash
# Method 1 (default): plugin install via Claude Code
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins

# Method 1 (CLI): direct uvx invocation (zero config -- runs on the built-in local model)
claude mcp add mnemo -- uvx mnemo-mcp

# Method 3 (HTTP / multi-device / multi-user)
docker run -d --name mnemo-mcp-http -p 8085:8080 \
  -v mnemo-data:/data -e MCP_TRANSPORT=http \
  -e PUBLIC_URL=https://mnemo.example.com \
  n24q02m/mnemo-mcp:latest
```

No API keys are required: with no provider keys set, mnemo runs fully offline on the
bundled local Qwen3 ONNX embedding + reranker. Add cloud provider keys only to switch
embedding / rerank / LLM onto a hosted model (see [Configuration](#configuration)).

Full setup matrices live at the canonical docs site
[mcp.n24q02m.com/servers/mnemo-mcp/setup/](https://mcp.n24q02m.com/servers/mnemo-mcp/setup/)
and the paste-to-agent snippet at
[claude-plugins/plugins/mnemo-mcp/setup-with-agent.md](https://github.com/n24q02m/claude-plugins/blob/main/plugins/mnemo-mcp/setup-with-agent.md).

## Configuration

All settings are plain environment variables (no prefix). Everything is optional --
mnemo runs zero-config on the local model. The most common knobs:

### Model selection (per-task chains)

Embedding, reranking, and LLM features each take an ordered, comma-separated chain of
`provider/model` entries (tried in order, litellm fallback). Leave a chain empty to use
the bundled local model (embedding / rerank) or to disable the feature (LLM).

| Env var | Default | Purpose |
|---|---|---|
| `EMBEDDING_MODELS` | (empty -> local Qwen3 ONNX) | Embedding chain, e.g. `jina_ai/jina-embeddings-v5-text-small,gemini/gemini-embedding-001` |
| `RERANK_MODELS` | (empty -> local Qwen3 cross-encoder) | Rerank chain, e.g. `jina_ai/jina-reranker-v3,cohere/rerank-v3.5` |
| `LLM_MODELS` | (built-in cloud chain) | LLM chain for graph extraction / importance / compression; empty disables those features |
| `EMBEDDING_DIMS` | `768` | Embedding dimensions (`0` = auto-detect) |

Provider is inferred from the model prefix; supply each provider's key via the litellm
`<PROVIDER>_API_KEY` convention:

| model prefix | key env var | get it at |
|---|---|---|
| `jina_ai/` | `JINA_AI_API_KEY` | jina.ai/api-dashboard |
| `gemini/` | `GEMINI_API_KEY` | aistudio.google.com/apikey |
| `openai/` (or bare) | `OPENAI_API_KEY` | platform.openai.com/api-keys |
| `cohere/` | `COHERE_API_KEY` | dashboard.cohere.com/api-keys |

Any other litellm provider works via env passthrough; see
`https://docs.litellm.ai/docs/providers/<provider>` for its `<PROVIDER>_API_KEY` name.
Custom OpenAI-compatible endpoints (SSRF-guarded): `LLM_API_BASE`, `EMBEDDING_API_BASE`,
`RERANK_API_BASE`.

> Changing the embedding **model** changes the vector space. A safe-by-default guard
> blocks boot on mismatch; set `REINDEX_ON_MODEL_CHANGE=true` to re-embed.

### Storage, sync, retrieval, and archive

| Env var | Default | Purpose |
|---|---|---|
| `DB_PATH` | `~/.mnemo-mcp/memories.db` | SQLite database path (also accepts `MNEMO_DB_PATH`) |
| `SYNC_ENABLED` | `true` | Enable Google Drive multi-machine sync |
| `GOOGLE_DRIVE_CLIENT_ID` | (none) | OAuth client ID required for sync |
| `SYNC_FOLDER` | `mnemo-mcp` | Google Drive folder name |
| `SYNC_INTERVAL` | `300` | Auto-sync interval in seconds (`0` = manual only) |
| `RERANK_ENABLED` | `true` | Enable reranking of fused results |
| `RERANK_TOP_N` | `10` | Number of reranked results to keep |
| `ARCHIVE_ENABLED` | `true` | Enable importance x recency soft-archive sweeps |
| `ARCHIVE_AFTER_DAYS` | `90` | Age before a memory is eligible for archive |
| `DEDUP_THRESHOLD` | `0.9` | Similarity above which a new memory is a duplicate |
| `RECENCY_HALF_LIFE_DAYS` | `7` | Half-life for temporal decay scoring |
| `KG_AUTO_ENABLED` | `false` | Auto-extract entities + relations on capture |
| `LOG_LEVEL` | `INFO` | Log verbosity |

### Manual config example

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "uvx",
      "args": ["mnemo-mcp"],
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

## Comparison vs. peers

| Feature | mnemo-mcp | Mem0 | Letta | OpenMemory |
|---|---|---|---|---|
| Hybrid retrieval (FTS + vec) | yes (FTS5 + sqlite-vec + RRF) | yes | partial | yes |
| Cross-encoder rerank chain | yes (qwen3 local + Jina + Cohere) | partial (Cohere only) | no | no |
| Temporal decay scoring | yes (exp half-life) | no | no | no |
| Importance boost in rank | yes (LLM 0.0-1.0) | no | no | no |
| Soft-archive + restore policy | yes (importance x recency) | no | no | no |
| Self-hostable (single SQLite file) | yes (zero ext deps) | partial (cloud-first) | yes (Postgres) | yes (Postgres + Qdrant) |
| Multi-provider LLM dispatch | yes (`LLM_MODELS` chain, any litellm provider) | partial | yes | partial |
| Plugin trinity (skills + hooks) | yes (recall-context + memory-commit) | n/a | n/a | n/a |
| Multi-machine sync | yes (GDrive bundled OAuth) | yes (cloud) | n/a | n/a |
| E2E-encrypted passport sync | yes (AES-256-GCM + Argon2id, S3 + GDrive) | no | no | no |
| LLM compression on capture | yes (multi-provider, ~3x at >=0.90 retention) | no | no | no |
| Backend-pluggable sync architecture | yes (S3 / R2 / B2 / MinIO + GDrive) | no | no | no |
| Bitemporal `valid_from` / `valid_to` queries | yes (`as_of` time-travel) | no | partial (events only) | no |
| Entity resolution via embedding KNN | yes (cosine threshold tunable) | no | no | no |
| Audit trail with state hashes | yes (`memory_audit` table) | no | no | no |

## Status

> **2026-05-02 -- Architecture stabilization update**
>
> Past months saw significant churn around credential handling and the daemon-bridge auto-spawn pattern. This caused multi-process races, browser tab spam, and inconsistent setup UX across plugins. **The architecture is now stable**: 2 clean modes (stdio + HTTP), no daemon-bridge layer, no auto-spawn from stdio.
>
> Apologies for the instability period. If you encountered issues with prior versions, please update to the latest release and follow the current [setup docs](https://mcp.n24q02m.com/servers/mnemo-mcp/setup/) -- most prior workarounds are no longer needed.
>
> **Related plugins from the same author**:
> - [wet-mcp](https://github.com/n24q02m/wet-mcp) -- Web search + content extraction
> - [imagine-mcp](https://github.com/n24q02m/imagine-mcp) -- Image/video understanding + generation
> - [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) -- Notion API
> - [better-email-mcp](https://github.com/n24q02m/better-email-mcp) -- Email management
> - [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) -- Telegram
> - [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) -- Godot Engine
> - [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph) -- Code review knowledge graph
>
> All plugins share the same architecture -- install once, learn pattern transfers.

## Documentation

Full docs at **[mcp.n24q02m.com/servers/mnemo-mcp/setup/](https://mcp.n24q02m.com/servers/mnemo-mcp/setup/)**:

- [Setup](https://mcp.n24q02m.com/servers/mnemo-mcp/setup/) -- install methods for Claude Code, Codex, Gemini CLI, Cursor, Windsurf, mcp.json
- [Modes overview](https://mcp.n24q02m.com/get-started/modes-overview/) -- stdio / local-relay / remote-relay / remote-oauth
- [Multi-user setup](https://mcp.n24q02m.com/get-started/multi-user/) -- per-JWT-sub credential model

In-repo references:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) -- storage layout, embedding / rerank dispatch, knowledge graph, plugin trinity
- [`docs/compression.md`](docs/compression.md) -- LLM compression pipeline
- [`docs/passport.md`](docs/passport.md) -- encrypted passport sync (S3 / GDrive backends)
- [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) -- retrieval quality + latency metrics

**Install with AI agent** -- paste this to your AI coding agent:

> Install MCP server `mnemo-mcp` following the steps at
> https://raw.githubusercontent.com/n24q02m/claude-plugins/main/plugins/mnemo-mcp/setup-with-agent.md

## Tools

15 MCP tools, 17 memory actions. The memory surface is exposed both as 11 specialized single-purpose tools and a legacy `memory` dispatcher (same actions), plus `config`, `help`, and `config__open_relay`:

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `add_memory`, `search_memory`, `list_memories`, `update_memory`, `delete_memory`, `export_memories`, `import_memories`, `memory_stats`, `restore_memory`, `archived_memories`, `consolidate_memories` | (one action each) | Specialized single-purpose memory tools -- the recommended surface |
| `memory` (legacy dispatcher) | `add`, `capture`, `search`, `list`, `update`, `delete`, `export`, `import`, `stats`, `restore`, `archived`, `archive_now`, `consolidate`, `compress`, `entity_search`, `entity_graph`, `history` | Core CRUD + typed capture (6 context_types) + hybrid search (RRF + rerank + temporal decay) + import/export + soft-archive + restore + on-demand archive sweep + LLM consolidation + LLM compression + temporal KG (entity search / graph / history) |
| `config` | `status`, `sync`, `set`, `warmup`, `setup_sync`, `setup_status`, `setup_start`, `setup_skip`, `setup_reset`, `setup_complete`, `setup_relay`, `sync_now`, `export_passport`, `import_passport` | Server status, trigger sync, update settings, pre-download embedding model, authenticate sync provider, manage HTTP setup form lifecycle, passport export/import |
| `help` | `topic="memory"` or `topic="config"` | Full documentation for any tool |
| `config__open_relay` | (HTTP relay mode) | Open the zero-config relay setup form (registered via mcp-core) |

Plugin trinity (Claude Code marketplace install):

| Component | Trigger | Purpose |
|---|---|---|
| `mnemo:recall-context` skill | session start, before significant decisions, "what do I know about X?" | Pulls cwd / topic-relevant memories with `context_type` filtering |
| `mnemo:memory-commit` skill | "remember this" / "save this" / "ghi nho" / "luu lai" | Typed manual capture with `context_type` decision tree |
| `mnemo:knowledge-audit` skill | periodic / "audit memory" | Find duplicates, contradictions, stale entries; consolidate |
| `mnemo:session-handoff` skill | end of session | Capture decisions / preferences / corrections / conventions / open questions |
| SessionStart hook | every session init | Non-blocking nudge to invoke `recall-context` |
| PostToolUse hook (opt-in) | `CAPTURE_AUTO_ENABLED=true` | Hint `memory-commit` after Write/Edit of CLAUDE.md / AGENTS.md / ARCHITECTURE.md / docs/*.md |

### MCP Resources

| URI | Description |
|:----|:------------|
| `mnemo://stats` | Database statistics and server status |

### MCP Prompts

| Prompt | Parameters | Description |
|:-------|:-----------|:------------|
| `save_summary` | `summary` | Generate prompt to save a conversation summary as memory |
| `recall_context` | `topic` | Generate prompt to recall relevant memories about a topic |

## Security

- **Graceful fallbacks** -- Cloud → Local embedding, no cross-mode fallback
- **Sync token security** -- OAuth tokens stored at `~/.mnemo-mcp/tokens/` with 600 permissions
- **Input validation** -- Sync provider, folder, remote validated against allowlists
- **Error sanitization** -- No credentials in error messages

## Build from Source

```bash
git clone https://github.com/n24q02m/mnemo-mcp.git
cd mnemo-mcp
uv sync
uv run mnemo-mcp
```

## Trust Model

This plugin implements **TC-Local** (machine-bound, single trust principal). The mode/storage/encryption breakdown below is the full classification.

| Mode | Credentials | Memory data | Who can read your data? |
|---|---|---|---|
| stdio (default) | Read from environment variables (no credential file written) | Local SQLite at `~/.mnemo-mcp/memories.db` | Only your OS user |
| HTTP self-host (single user) | Encrypted `config.enc` under `~/.mnemo-mcp/` | Local SQLite (same host) | Only you (admin = user) |
| HTTP multi-user remote (`PUBLIC_URL`) | Per-JWT-`sub` store at `subs/<sub>/config.json` | Per-`sub` isolated rows | Only the authenticated user (per-`sub` isolation) |

Passport sync bundles are always end-to-end encrypted (AES-256-GCM + Argon2id); backends
never see plaintext.

## License

MIT -- See [LICENSE](LICENSE).
