# Mnemo MCP Server

mcp-name: io.github.n24q02m/mnemo-mcp

**Persistent AI memory with hybrid search and embedded sync. Open, free, unlimited.**

<!-- Badge Row 1: Status -->
[![CI](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/n24q02m/mnemo-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/n24q02m/mnemo-mcp/graph/badge.svg?token=GELGVQNMUZ)](https://codecov.io/gh/n24q02m/mnemo-mcp)
[![PyPI](https://img.shields.io/pypi/v/mnemo-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/mnemo-mcp/)
[![License: Apache-2.0](https://img.shields.io/github/license/n24q02m/mnemo-mcp)](LICENSE)
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
| [agent-chat-plugin](https://github.com/n24q02m/agent-chat-plugin) | Peer AI agents chat in a shared folder — no human relay, no orchestrator, wor... | Tooling |
| [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph) | Knowledge graph for token-efficient code reviews -- semantic search and call-... | MCP |
| [better-drive](https://github.com/n24q02m/better-drive) | 2-way Google Drive sync with .driveignore filter — rclone engine, Windows tray | Tooling |
| [better-email-mcp](https://github.com/n24q02m/better-email-mcp) | IMAP/SMTP email for AI agents -- read, send, organize folders, and manage att... | MCP |
| [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) | Composite MCP server for Godot Engine -- 17 composite tools for AI-assisted g... | MCP |
| [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) | Markdown-first Notion for AI agents -- pages, databases, blocks, and comments... | MCP |
| [better-semantic-release](https://github.com/n24q02m/better-semantic-release) | Drop-in python-semantic-release fork with built-in release-safety guards (orp... | Tooling |
| [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) | Telegram for AI agents -- messages, chats, media, and contacts across both bo... | MCP |
| [better-workspace-mcp](https://github.com/n24q02m/better-workspace-mcp) | Google Workspace MCP server (Docs/Drive/Calendar/Gmail/Sheets/Slides/Tasks/Ch... | MCP |
| [claude-plugins](https://github.com/n24q02m/claude-plugins) | Claude Code plugin marketplace for the n24q02m MCP servers -- install web sea... | Marketplace |
| [imagine-mcp](https://github.com/n24q02m/imagine-mcp) | Image and video understanding + generation for AI agents -- across Gemini, Op... | MCP |
| [jules-task-archiver](https://github.com/n24q02m/jules-task-archiver) | Chrome Extension for bulk operations on Jules tasks via batchexecute API -- a... | Tooling |
| [mcp-core](https://github.com/n24q02m/mcp-core) | Shared foundation for building MCP servers -- Streamable HTTP transport, OAut... | MCP |
| [mnemo-mcp](https://github.com/n24q02m/mnemo-mcp) | Persistent AI memory with hybrid search and embedded sync. Open, free, unlimi... | MCP |
| [fastretrieval](https://github.com/n24q02m/fastretrieval) | Multi-model retrieval runtime for ONNX/GGUF embeddings and reranking | Library |
| [skret](https://github.com/n24q02m/skret) | Secrets without the server. | CLI |
| [tacet](https://github.com/n24q02m/tacet) | A self-distilling neuro-symbolic cascade that amortises LLM cost across knowl... | Tooling |
| [web-core](https://github.com/n24q02m/web-core) | Shared web infrastructure package for search, scraping, HTTP security, and st... | Library |
| [wet-mcp](https://github.com/n24q02m/wet-mcp) | Open-source MCP server for AI agents: web search, content extraction, and lib... | MCP |

</details>
<!-- END: AUTO-GENERATED-CROSS-PROMO -->

## Table of contents

- [Features](#features)
- [Status](#status)
- [Documentation](#documentation)
- [Smithery](#smithery)
- [Tools](#tools)
- [Security](#security)
- [Build from Source](#build-from-source)
- [CLI](#cli)
- [Remote (HTTP mode)](#remote-http-mode)
- [Deploy to Cloudflare](#deploy-to-cloudflare)
- [Trust Model](#trust-model)
- [License](#license)



<a href="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp/badge" alt="Mnemo MCP server" />
</a>

## Roadmap (current = Phase 3 / v2.x)

| Phase | Version | Status | Highlights |
|---|---|---|---|
| **Phase 1** | **v1.x** | **Shipped** | Typed `memory(action="capture")` (6 context_types + dedup) -- RRF (k=60) hybrid fusion + cross-encoder rerank + temporal decay -- importance x recency archive policy + restore -- Alembic migrations -- multi-provider LLM dispatch -- plugin trinity (recall-context + memory-commit skills, SessionStart + opt-in PostToolUse hooks) |
| **Phase 2** | v1.x+1 | **Shipped** | LLM-driven compression of older memories + Passport sync (encrypted import/export bundle for cross-machine bootstrap) -- AES-256-GCM + Argon2id, S3 / R2 / B2 / MinIO + GDrive backends, delta-sync with LWW per row |
| **Phase 3** | **v2.0.0** | **Shipped (BREAKING)** | Temporal knowledge graph -- bitemporal `valid_from` / `valid_to` columns -- entity resolution via embedding KNN -- `entity_search` / `entity_graph` / `history` actions -- KG-aware passport bundle sections -- `KG_AUTO_ENABLED` opt-in auto-extract on capture |

## Features

- **Hybrid retrieval** -- FTS5 + vector search (sqlite-vec locally, Vectorize on Cloudflare), fused via Reciprocal Rank Fusion (k=60), then re-ranked by a configurable rerank chain (`RERANK_MODELS`, order = litellm fallback; empty -> Fastretrieval's local Qwen3 reranker) with temporal decay and importance boost
- **Typed capture** -- `memory(action="capture")` with 6 context_types (`conversation`/`fact`/`preference`/`skill`/`task`/`decision`), embedding-based dedup, and a configurable LLM chain (`LLM_MODELS`, order = litellm fallback)
- **Knowledge graph** -- Automatic entity extraction and relation tracking; top results boosted by graph proximity
- **Importance scoring + archive policy** -- LLM-scored 0.0-1.0 importance; soft-archive when `recency_factor * (1 - importance) > 1.0`; restore action available
- **Auto-archive trigger** -- Background sweep every Nth capture (default 100) -- no cron required
- **STM-to-LTM consolidation** -- LLM summarization of related memories in a category
- **Duplicate detection** -- Warns before adding semantically similar memories
- **Zero config** -- Fastretrieval's built-in local registry resolves Qwen3 ONNX embedding + reranking, no API keys needed. Optional cloud providers (Jina AI, Gemini, OpenAI, Cohere)
- **Multi-machine sync** -- JSONL-based merge sync via Google Drive (bundled Desktop OAuth public client)
- **Plugin trinity** -- Ships `/recall-context` + `/memory-commit` skills and SessionStart + opt-in PostToolUse hooks (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- **Proactive memory** -- Tool descriptions and skills guide AI to save preferences, decisions, facts at the right moment
- **LLM compression** -- Per-turn compression via the multi-provider dispatcher targets ~3x token reduction at >=0.9 fact retention; graceful skip when no provider configured (see [docs/compression.md](docs/compression.md))
- **Encrypted passport sync** -- AES-256-GCM bundles + Argon2id KDF, S3 (R2 / B2 / MinIO) and Google Drive backends, delta-sync with last-write-wins per row (see [docs/passport.md](docs/passport.md)). Bootstrap via the `passport-bootstrap` skill.
- **Temporal knowledge graph** -- Bitemporal columns (`valid_from` / `valid_to` / `superseded_by`) on every memory + entity-resolution dedup (embedding KNN at default 0.85 cosine threshold) + audit trail (`memory_audit` table with prev/new state hashes) + new actions (`entity_search` / `entity_graph` / `history`) + opt-in `KG_AUTO_ENABLED` auto-extract on capture. **BREAKING** for clients that called `memory.get` expecting historical-inclusive results: pass `as_of` for time-travel; default now filters to current-state (`valid_to IS NULL`).

## Comparison vs. peers

| Feature | mnemo-mcp | Mem0 | Letta | OpenMemory |
|---|---|---|---|---|
| Hybrid retrieval (FTS + vec) | yes (FTS5 + RRF; sqlite-vec local / Vectorize on Cloudflare) | yes | partial | yes |
| Cross-encoder rerank chain | yes (Fastretrieval Qwen3 local + Jina + Cohere) | partial (Cohere only) | no | no |
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

**Install with AI agent** -- paste this to your AI coding agent:

> Install MCP server `mnemo-mcp` following the steps at
> https://raw.githubusercontent.com/n24q02m/claude-plugins/main/plugins/mnemo-mcp/setup-with-agent.md

## Smithery

mnemo-mcp is packaged for [Smithery](https://smithery.ai/) -- install or run it straight from the registry. It starts over stdio via `uvx mnemo-mcp` with no configuration required to launch; credentials are configured at runtime through the server's own config flow (see [Documentation](#documentation)). The published start command lives in [`smithery.yaml`](smithery.yaml).

## Tools

15 MCP tools, 17 memory actions. The memory surface is exposed both as 11 specialized single-purpose tools and a deprecated legacy `memory` dispatcher (same actions), plus `config`, `help`, and `config__open_relay`:

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `add_memory`, `search_memory`, `list_memories`, `update_memory`, `delete_memory`, `export_memories`, `import_memories`, `memory_stats`, `restore_memory`, `archived_memories`, `consolidate_memories` | (one action each) | Specialized single-purpose memory tools -- the recommended surface |
| `memory` (legacy dispatcher, **DEPRECATED** -- use the granular tools above instead; will be removed in a future release) | `add`, `capture`, `search`, `list`, `update`, `delete`, `export`, `import`, `stats`, `restore`, `archived`, `archive_now`, `consolidate`, `compress`, `entity_search`, `entity_graph`, `history` | Core CRUD + typed capture (6 context_types) + hybrid search (RRF + rerank + temporal decay) + import/export + soft-archive + restore + on-demand archive sweep + LLM consolidation + LLM compression + temporal KG (entity search / graph / history) |
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
| `mnemo:temporal-query` skill | "as of" / "back in" / "history of" / "what did I think then" | Point-in-time snapshots via `action="as_of"` and version-chain tracing via `superseded_by` |
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

## CLI

The `mnemo-mcp` console script both starts the server and exposes a few one-shot operator subcommands. A bare invocation (or any `--`-prefixed flag) starts the server; a leading subcommand runs an action and exits.

```bash
mnemo-mcp                       # start the stdio server (default transport)
mnemo-mcp --http                # start the Streamable HTTP server
                                # (also via MCP_TRANSPORT=http or TRANSPORT_MODE=http)

mnemo-mcp auth google           # authorize Google Drive sync via OAuth
mnemo-mcp auth google --client-id <ID> --client-secret <SECRET>   # bring-your-own OAuth client
mnemo-mcp logout                # clear the local Google Drive sync token
mnemo-mcp warmup                # pre-download Fastretrieval-managed local embedding + rerank models

mnemo-mcp config status         # report whether stored config exists
mnemo-mcp config delete --yes   # delete the stored (encrypted) config
mnemo-mcp relay status          # show the active browser-setup relay session
mnemo-mcp relay open            # open the relay setup form in a browser
mnemo-mcp relay reset           # clear relay session state
mnemo-mcp doctor                # environment diagnostics (Python, backend, store, mode)
```

| Subcommand | Purpose |
|:-----------|:--------|
| `auth <provider>` | Authorize a sync credential provider (currently `google`); `--client-id` / `--client-secret` supply a bring-your-own OAuth client |
| `warmup` | Pre-download the Fastretrieval-managed local Qwen3 ONNX embedding + rerank models so first use works offline |
| `config status` \| `config delete [--yes]` | Inspect or remove the stored encrypted configuration |
| `relay status` \| `relay open` \| `relay reset` | Inspect, open, or clear the zero-config browser setup session |
| `doctor` | Report Python version, credential backend, store dir, config, relay session, and storage mode |

## Remote (HTTP mode)

Deployed over HTTP, mnemo speaks Streamable HTTP transport and is OAuth-gated. Point any MCP client that supports remote HTTP + OAuth at `https://<your-host>/mcp` and authenticate on first connect; each authenticated user gets an isolated per-user credential store (see [Trust Model](#trust-model)). To stand up an instance, see [Deploy to Cloudflare](#deploy-to-cloudflare).

Public OCI image publication is discontinued. Existing historical registry tags
remain untouched; new container deployments build from source or use the
Cloudflare-managed registry.

## Deploy to Cloudflare

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/n24q02m/mnemo-mcp)

Run your own mnemo instance serverless on Cloudflare (Containers + D1 + Vectorize + KV).

**Prerequisites:** a Cloudflare account on the **Workers Paid plan** — required for Containers, D1, and Vectorize (the Cloudflare free tier does not include them) — and the `wrangler` CLI.

1. `git clone https://github.com/n24q02m/mnemo-mcp && cd mnemo-mcp`
2. `wrangler login`
3. Provision the storage bindings mnemo uses -- the memories database, the embedding
   index, and the encrypted credential store:
   ```
   wrangler d1 create mnemo-memories
   wrangler vectorize create mnemo-memory-vectors --dimensions 768 --metric cosine
   wrangler kv namespace create mnemo-kv
   ```
   Paste the returned D1 database ID and KV namespace ID into `wrangler.jsonc` (the
   Vectorize index binds by name, so no ID is needed), then create the memories schema
   (tables, indexes, and the FTS5 full-text index) in the database you just made:
   ```
   wrangler d1 migrations apply mnemo-memories --remote
   ```
   The SQL lives in `migrations/0001_init.sql`, and the D1 binding in `wrangler.jsonc`
   points at that folder via `migrations_dir: "migrations"`. Full-text search uses FTS5,
   which D1 ships; vector similarity is served by Vectorize rather than by an in-database
   extension, because D1 cannot load one.
4. Build the HTTP container from this checkout and push it to your Cloudflare managed registry (CF Containers cannot pull from external registries directly), then set `<YOUR_ACCOUNT_ID>` in `wrangler.jsonc`:
   ```
   docker build --target http -t mnemo-mcp:local .
   wrangler containers push mnemo-mcp:local
   # set image to registry.cloudflare.com/<YOUR_ACCOUNT_ID>/mnemo-mcp:local
   ```
5. Set `<YOUR_PUBLIC_URL>` (e.g. `https://mnemo.example.com`) and `<YOUR_WORKER_DOMAIN>`
   (e.g. `mnemo.example.com`) in `wrangler.jsonc`, then set the secrets:
   ```
   wrangler secret put CREDENTIAL_SECRET              # per-user vault key (encrypts the cf-kv credential store)
   wrangler secret put MCP_RELAY_PASSWORD             # shared password gating the browser setup form
   wrangler secret put MCP_DCR_SERVER_SECRET          # required once PUBLIC_URL is set (multi-user, per-JWT-sub)
   wrangler secret put JINA_AI_API_KEY                # EMBEDDING_MODELS + RERANK_MODELS (cloud embed / rerank)
   wrangler secret put GOOGLE_VERTEX_EXPRESS_API_KEY  # LLM_MODELS (graph extraction, importance, consolidation)
   ```
6. `wrangler deploy` and complete setup in the browser relay form at your Worker domain.

Storage maps to Cloudflare via `MCP_STORAGE_BACKEND=cf-kv` (credentials / tokens, encrypted),
`MEMORY_DB_BACKEND=cf-d1` (the memories database + FTS5 full-text; unset or `sqlite`
keeps the local SQLite file at `DB_PATH`), and Vectorize (embeddings,
cosine). Embedding and reranking are forced cloud through the `EMBEDDING_MODELS` /
`RERANK_MODELS` chains (`jina_ai/...`) so the container never downloads Fastretrieval's
local Qwen3 ONNX models, and graph / LLM features run through the `LLM_MODELS` chain (`vertex_express/...`).

### Authority & Sync Boundary

On Cloudflare deployments, **Cloudflare D1 + Vectorize + KV** is the sole production authority:
- **D1** (`MEMORY_DB_BACKEND=cf-d1`): Authoritative storage for memory rows, metadata, bitemporal valid ranges, and FTS5 search.
- **Vectorize** (`MCP_VECTORIZE_IDX`): Dense vector index for semantic similarity search.
- **KV** (`MCP_STORAGE_BACKEND=cf-kv`): Encrypted per-user credential and session store.
- **Sync boundary** (`SYNC_ENABLED=false`): Production Cloudflare deployments pin legacy Google Drive sync off; Cloudflare serves as the live authority.
- **Local & self-host bootstrap**: Local stdio (`~/.mnemo-mcp/memories.db`) and self-hosted instances retain optional passport sync (Google Drive Device Code OAuth or S3/R2/B2) for workstation migration.

## Trust Model

This plugin implements **TC-Local** (machine-bound, single trust principal). The mode/storage/encryption breakdown below is the full classification.

| Mode | Storage | Encryption | Who can read your data? |
|---|---|---|---|
| stdio (default) | `~/.mnemo-mcp/config.json` | AES-GCM, machine-bound key | Only your OS user (file perm 0600) |
| HTTP self-host | Same as stdio | Same | Only you (admin = user) |
| HTTP multi-user remote (`PUBLIC_URL`) | Per-JWT-sub credential store | AES-GCM | Only the authenticated user (per-`sub` isolation) |

### Workspace username (HTTP setup form)

The browser setup form has an optional **workspace username** field. Entering the
same username always lands you in the same per-`sub` bucket, so your credentials
and memories stay reachable across a re-authorization and across devices, instead
of being tied to the one-off subject minted for each `/authorize` round-trip.
Leaving it blank keeps the previous per-authorize behaviour.

Trust boundary: when the form is gated by a *shared* `MCP_RELAY_PASSWORD`, the
username is a partition key, not a secret -- anyone who knows that password can
type any username and reach that bucket. That is fine for a trusted group; an
untrusted multi-tenant deployment needs a per-user secret or delegated OAuth
instead.

**One-time migration:** existing users must re-enter their credentials once after
this change. Nothing is deleted; credentials stored under the old random subject
are simply no longer addressed.

## License

Apache-2.0 -- See [LICENSE](LICENSE).
