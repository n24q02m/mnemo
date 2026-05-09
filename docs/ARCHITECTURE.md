# Mnemo MCP -- Architecture

> Phase 1 (v1.x) snapshot. Updated 2026-05-09 to reflect typed capture, RRF
> retrieval, archive policy, multi-provider LLM dispatch, and plugin trinity.

## High-level

```
+--------------------+        +---------------------+
| MCP client         |  MCP   | mnemo-mcp           |
| (Claude Code,      | <----> | FastMCP server      |
|  Cursor, Codex,    |        | 3 tools: memory,    |
|  claude.ai web)    |        | config, help        |
+--------------------+        +----------+----------+
                                         |
                                         v
                                +--------------------+
                                | SQLite (WAL)       |
                                |  - memories table  |
                                |  - memories_fts    |
                                |  - memories_vec    |
                                |  - alembic_version |
                                +--------------------+
```

The server stores everything in a single SQLite file under
`~/.mnemo-mcp/memories.db` (or `$DB_PATH`). FTS5 + `sqlite-vec` virtual
tables back the hybrid retrieval pipeline. No external services are
required for the local-only (ONNX) configuration.

## Capture pipeline (`memory(action="capture")`)

```
caller text
   |
   v
[validate context_type]   <-- one of: conversation, fact, preference,
   |                              skill, task, decision
   v
[embedding] (cloud or local Qwen3 ONNX)
   |
   v
[dedup probe] check_duplicate(text, threshold=DEDUP_THRESHOLD/0.92)
   |
   +-- duplicate? -----> return existing memory_id, status="deduplicated"
   |
   v (no duplicate)
[optional LLM fact extraction]   <-- multi-provider dispatch:
   |                                 GEMINI > OPENAI > ANTHROPIC > XAI
   |                                 graceful skip when no provider
   v
[db.add_with_context_type]
   |
   v
SQLite memories row (id, content, category, tags, source, embedding,
                     context_type, importance, archived_at, created_at,
                     updated_at)
   |
   v
[background enrichment]
   - score_importance via LLM (graph.py)
   - extract_entities + relations via LLM, link to memory
   - asyncio.create_task -- never blocks the response
   |
   v
[archive auto-trigger]
   - every Nth capture (ARCHIVE_TRIGGER_EVERY, default 100)
   - asyncio.to_thread(db.archive_by_score, ...)
```

Schema column added in Phase 1 by Alembic revision `mem_001_context_types`:

- `context_type TEXT NOT NULL DEFAULT 'conversation'`
- `archived_at DATETIME` (NULL = active; soft-archive timestamp)
- `importance REAL DEFAULT 0.5` (LLM-scored, used by archive + boost)

## Retrieval pipeline (`memory(action="search")`)

```
query string
   |
   v
+-------------------+         +-----------------------+
| FTS5 search       |         | embedding(query)      |
| (BM25-style       |         | + sqlite-vec ANN      |
|  full-text)       |         | (cosine distance)     |
+----+--------------+         +-----------+-----------+
     |                                    |
     v                                    v
   FTS5 ranked list                  vec0 ranked list
     |                                    |
     +----------+-------------------------+
                |
                v
          [RRF fusion k=60]
          score(d) = sum_i 1 / (k + rank_i(d))
                |
                v
          top-50 candidate pool
                |
                v
          [cross-encoder rerank]
            chain: qwen3-reranker (local) -> Jina (cloud) -> Cohere
            graceful skip when none available
                |
                v
          top-N reranked (default RERANK_TOP_N=10)
                |
                v
          [temporal decay scoring]
            score *= exp(-days_since_updated / RECENCY_HALF_LIFE_DAYS)
                |
                v
          [importance boost]
            score *= (1 + importance)
                |
                v
          [filter pass]
            context_type, since/until, min_importance, include_archived
                |
                v
          [graph boost]
            top-1 result -> find_related_memory_ids via entity links
            mark related results with graph_related: true
                |
                v
          final ranked results -> _format_memory -> JSON
```

The `db.search` method returns `max(50, limit*5)` candidates when a
reranker is active so the rerank pool is wide enough for meaningful
reordering; otherwise it returns exactly `limit` rows.

## Archive policy (`memory(action="archive_now")` + auto-sweep)

Soft-archive moves the row out of default search results by setting
`archived_at` to the current timestamp. The row is never deleted.

```
score = recency_factor * (1 - importance)
recency_factor = days_since_updated / ARCHIVE_AFTER_DAYS

archive when score > 1.0 AND archived_at IS NULL
```

Trigger paths:

- Manual: `memory(action="archive_now")` -- runs `db.archive_by_score`.
- Auto: every Nth capture via `ARCHIVE_TRIGGER_EVERY` (default 100).
- Scheduled: external cron (HTTP self-host deployments).

Restore: `memory(action="restore", memory_id=...)` clears `archived_at`.

## Multi-provider LLM dispatch (`mnemo_mcp.llm`)

Phase 1 ships the dispatch layer; actual fact-extraction prompts arrive in
Phase 2 (compression / passport sync).

```
auto-detect order:
  GEMINI_API_KEY / GOOGLE_API_KEY  -->  gemini/<model>
  OPENAI_API_KEY                   -->  openai/<model>
  ANTHROPIC_API_KEY                -->  anthropic/<model>
  XAI_API_KEY                      -->  xai/<model>
  none                             -->  return None + log warning,
                                        capture stores raw text
```

Caller override: `LLM_MODELS=provider/model[,provider/model,...]` env or
per-call kwarg. The dispatcher uses LiteLLM-compatible model strings.

## Plugin trinity (Phase 1 §14 addendum)

The plugin manifest at `.claude-plugin/plugin.json` declares the MCP
server stanza + `userConfig`. Claude Code auto-discovers `skills/` and
`hooks/` at the plugin root; no extra manifest fields are required.

```
plugin root/
  .claude-plugin/
    plugin.json        -- mcpServers + userConfig
  skills/
    knowledge-audit/SKILL.md   (pre-existing)
    session-handoff/SKILL.md   (pre-existing)
    recall-context/SKILL.md    (Phase 1, new)
    memory-commit/SKILL.md     (Phase 1, new)
  hooks/
    hooks.json         -- declares SessionStart + PostToolUse
    session-start.sh   (Phase 1, new)
    post-tool-use.sh   (Phase 1, new; opt-in CAPTURE_AUTO_ENABLED)
```

Skills are model-invoked workflows; hooks are non-blocking shell scripts
that emit hints into the session context. Neither hook makes MCP calls
directly -- the agent decides whether to invoke `recall-context` /
`memory-commit` based on the hint.

## Migration model (Alembic)

```
alembic/
  env.py          -- runs migrations against the live SQLite path
  script.py.mako  -- revision template
  versions/
    mem_001_context_types.py   -- Phase 1 schema upgrade
```

`MemoryDB.__init__` runs:

1. Open SQLite + enable WAL.
2. Query `alembic_version` table.
3. If behind target, **backup `memories.db` -> `memories.db.bak.<ts>`**
   then `alembic upgrade head`.
4. Re-open and proceed.

Migrations are idempotent: re-running `alembic upgrade head` on a current
schema is a no-op. Backup-before-migrate is mandatory; the server refuses
to upgrade when the backup write fails.

## Trust model

This plugin implements **TC-Local** (machine-bound, single trust principal).
See [mcp-core TRUST-MODEL.md](https://github.com/n24q02m/mcp-core/blob/main/docs/TRUST-MODEL.md)
for the full classification.

| Mode | Storage | Encryption | Who can read your data? |
|---|---|---|---|
| stdio (default) | `~/.mnemo-mcp/config.json` + `memories.db` | AES-GCM, machine-bound key | Only your OS user (file perm 0600) |
| HTTP self-host (single-user) | Same | Same | Only you (admin = user) |
| HTTP self-host (multi-user) | `~/.mnemo-mcp/subs/<sub>/config.json` + per-sub `memories.db` | Per-sub AES-GCM | Each authenticated user sees only their sub |

In multi-user remote mode, `MCP_DCR_SERVER_SECRET` is required as proof
of intentional multi-user deployment -- mnemo refuses to start with
`PUBLIC_URL` set but `MCP_DCR_SERVER_SECRET` missing.
