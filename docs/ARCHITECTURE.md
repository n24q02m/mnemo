# Mnemo MCP -- Architecture

> Phase 1 (v1.x) snapshot. Updated 2026-05-09 to reflect typed capture, RRF
> retrieval, archive policy, multi-provider LLM dispatch, and plugin trinity.

## High-level

```
+--------------------+        +---------------------+
| MCP client         |  MCP   | mnemo-mcp           |
| (Claude Code,      | <----> | FastMCP server      |
|  Cursor, Codex,    |        | 15 tools (memory    |
|  claude.ai web)    |        | + config + help)    |
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
[dedup probe] check_duplicate(text, threshold=DEDUP_THRESHOLD/0.9)
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
The table below is the full classification.

| Mode | Storage | Encryption | Who can read your data? |
|---|---|---|---|
| stdio (default) | `~/.mnemo-mcp/config.json` + `memories.db` | AES-GCM, machine-bound key | Only your OS user (file perm 0600) |
| HTTP self-host (single-user) | Same | Same | Only you (admin = user) |
| HTTP self-host (multi-user) | `~/.mnemo-mcp/subs/<sub>/config.json` + per-sub `memories.db` | Per-sub AES-GCM | Each authenticated user sees only their sub |

In multi-user remote mode, `MCP_DCR_SERVER_SECRET` is required as proof
of intentional multi-user deployment -- mnemo refuses to start with
`PUBLIC_URL` set but `MCP_DCR_SERVER_SECRET` missing.

---

## Phase 2 (v1.x+1.y) -- LLM compression + passport sync

> Phase 2 layers compression + cross-machine sync on top of the Phase 1
> capture / retrieval foundation without rewriting any existing path.
> Existing tests pass unchanged; Phase 1 callers see zero breaking
> changes.

### Compression pipeline

```
memory(action="capture", text=..., context_type="fact")
        |
        v
+-------------------+      dedup hit?      +------------------+
| capture()         | -------------------> | reuse existing   |
| (capture.py)      |                      | memory_id        |
+---------+---------+                      +------------------+
          | dedup miss
          v
+--------------------+
| compression.compress(text)
|   - reads COMPRESSION_ENABLED / PROVIDER / MODEL env
|   - resolves provider via llm.detect_provider() priority
|   - calls llm.call_llm with COMPRESSION_PROMPT (temp=0)
|   - tiktoken cl100k_base for tokens_in/out metrics
|   - graceful skip on no-provider / disabled / empty / error
+---------+----------+
          |
          v
db.add_with_context_type(
    content=<compressed>, text_raw=<original>,
    compressed=True, compression_provider="gemini", ...
)
```

Schema (mem_002_compression migration):

- `memories.text_raw TEXT` -- original text retained for audit / recovery
- `memories.compressed BOOLEAN NOT NULL DEFAULT 0`
- `memories.compression_provider TEXT`
- `sync_state` table -- per-backend sync cursor (see below)

Manual re-compression is exposed via
`memory(action="compress", memory_id=...)` for back-filling rows captured
before `COMPRESSION_ENABLED` was true.

### Sync architecture (backend-pluggable)

```
                   +-------------------------+
                   | sync_now orchestrator   |
                   | (sync.delta.sync_now)   |
                   +-----------+-------------+
                               |
              +----------------+----------------+
              v                                 v
   +---------------------+           +---------------------+
   | GDriveBackend       |           | S3Backend           |
   | (sync.gdrive)       |           | (sync.s3)           |
   |  uses Phase 1       |           |  boto3 + custom     |
   |  OAuth Device Code  |           |  endpoint for R2 / |
   |  token              |           |  B2 / MinIO         |
   +----------+----------+           +----------+----------+
              |                                 |
              v                                 v
       <gdrive>/<sync_folder>/passport/   <bucket>/<prefix>/
       seq-NNNNNN.bin                     seq-NNNNNN.bin
                  (opaque AES-256-GCM bundles)
```

Both backends implement the same `SyncBackend` ABC (push / pull /
last_remote_sequence / health_check). The package registry
(`sync.register / get / list_backends`) lazily wires backends; the
active one per deployment is selected XOR-style by
`sync.resolve_active_backend()` (S3 when `SYNC_S3_BUCKET` is set,
else GDrive — see `docs/passport.md`). New backends drop in by
subclassing `SyncBackend` and calling `sync.register("name", instance)`.

### Bundle format (E2E encryption)

```
+------------------------+ <- offset 0
| 4 bytes header_len     |
+------------------------+
| N bytes plaintext JSON | -- {"version":2,"kdf":"argon2id",
| header                 |     "salt":"<hex>","aead":"aes-256-gcm",
+------------------------+     "nonce":"<hex>"}
| M bytes AES-256-GCM    | -- associated_data = header bytes
| ciphertext             |
+------------------------+

Inside ciphertext (length-prefixed sections):
+--------+---------------+--------+--------------------+
| u32 BE | name (UTF-8)  | u64 BE | section data bytes |
+--------+---------------+--------+--------------------+

Sections (Phase 2):
- manifest.json
- memories.jsonl
- memories_entities.jsonl  (Phase 3 will populate)
- memories_edges.jsonl     (Phase 3 will populate)
```

Argon2id parameters (OWASP 2024 baseline): 32-byte salt per bundle,
3 iterations, 4 lanes, 64 MiB memory cost. Header is plaintext so an
operator can audit version + KDF without the passphrase. Wrong
passphrase OR ciphertext tampering both raise
`cryptography.exceptions.InvalidTag` (no oracle).

### Delta-sync protocol with LWW

```
            +--------------------+
            | sync_now()         |
            +-----+--------------+
                  | read sync_state.upload_cursor + last_sync_at
                  | query backend.last_remote_sequence
                  v
       remote_seq > local_cursor + 1 ?
       (other machine pushed in between)
                  |
        no        |        yes
        v         v
+----------+   +-------------------------------------+
| delta    |   | full pull -> apply_bundle (LWW per |
| push at  |   | row -> insert/update/skip+audit)    |
| cursor+1 |   | -> build_full_bundle -> push at     |
+----------+   | remote_seq+1                        |
               +-------------------------------------+

LWW per row inside apply_bundle:
  local missing                        -> INSERT
  local.updated_at < remote.updated_at -> REPLACE
  local.updated_at >= remote.updated_at -> SKIP + write
                                          sync_overrides audit row
```

`sync_overrides` is a side table created idempotently on first audit
hit. It carries (memory_id, local_updated_at, remote_updated_at,
local_content, remote_content, recorded_at) so the user can later
inspect divergence without losing the local change.

### Passphrase storage gate

The relay form collects `SYNC_PASSPHRASE` as a single password input.
Before persistence, `credential_state._harden_passphrase` swaps it for
`SYNC_PASSPHRASE_SALT` + `SYNC_PASSPHRASE_HASH` (Argon2id-derived hex).
The raw passphrase NEVER lands in `config.json`; the user must supply it
again per session (env var in stdio mode, relay form in HTTP mode).

Verification uses `bundle.verify_passphrase` which is constant-time
(`hmac.compare_digest`) so timing attacks cannot leak digest contents.
A leaked `config.json` exposes only the Argon2id digest (which still
needs to be brute-forced against the 64 MiB / 3-iter Argon2id cost).

### Background sync scheduler

`sync.start_passport_scheduler(db, interval)` spawns a background task
that wakes every `SYNC_INTERVAL` seconds and calls `sync_now` for each
backend in `SYNC_BACKEND`. An `asyncio.Lock` prevents concurrent ticks
overlapping with manual `config(action="sync_now")` calls. Per-backend
exceptions are logged + swallowed so one backend offline does not stall
the loop.

### MCP action surface (Phase 2 additions)

| Action | Purpose |
|---|---|
| `memory(action="compress", memory_id=...)` | Manual re-compression of an existing row. |
| `config(action="sync_now", key="<backend>")` | Push delta (or full-pull-push on sequence gap). |
| `config(action="export_passport")` | Write encrypted bundle to `<data_dir>/passport-<ts>.mnemo`. |
| `config(action="import_passport", key="<backend>")` | Pull latest bundle, LWW merge. |

Plugin trinity Phase 2 addition: `passport-bootstrap` skill guides
fresh-machine restore (detect backend -> prompt passphrase ->
import_passport -> verify status).

### Phase 2 env vars

```
COMPRESSION_ENABLED       (bool, default true)
COMPRESSION_PROVIDER      (gemini | openai | anthropic | xai; default auto)
COMPRESSION_MODEL         (provider model name; default per-provider)

SYNC_BACKEND              (comma-separated, default "gdrive")
SYNC_S3_BUCKET            (required for s3 backend)
SYNC_S3_REGION            (default "us-east-1"; "auto" for R2)
SYNC_S3_ENDPOINT          (custom endpoint for R2 / B2 / MinIO)
SYNC_S3_ACCESS_KEY_ID
SYNC_S3_SECRET_ACCESS_KEY
SYNC_S3_PREFIX            (default "passport/")

SYNC_PASSPHRASE           (raw passphrase, in-process only; never persisted)
```

---

## Phase 3 (v2.0.0) -- Temporal knowledge graph + entity resolution

> Phase 3 adds bitemporal columns (commit_sha / valid_from / valid_to /
> superseded_by), renames the Phase 1/2 graph tables to spec-canonical
> names (entities → memory_entities, relations → memory_edges,
> memory_entities join → memory_entity_links), introduces
> `memory_audit` mutation log, and ships the `memory_entities_vec`
> sqlite-vec table for embedding-based entity dedup. The bundle codec
> now actually populates the graph sections that Phase 2 reserved as
> empty placeholders.

### Schema (mem_003_temporal migration)

Additive on `memories`:

- `commit_sha TEXT` -- per-row sha256(content) for provenance + audit chain
  (backfilled for legacy rows during migration).
- `valid_from DATETIME` -- bitemporal lower bound (backfilled to
  `created_at` for legacy rows).
- `valid_to DATETIME` -- bitemporal upper bound (NULL = currently valid).
  Phase 3 default `memory.get` filters `valid_to IS NULL` (BREAKING).
- `superseded_by TEXT` -- forward pointer to the new memory id that
  replaced this one.

Renamed (idempotent — migration RENAMEs in-place; data preserved):

- `entities` → `memory_entities` (spec §5.2 canonical)
- `relations` → `memory_edges` (+ memory_id, valid_from, valid_to columns)
- `memory_entities` (join) → `memory_entity_links`

New tables:

- `memory_audit (id, memory_id, prev_state_hash, new_state_hash,
  operation, commit_sha, occurred_at)` + index on
  `(memory_id, occurred_at DESC)`.
- `memory_entities_vec` -- vec0 virtual table, `embedding float[768]`,
  rowid aligned with `memory_entities.rowid`.

### Capture pipeline (Phase 3 KG_AUTO_ENABLED path)

```
memory(action="capture", text=..., context_type="fact")
        |
        v
+------------------------+
| capture() -- Phase 1   |
| dedup + compress + add |
+-----------+------------+
            | memory_id (new row, valid_to=NULL)
            v
[background _enrich_memory]
   if settings.kg_auto_enabled:
     temporal.extract.extract_entities(text)
       (LLM via llm.call_llm dispatch)
            |
            v
     temporal.store.store_kg_with_memory_id(conn, mid, extracted)
       - upsert_entities (memory_entities)
       - create_relations (memory_edges)
       - link_memory_entities (memory_entity_links)
       - backfill memory_edges.memory_id = mid + valid_from = now
   else: legacy graph helpers (Phase 1 path; no KG bookkeeping)
```

`KG_AUTO_ENABLED` defaults to **False** so Phase 1/2 callers see no
behavioural change. Explicit opt-in via env var or
`config(action="set", key="kg_auto_enabled", value="true")`.

### Entity resolution

`temporal.resolve.resolve_entity(conn, name, type, embedding)`:

1. Stage 1 — exact name + type lookup in `memory_entities` (Phase 1
   semantics; deterministic).
2. Stage 2 — embedding KNN against `memory_entities_vec` when an
   embedding is supplied AND the vec table exists. Accepts the top-1
   neighbour when cosine similarity ≥ `TEMPORAL_ENTITY_RESOLUTION_THRESHOLD`
   (default 0.85). Cosine = `1 - L2_squared / 2` (assumes
   L2-normalised embeddings; matches Qwen3 / Jina default).
3. Miss → INSERT new entity AND parallel `memory_entities_vec` row at
   the entity's rowid for round-trip back-mapping.

### KG-aware queries

| Action | Purpose |
|---|---|
| `memory(action="entity_search", name=..., entity_type=..., limit=...)` | Find memories mentioning an entity (case-insensitive name + optional type filter, fuzzy LIKE fallback). |
| `memory(action="entity_graph", entity_id=..., name=..., depth=1\|2, limit=...)` | BFS neighbourhood subgraph anchored at one entity, depth-bounded. |
| `memory(action="history", entity_id=...)` | Timeline of all memories ever linked to an entity (includes superseded rows). |

Bitemporal filter (`memories_as_of`): when `as_of=None`, returns rows
with `valid_to IS NULL` (current state). Otherwise filters
`valid_from <= as_of < valid_to`.

### Bundle codec — KG sections populated

Phase 2 reserved `memories_entities.jsonl` + `memories_edges.jsonl` as
empty placeholders. Phase 3 populates them plus a new
`memories_entity_links.jsonl` section. Manifest schema_version bumps to
`mem_003_temporal` with `entity_count` / `edge_count` / `link_count`
fields. Receivers replay via INSERT OR IGNORE so duplicates collapse on
the unique indexes.

### Phase 3 env vars

```
KG_AUTO_ENABLED                        (bool, default false; opt-in)
TEMPORAL_ENTITY_RESOLUTION_THRESHOLD   (float, default 0.85)
TEMPORAL_SUPERSESSION_THRESHOLD        (float, default 0.85)
TEMPORAL_SUPERSESSION_ENABLED          (bool, default true)
```

### BREAKING: memory.get default filter

In v2.0.0+, `memory(action="get")` and the underlying
`db.memories_as_of(as_of=None)` filter `valid_to IS NULL` (current
state). Old clients that expect historical-inclusive results must now
pass an explicit `as_of` timestamp. Phase 1/2 `db.search` is unchanged
for backward compatibility — the BREAKING surface is limited to the
new `as_of`-aware action.

### Plugin trinity Phase 3 addition

The `knowledge-audit` skill grows 5 KG-specific dimensions: stale
entities, orphan edges, contradicting / superseded chains, bitemporal
drift detection, audit-trail integrity check. Triggers expand to: post
legacy-passport import, post `KG_AUTO_ENABLED=true` batch capture, pre
Phase 3 passport export.
