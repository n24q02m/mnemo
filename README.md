# Mnemo MCP Server

mcp-name: io.github.n24q02m/mnemo-mcp

**Persistent memory MCP server with hybrid retrieval (FTS5 + sqlite-vec + RRF fusion + cross-encoder rerank + temporal decay) and embedded sync. Open, free, unlimited.**

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
| [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph) | Knowledge graph for token-efficient code reviews -- fixed search, configurabl... | MCP |
| [better-email-mcp](https://github.com/n24q02m/better-email-mcp) | IMAP/SMTP email server for AI agents -- 6 composite tools with multi-account ... | MCP |
| [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) | Composite MCP server for Godot Engine -- 17 mega-tools for AI-assisted game d... | MCP |
| [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) | Markdown-first Notion API server for AI agents -- 10 composite tools replacin... | MCP |
| [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) | MCP server for Telegram with dual-mode support: Bot API (httpx) for quick bot... | MCP |
| [claude-plugins](https://github.com/n24q02m/claude-plugins) | Full documentation: mcp.n24q02m.com — unified docs for all 8 servers + the mc... | Marketplace |
| [imagine-mcp](https://github.com/n24q02m/imagine-mcp) | Production-grade MCP server for image and video understanding + generation ac... | MCP |
| [jules-task-archiver](https://github.com/n24q02m/jules-task-archiver) | Chrome Extension for bulk operations on Jules tasks via batchexecute API -- a... | Tooling |
| [mcp-core](https://github.com/n24q02m/mcp-core) | Unified MCP Streamable HTTP 2025-11-25 transport, OAuth 2.1 Authorization Ser... | MCP |
| [mnemo-mcp](https://github.com/n24q02m/mnemo-mcp) | Persistent AI memory with hybrid search and embedded sync. Open, free, unlimi... | MCP |
| [qwen3-embed](https://github.com/n24q02m/qwen3-embed) | Lightweight Qwen3 text embedding and reranking via ONNX Runtime and GGUF | Library |
| [skret](https://github.com/n24q02m/skret) | Secrets without the server. | CLI |
| [web-core](https://github.com/n24q02m/web-core) | Shared web infrastructure package for search, scraping, HTTP security, and st... | Library |
| [wet-mcp](https://github.com/n24q02m/wet-mcp) | Open-source MCP Server for web search, content extraction, library docs & mul... | MCP |

</details>
<!-- END: AUTO-GENERATED-CROSS-PROMO -->

## Table of contents

- [Features](#features)
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

## Roadmap (current = Phase 1 / v1.x)

| Phase | Version | Status | Highlights |
|---|---|---|---|
| **Phase 1** | **v1.x** | **Shipped** | Typed `memory(action="capture")` (6 context_types + dedup) -- RRF (k=60) hybrid fusion + cross-encoder rerank + temporal decay -- importance x recency archive policy + restore -- Alembic migrations -- multi-provider LLM dispatch -- plugin trinity (recall-context + memory-commit skills, SessionStart + opt-in PostToolUse hooks) |
| **Phase 2** | v1.x+1 | Planned | LLM-driven compression of older memories + Passport sync (encrypted import/export bundle for cross-machine bootstrap) |
| **Phase 3** | v2.0 | Planned (BREAKING) | Temporal knowledge graph -- bitemporal `as_of` queries, entity timelines, time-travel retrieval |

## Features

- **Hybrid retrieval** -- FTS5 + sqlite-vec, fused via Reciprocal Rank Fusion (k=60), then re-ranked by a cross-encoder chain (qwen3-reranker local -> Jina -> Cohere) with temporal decay and importance boost
- **Typed capture** -- `memory(action="capture")` with 6 context_types (`conversation`/`fact`/`preference`/`skill`/`task`/`decision`), embedding-based dedup, and a multi-provider LLM dispatcher (Gemini > OpenAI > Anthropic > xAI)
- **Knowledge graph** -- Automatic entity extraction and relation tracking; top results boosted by graph proximity
- **Importance scoring + archive policy** -- LLM-scored 0.0-1.0 importance; soft-archive when `recency_factor * (1 - importance) > 1.0`; restore action available
- **Auto-archive trigger** -- Background sweep every Nth capture (default 100) -- no cron required
- **STM-to-LTM consolidation** -- LLM summarization of related memories in a category
- **Duplicate detection** -- Warns before adding semantically similar memories
- **Zero config** -- Built-in local Qwen3 ONNX embedding + reranking, no API keys needed. Optional cloud providers (Jina AI, Gemini, OpenAI, Cohere)
- **Multi-machine sync** -- JSONL-based merge sync via Google Drive (bundled Desktop OAuth public client)
- **Plugin trinity** -- Ships `/recall-context` + `/memory-commit` skills and SessionStart + opt-in PostToolUse hooks (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- **Proactive memory** -- Tool descriptions and skills guide AI to save preferences, decisions, facts at the right moment

## Comparison vs. peers

| Feature | mnemo-mcp | Mem0 | Letta | OpenMemory |
|---|---|---|---|---|
| Hybrid retrieval (FTS + vec) | yes (FTS5 + sqlite-vec + RRF) | yes | partial | yes |
| Cross-encoder rerank chain | yes (qwen3 local + Jina + Cohere) | partial (Cohere only) | no | no |
| Temporal decay scoring | yes (exp half-life) | no | no | no |
| Importance boost in rank | yes (LLM 0.0-1.0) | no | no | no |
| Soft-archive + restore policy | yes (importance x recency) | no | no | no |
| Self-hostable (single SQLite file) | yes (zero ext deps) | partial (cloud-first) | yes (Postgres) | yes (Postgres + Qdrant) |
| Multi-provider LLM dispatch | yes (Gemini/OpenAI/Anthropic/xAI auto-detect) | partial | yes | partial |
| Plugin trinity (skills + hooks) | yes (recall-context + memory-commit) | n/a | n/a | n/a |
| Multi-machine sync | yes (GDrive bundled OAuth) | yes (cloud) | n/a | n/a |

## Status

> **2026-05-02 -- Architecture stabilization update**
>
> Past months saw significant churn around credential handling and the daemon-bridge auto-spawn pattern. This caused multi-process races, browser tab spam, and inconsistent setup UX across plugins. **As of v<auto>, the architecture is stable**: 2 clean modes (stdio + HTTP), no daemon-bridge layer, no auto-spawn from stdio.
>
> Apologies for the instability period. If you encountered issues with prior versions, please update to v<auto>+ and follow the current `docs/setup-manual.md` -- most prior workarounds are no longer needed.
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

Full docs at **[mcp.n24q02m.com/servers/mnemo-mcp/](https://mcp.n24q02m.com/servers/mnemo-mcp/)**:

- [Setup](https://mcp.n24q02m.com/servers/mnemo-mcp/setup/) -- install methods for Claude Code, Codex, Gemini CLI, Cursor, Windsurf, mcp.json
- [Modes overview](https://mcp.n24q02m.com/get-started/modes-overview/) -- stdio / local-relay / remote-relay / remote-oauth
- [Multi-user setup](https://mcp.n24q02m.com/get-started/multi-user/) -- per-JWT-sub credential model

**Install with AI agent** -- paste this to your AI coding agent:

> Install MCP server `mnemo-mcp` following the steps at
> https://raw.githubusercontent.com/n24q02m/claude-plugins/main/plugins/mnemo-mcp/setup-with-agent.md

## Tools

3 MCP tools, 13 memory actions:

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `memory` | `add`, `capture`, `search`, `list`, `update`, `delete`, `export`, `import`, `stats`, `restore`, `archived`, `archive_now`, `consolidate` | Core CRUD + typed capture (6 context_types) + hybrid search (RRF + rerank + temporal decay) + import/export + soft-archive + restore + on-demand archive sweep + LLM consolidation |
| `config` | `status`, `sync`, `set`, `warmup`, `setup_sync`, `setup_status`, `setup_start`, `setup_skip`, `setup_reset`, `setup_complete`, `setup_relay` | Server status, trigger sync, update settings, pre-download embedding model, authenticate sync provider, manage HTTP setup form lifecycle |
| `help` | `topic="memory"` or `topic="config"` | Full documentation for any tool |

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

This plugin implements **TC-Local** (machine-bound, single trust principal). See [mcp-core/docs/TRUST-MODEL.md](https://github.com/n24q02m/mcp-core/blob/main/docs/TRUST-MODEL.md) for full classification.

| Mode | Storage | Encryption | Who can read your data? |
|---|---|---|---|
| stdio (default) | `~/.mnemo-mcp/config.json` | AES-GCM, machine-bound key | Only your OS user (file perm 0600) |
| HTTP self-host | Same as stdio | Same | Only you (admin = user) |

## License

MIT -- See [LICENSE](LICENSE).
