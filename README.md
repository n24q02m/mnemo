# Mnemo MCP Server

> **Renamed (2026-09-13):** repo is now `mnemo` — CLI-first (`mnemo` command). PyPI package stays `mnemo-mcp`; MCP server remains a secondary surface.

mcp-name: io.github.n24q02m/mnemo

**Persistent AI memory with hybrid search. Open, free, unlimited.**

<!-- Badge Row 1: Status -->
[![Mode](https://img.shields.io/badge/mode-daemon_%C2%B7_http_remote_relay-5C6BC0)](https://mcp.n24q02m.com/get-started/modes-overview/)
[![CI](https://github.com/n24q02m/mnemo/actions/workflows/ci.yml/badge.svg)](https://github.com/n24q02m/mnemo/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/n24q02m/mnemo/graph/badge.svg?token=GELGVQNMUZ)](https://codecov.io/gh/n24q02m/mnemo)
[![PyPI](https://img.shields.io/pypi/v/mnemo-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/mnemo-mcp/)
[![License: Apache-2.0](https://img.shields.io/github/license/n24q02m/mnemo)](LICENSE)
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
| [mnemo](https://github.com/n24q02m/mnemo) | Persistent AI memory with hybrid search and embedded sync. Open, free, unlimi... | MCP |
| [fastretrieval](https://github.com/n24q02m/fastretrieval) | Multi-model retrieval runtime for ONNX/GGUF embeddings and reranking | Library |
| [skret](https://github.com/n24q02m/skret) | Secrets without the server. | CLI |
| [tacet](https://github.com/n24q02m/tacet) | A self-distilling neuro-symbolic cascade that amortises LLM cost across knowl... | Tooling |
| [web-core](https://github.com/n24q02m/web-core) | Shared web infrastructure package for search, scraping, HTTP security, and st... | Library |
| [wet-mcp](https://github.com/n24q02m/wet-mcp) | Open-source MCP server for AI agents: web search, content extraction, and lib... | MCP |

</details>
<!-- END: AUTO-GENERATED-CROSS-PROMO -->

## Table of contents

- [Features](#features)
- [Quick install](#quick-install)
- [Status](#status)
- [Documentation](#documentation)
- [Smithery](#smithery)
- [Tools](#tools)
- [Security](#security)
- [Build from Source](#build-from-source)
- [CLI](#cli)
- [Self-hosting (local HTTP instance)](#self-hosting-local-http-instance)
- [Remote (HTTP mode)](#remote-http-mode)
- [Trust Model](#trust-model)
- [License](#license)



<a href="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/n24q02m/mnemo-mcp/badge" alt="Mnemo MCP server" />
</a>

## Roadmap (current = Phase 3 / v2.x)

> Phase rows below describe the pre-de-host design history (v1.x / early v2):
> multi-provider LLM dispatch, GDrive/S3 passport sync, and Cloudflare
> deployment were **removed in the 2026-09 de-host**. Current architecture:
> one local SQLite store (WAL), per-task `[models.*]` provider cells
> (OpenRouter pre-wired default), no embedded sync (backup = rclone).

| Phase | Version | Status | Highlights |
|---|---|---|---|
| **Phase 1** | **v1.x** | **Shipped** | Typed `memory(action="capture")` (6 context_types + dedup) -- RRF (k=60) hybrid fusion + cross-encoder rerank + temporal decay -- importance x recency archive policy + restore -- Alembic migrations -- multi-provider LLM dispatch (pre-de-host) -- plugin trinity (recall-context + memory-commit skills, SessionStart + opt-in PostToolUse hooks) |
| **Phase 2** | v1.x+1 | **Shipped, partially removed** | LLM-driven compression of older memories (kept, now via `[models.chat]` cell) + Passport sync (encrypted import/export bundle; **removed 2026-09**) |
| **Phase 3** | **v2.0.0** | **Shipped (BREAKING)** | Temporal knowledge graph -- bitemporal `valid_from` / `valid_to` columns -- entity resolution via embedding KNN -- `entity_search` / `entity_graph` / `history` actions -- `KG_AUTO_ENABLED` opt-in auto-extract on capture |

## Features

- **Hybrid retrieval** -- FTS5 + vector search (sqlite-vec), fused via Reciprocal Rank Fusion (k=60), then re-ranked via the `[models.rerank]` provider cell (OpenRouter pre-wired default) with the local Fastretrieval Qwen3 cross-encoder as fallback, plus temporal decay and importance boost
- **Typed capture** -- `memory(action="capture")` with 6 context_types (`conversation`/`fact`/`preference`/`skill`/`task`/`decision`), embedding-based dedup, and optional `[models.chat]`-cell compression + importance scoring
- **Knowledge graph** -- Automatic entity extraction and relation tracking; top results boosted by graph proximity
- **Importance scoring + archive policy** -- LLM-scored 0.0-1.0 importance; soft-archive when `recency_factor * (1 - importance) > 1.0`; restore action available
- **Auto-archive trigger** -- Background sweep every Nth capture (default 100) -- no cron required
- **STM-to-LTM consolidation** -- LLM summarization of related memories in a category
- **Duplicate detection** -- Warns before adding semantically similar memories
- **Zero config** -- Fastretrieval's built-in local registry resolves Qwen3 ONNX embedding + reranking, no API keys needed. Optional cloud calls go through per-task `[models.<task>]` provider cells (OpenAI-spec; OpenRouter pre-wired default)
- **Local-first storage** -- one SQLite file (WAL) under `~/.mnemo/`; backup and cross-machine migration = `rclone` outside the server (no embedded sync)
- **Plugin trinity** -- Ships `/recall-context` + `/memory-commit` skills and SessionStart + opt-in PostToolUse hooks (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- **Proactive memory** -- Tool descriptions and skills guide AI to save preferences, decisions, facts at the right moment
- **LLM compression** -- Per-turn compression through the `[models.chat]` provider cell targets ~3x token reduction at >=0.9 fact retention; graceful skip when the cell is unconfigured (see [docs/compression.md](docs/compression.md))
- **Temporal knowledge graph** -- Bitemporal columns (`valid_from` / `valid_to` / `superseded_by`) on every memory + entity-resolution dedup (embedding KNN at default 0.85 cosine threshold) + audit trail (`memory_audit` table with prev/new state hashes) + new actions (`entity_search` / `entity_graph` / `history` / `as_of`) + opt-in `KG_AUTO_ENABLED` auto-extract on capture. **BREAKING** for clients that called `memory.get` expecting historical-inclusive results: pass `as_of` for time-travel; default now filters to current-state (`valid_to IS NULL`).

## Quick install

```bash
# Method 1: Claude Code plugin (skills + hooks; connects to a running
# mnemo HTTP instance -- start one per "Self-hosting" below)
/plugin marketplace add n24q02m/claude-plugins
/plugin install mnemo-mcp@n24q02m-plugins

# Method 2: run the HTTP server yourself and register the endpoint
uvx --from mnemo-mcp mnemo-mcp            # serves http://127.0.0.1:8000/mcp by default
claude mcp add --transport http mnemo http://127.0.0.1:8000/mcp

# Method 3 (remote): point a client at an existing HTTP deployment
claude mcp add --transport http mnemo https://<your-host>/mcp
```

Install matrix (the server speaks Streamable HTTP only — there is no stdio
transport post-de-host; see the
[Setup](https://mcp.n24q02m.com/servers/mnemo-mcp/setup/) page for full steps):

| Client | Install |
|---|---|
| Claude Code (plugin) | `/plugin marketplace add n24q02m/claude-plugins` then `/plugin install mnemo-mcp@n24q02m-plugins` (requires a running instance; see [Self-hosting](#self-hosting-local-http-instance)) |
| Claude Code (HTTP) | start the server (`uvx --from mnemo-mcp mnemo-mcp` or docker compose), then `claude mcp add --transport http mnemo http://127.0.0.1:8000/mcp` |
| Codex / Gemini CLI / Cursor / Windsurf | start the server, then register the `http://<host>:<port>/mcp` HTTP endpoint in the client's MCP settings |
| Any MCP client | point it at the `/mcp` endpoint of a running instance (Streamable HTTP) |

With `auth = "token"` or `"multi"` configured in `mnemo-config/config.toml`,
send the token as a Bearer credential (`--header "Authorization: Bearer <token>"`
or the client's equivalent).

## Comparison vs. peers

| Feature | mnemo | Mem0 | Letta | OpenMemory |
|---|---|---|---|---|
| Hybrid retrieval (FTS + vec) | yes (FTS5 + RRF + sqlite-vec) | yes | partial | yes |
| Cross-encoder rerank | yes (Fastretrieval Qwen3 local + `[models.rerank]` cell) | partial (Cohere only) | no | no |
| Temporal decay scoring | yes (exp half-life) | no | no | no |
| Importance boost in rank | yes (LLM 0.0-1.0) | no | no | no |
| Soft-archive + restore policy | yes (importance x recency) | no | no | no |
| Self-hostable (single SQLite file) | yes (zero ext deps) | partial (cloud-first) | yes (Postgres) | yes (Postgres + Qdrant) |
| LLM dispatch | yes (`[models.chat]` cell, any OpenAI-spec endpoint) | partial | yes | partial |
| Plugin trinity (skills + hooks) | yes (recall-context + memory-commit) | n/a | n/a | n/a |
| Cross-machine migration | yes (rclone backup/restore outside the server) | yes (cloud) | n/a | n/a |
| LLM compression on capture | yes ([models.chat] cell, ~3x at >=0.90 retention) | no | no | no |
| Bitemporal `valid_from` / `valid_to` queries | yes (`as_of` time-travel) | no | partial (events only) | no |
| Entity resolution via embedding KNN | yes (cosine threshold tunable) | no | no | no |
| Audit trail with state hashes | yes (`memory_audit` table) | no | no | no |

## Status

> **2026-09 -- De-host update**
>
> The Cloudflare D1/Vectorize/KV deployment mode, embedded GDrive/S3 passport
> sync, multi-provider key dispatch (per-provider API-key env vars + model
> chains), and the stdio transport were removed. mnemo now runs one HTTP MCP
> endpoint on a local SQLite (WAL) store, and all cloud calls go through
> per-task `[models.*]` provider cells (OpenRouter pre-wired default).
> Backup across machines = `rclone` outside the server.
>
> If you encountered issues with prior versions, update to the latest release
> and follow the current [setup docs](https://mcp.n24q02m.com/servers/mnemo-mcp/setup/).
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

mnemo-mcp was previously packaged for [Smithery](https://smithery.ai/) via a
local stdio start command. Post-de-host the server is HTTP-only, so the local
`smithery.yaml` was removed; publish a running instance's `https://<host>/mcp`
endpoint to Smithery as a remote server instead.

## Tools

13 MCP tools, 18 memory actions. The memory surface is exposed as 11
specialized single-purpose tools, the deprecated legacy `memory` dispatcher
(same actions), and `config`:

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `add_memory`, `search_memory`, `list_memories`, `update_memory`, `delete_memory`, `export_memories`, `import_memories`, `memory_stats`, `restore_memory`, `archived_memories`, `consolidate_memories` | (one action each) | Specialized single-purpose memory tools -- the recommended surface |
| `memory` (legacy dispatcher, **DEPRECATED** -- use the granular tools above instead; will be removed in a future release) | `add`, `capture`, `search`, `list`, `as_of`, `update`, `delete`, `export`, `import`, `stats`, `restore`, `archived`, `archive_now`, `consolidate`, `compress`, `entity_search`, `entity_graph`, `history` | Core CRUD + typed capture (6 context_types) + hybrid search (RRF + rerank + temporal decay) + import/export + soft-archive + restore + on-demand archive sweep + LLM consolidation + LLM compression + temporal KG (entity search / graph / history / as_of) |
| `config` | `status`, `set`, `warmup`, `backfill_embeddings` | Server status, update runtime settings, pre-download embedding model, backfill missing embedding vectors |

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

- **Graceful fallbacks** -- cloud provider cells degrade to local ONNX; an unconfigured cell never silently selects a paid provider
- **Host-only credentials** -- provider keys live in the host-owned `config.toml` or `HULL_<TASK>_API_KEY` env vars; end users never see them
- **Auth-gated HTTP** -- `auth = "no-auth"` refuses non-loopback binds; `token` / `multi` require credential checks
- **Error sanitization** -- No credentials in error messages

## Build from Source

```bash
git clone https://github.com/n24q02m/mnemo.git
cd mnemo
uv sync
uv run mnemo-mcp
```

## CLI

The package ships two distinct console scripts:

- **`mnemo`** -- CLI-first memory surface (primary for scripts/agents; it never
  starts a server): `capture`, `recall`, `reflect`, `fetch`, and the
  `standing-*` family operate directly on a SQLite memory DB.
  `mnemo-pilot` is a legacy alias of the same entry point.
- **`mnemo-mcp`** -- the MCP server plus one-shot operator subcommands. A
  bare invocation starts the HTTP server; a leading subcommand
  (`config-init`, `warmup`, `token-hash`, `token-verify`) runs an action
  and exits.

CLI-first memory surface (`mnemo`; every subcommand takes `--db <path>`,
prints a JSON envelope, and exits with a taxonomy-mapped code):

```bash
uvx --from mnemo-mcp mnemo recall --db ./mem.db "package naming" --k 3   # try without a persistent install

mnemo capture --db ./mem.db "keep PyPI name mnemo-mcp; repo is mnemo" --tags decision --category decision
mnemo recall --db ./mem.db "release ladder" --k 5        # search a subject's memories
mnemo reflect --db ./mem.db "why keep the alias?" --k 5  # bounded cited reflect over retrieval
mnemo fetch --db ./mem.db <memory_id>                    # fetch one memory by id
mnemo standing-refresh --db ./mem.db onboarding "how do releases cut?" --k 5   # materialize a standing page
mnemo standing-read --db ./mem.db onboarding             # cheap read with staleness info
```

Server operator CLI (`mnemo-mcp`; a bare invocation starts the HTTP server):

```bash
mnemo-mcp                       # start the Streamable HTTP MCP server
                                # (bind host/port from config.toml or MNEMO_HOST/MNEMO_PORT)

mnemo-mcp config-init [--force] # write ~/.mnemo/config.toml from the template
mnemo-mcp warmup                # pre-download local embedding model / probe cells
mnemo-mcp token-hash            # print a scrypt$ hash for [server] token_hash
                                # (reads MNEMO_AUTH_TOKEN or prompts)
mnemo-mcp token-verify <token> <scrypt$...>   # verify a token against a hash
```

| Subcommand | Purpose |
|:-----------|:--------|
| `config-init [--force]` | Write the default instance `config.toml` (server auth + `[models.*]` provider cells) |
| `warmup` | Pre-download the Fastretrieval-managed local ONNX embedding model so first use works offline |
| `token-hash` | Mint a `scrypt$` hash for `[server] token_hash` (shared-token auth) |
| `token-verify` | Verify a candidate token against a stored `scrypt$` hash |

## Self-hosting (local HTTP instance)

Two ways to run the server for MCP clients on your machine.

### Dev: start with `uv` (no-auth, loopback only)

```bash
uv run mnemo-mcp               # binds 127.0.0.1:8000, auth = "no-auth" by default
```

`no-auth` refuses non-loopback binds, so this is localhost-only by construction —
fine for trying the server locally. The MCP endpoint is
`http://127.0.0.1:8000/mcp`. For a real config, bootstrap one and edit it:

```bash
uv run mnemo-mcp config-init   # writes ~/.mnemo/config.toml from the template
```

### Always-on: `docker compose` (token auth, loopback-published port)

`docker-compose.http.yml` is self-contained (builds the image, persists state
in the `mnemo-data` volume) and publishes only on loopback:

```bash
cp mnemo-config/config.example.toml mnemo-config/config.toml   # then edit:
#   auth = "token"; set token_hash per the comments at the top of the example
docker compose -f docker-compose.http.yml up --build -d
# MCP endpoint: http://127.0.0.1:8771/mcp   (override the host port: MNEMO_PORT=9000 ...)
```

Token setup (also documented in the example config):

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"     # 1. mint token
MNEMO_AUTH_TOKEN=<token> uv run mnemo-mcp token-hash              # 2. print scrypt$ hash
# 3. paste the hash into token_hash in mnemo-config/config.toml; give clients the token
```

For `auth = "multi"` (per-user namespaces) also mount `users.toml` — see the
commented line in `docker-compose.http.yml`.

### CLI consumer (no server needed)

The `mnemo` surface talks straight to the memory DB — handy for scripts and
agents:

```bash
mnemo capture --db ./mem.db "keep PyPI name mnemo-mcp; repo is mnemo" --tags decision --category decision
mnemo recall  --db ./mem.db "release ladder" --k 5
mnemo fetch   --db ./mem.db <memory_id>
```

Every subcommand prints a JSON envelope and takes `--db <path>`. See
[CLI](#cli) for the full surface (`reflect`, `standing-*`, …).

### Pointing an MCP client at the instance

Register the HTTP endpoint (Streamable HTTP transport):

- Claude Code: `claude mcp add --transport http mnemo http://127.0.0.1:8771/mcp`
- Any OpenAI-spec MCP client: server URL `http://127.0.0.1:8771/mcp`; with
  `auth = "token"` send the shared token as the Bearer credential.

### Config: local vs cloud, per task

Each task cell in `mnemo-config/config.toml` (`[models.embed]`, `rerank`,
`chat`, `jev_score`) is independent: `base_url + api_key + model`, OpenAI-spec
HTTP. Mix freely — e.g. cloud OpenRouter for `chat` while `embed`/`rerank`
point at a local OpenAI-spec server, or all cloud. Keys are host-only
(end users never see them) and may alternatively come from the
`HULL_<TASK>_API_KEY` env vars.

## Remote (HTTP mode)

mnemo speaks Streamable HTTP on a single `/mcp` endpoint — remote access is a
self-hosted instance on a reachable host, fronted by whatever TLS proxy you
choose (the server itself binds plain HTTP). Auth is configured in
`mnemo-config/config.toml` under `[server]`: `auth = "token"` (one shared
Bearer token) or `auth = "multi"` (per-user tokens + namespaces via
`users.toml`). `auth = "no-auth"` refuses non-loopback binds.

Public OCI image publication is discontinued. Existing historical registry tags remain untouched; new container deployments build from source
(`docker build --target http`) or use `docker-compose.http.yml`.

## Trust Model

mnemo is **TC-Local** (machine-bound): every storage artifact lives under
`~/.mnemo/` owned by your OS user, and provider keys are host-only config
(`config.toml` / `HULL_<TASK>_API_KEY`), never visible to MCP clients.

| `[server] auth` | Bind allowed | Storage | Who can read your data? |
|---|---|---|---|
| `no-auth` (default) | loopback only (non-loopback bind refused) | `~/.mnemo/memories.db` + `config.toml` | Only your OS user |
| `token` | any | same, one shared `default` namespace | Anyone holding the shared token |
| `multi` | any | per-namespace `~/.mnemo/subs/<ns>/memories.db` (via `users.toml`) | Each token holder sees only their own namespace |


## License

Apache-2.0 -- See [LICENSE](LICENSE).
