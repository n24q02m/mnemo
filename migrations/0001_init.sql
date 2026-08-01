-- 0001_init.sql -- initial mnemo-mcp schema for Cloudflare D1.
--
-- Source of truth: src/mnemo_mcp/db.py (MemoryDB._init_schema) PLUS the
-- Alembic lineage in src/mnemo_mcp/alembic/versions/ (baseline_001 ->
-- mem_001 -> mem_002_compression -> mem_003_temporal -> mem_004_store_meta).
-- On SQLite the schema is built incrementally: _init_schema creates the base
-- tables and then ALTER TABLE ADD COLUMN statements (one in db.py, the rest in
-- the Alembic revisions) grow `memories` to its final 19-column shape. A D1
-- database never walks that history, so THIS FILE IS THE END STATE, not the
-- baseline. When a column is added to the SQLite lineage, add it here too.
--
-- Deliberate differences from the SQLite build, and why:
--
--   * memories_vec is ABSENT ON PURPOSE -- it is not an oversight.
--     db.py::_ensure_vec_table creates `memories_vec` as a virtual table USING
--     vec0(...), which is provided by the loadable `sqlite-vec` extension
--     (db.py calls sqlite3.Connection.enable_load_extension + sqlite_vec.load).
--     D1 cannot load SQLite extensions: it ships a fixed subset (FTS5, JSON,
--     math functions) and offers no mechanism to load a third-party .so/.dylib.
--     Vector search on the D1 backend is served by Cloudflare Vectorize (the
--     VECTORIZE binding in wrangler.jsonc), wired up in a separate task -- not
--     by a table in this database. The same reasoning excludes
--     memory_entities_vec (created best-effort by mem_003_temporal).
--
--   * No PRAGMA statements. db.py sets journal_mode=WAL, synchronous=NORMAL and
--     busy_timeout=5000; none of those are in D1's supported PRAGMA list (D1
--     owns its own storage engine and durability settings). db.py also sets
--     `PRAGMA foreign_keys = ON`; on D1 that is already the default and cannot
--     be changed from a query, because D1 wraps every query in an implicit
--     transaction. The tables below are therefore created parent-first so no
--     `PRAGMA defer_foreign_keys` is needed.
--
--   * `memories` must stay a rowid table (no WITHOUT ROWID). memories_fts is an
--     external-content FTS5 index keyed on content_rowid=rowid; dropping the
--     rowid would break the index and its triggers.
--
--   * Three more tables exist in the SQLite lineage and are NOT created here,
--     because they are outside this migration's agreed scope rather than
--     because D1 cannot host them: `sync_state` (mem_002_compression),
--     `memory_audit` + idx_memory_audit_memory_time (mem_003_temporal), and
--     `alembic_version` (Alembic's own bookkeeping, which D1 replaces with the
--     `d1_migrations` table wrangler maintains). Unlike memories_vec, the first
--     two are plain tables that D1 would accept; add them in a follow-up
--     migration if the D1 backend needs delta-sync cursors or the audit log.
--
-- Notes on what is NOT changed, so the parity is easy to audit:
--   * IF NOT EXISTS is kept exactly as db.py writes it, so applying this file
--     to a database already seeded by the Python path is a no-op rather than an
--     error. wrangler tracks applied migrations in `d1_migrations` anyway.
--   * The FTS5 sync triggers are copied verbatim. D1 supports triggers, and
--     wrangler's SQL splitter keeps a `BEGIN ... END;` block as one statement
--     (it tracks compound statements). Keep END uppercase and on its own line:
--     the splitter's end-of-block test is case-sensitive.
--   * This file opens no explicit transaction of its own -- D1 already runs the
--     whole migration inside one. Do not add one, and do not write the phrase
--     for it in prose either: wrangler greps the RAW file (comments included)
--     for that literal and aborts the migration with "contains several
--     transactions" if it finds it. An earlier draft of this comment tripped
--     exactly that check.

-- ---------------------------------------------------------------------------
-- store_meta -- store-level key/value identity (embedding model + dims stamp).
-- db.py::_init_store_meta_schema, Alembic mem_004_store_meta.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT
);

-- ---------------------------------------------------------------------------
-- memories -- core memory rows.
-- Columns 1-9 from db.py::_init_memory_schema; the rest are the accumulated
-- ALTER TABLE ADD COLUMN upgrades, in the order they were introduced:
--   importance            db.py::_init_memory_schema (post-CREATE ALTER)
--   context_type,
--   archived_at           mem_001
--   text_raw, compressed,
--   compression_provider  mem_002_compression
--   commit_sha, valid_from,
--   valid_to, superseded_by  mem_003_temporal
-- valid_from is nullable here on purpose: the mem_003 docstring describes it as
-- NOT NULL DEFAULT CURRENT_TIMESTAMP, but the code it ships adds a plain
-- nullable DATETIME (SQLite ALTER TABLE ADD COLUMN cannot take a non-constant
-- default) and backfills it afterwards. The nullable shape is what every
-- existing store actually has, so it is what the Python layer reads.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    context_type TEXT NOT NULL DEFAULT 'conversation',
    archived_at DATETIME,
    text_raw TEXT,
    compressed BOOLEAN NOT NULL DEFAULT 0,
    compression_provider TEXT,
    commit_sha TEXT,
    valid_from DATETIME,
    valid_to DATETIME,
    superseded_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_category
    ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_updated
    ON memories(updated_at);
CREATE INDEX IF NOT EXISTS idx_memories_accessed
    ON memories(last_accessed);

-- Compound index that lets list_memories pagination
-- (WHERE category = ? ORDER BY updated_at DESC) skip a sort.
CREATE INDEX IF NOT EXISTS idx_memories_category_updated
    ON memories(category, updated_at DESC);

-- ---------------------------------------------------------------------------
-- memories_fts -- FTS5 full-text index over `memories`.
-- KEPT for D1: FTS5 is one of the SQLite extensions D1 ships (unlike vec0).
-- This is an EXTERNAL-CONTENT index (content=memories): it stores no column
-- values of its own and reads them back from `memories` via content_rowid.
-- That makes the three sync triggers below mandatory, not optional -- without
-- them the index silently drifts out of date on every write.
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(
    id UNINDEXED,
    content,
    category UNINDEXED,
    tags,
    content=memories,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

-- FTS5 triggers keeping the external-content index in sync with `memories`.
-- The delete-side statements must replay the same values that were indexed, so
-- they mirror db.py exactly (category is UNINDEXED and is not passed).
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, id, content, tags)
    VALUES (new.rowid, new.id, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
    VALUES ('delete', old.rowid, old.id, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
    VALUES ('delete', old.rowid, old.id, old.content, old.tags);
    INSERT INTO memories_fts(rowid, id, content, tags)
    VALUES (new.rowid, new.id, new.content, new.tags);
END;

-- ---------------------------------------------------------------------------
-- Knowledge graph. Canonical Phase 3 names (mem_003_temporal renames the
-- pre-Phase-3 `entities` / `relations` / `memory_entities` tables into these);
-- a fresh database gets them directly from db.py::_init_graph_schema.
-- Created parent-first so the REFERENCES clauses below resolve against tables
-- that already exist -- D1 enforces foreign keys and will not let a query turn
-- that off.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_entities (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_entities_name_type
    ON memory_entities(name, entity_type);

CREATE TABLE IF NOT EXISTS memory_edges (
    id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    memory_id TEXT,
    valid_from DATETIME,
    valid_to DATETIME
);
CREATE INDEX IF NOT EXISTS idx_memory_edges_source ON memory_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_memory_edges_target ON memory_edges(target_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_edges_unique
    ON memory_edges(source_id, target_id, relation_type);

CREATE TABLE IF NOT EXISTS memory_entity_links (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    PRIMARY KEY (memory_id, entity_id)
);

-- Index on entity_id so knowledge-graph traversal in find_related_memory_ids
-- does not fall back to a full table scan.
CREATE INDEX IF NOT EXISTS idx_memory_entity_links_entity_id
    ON memory_entity_links(entity_id);

-- ---------------------------------------------------------------------------
-- archived_memories -- rows moved out of `memories` by the archive policy.
-- db.py::_init_archive_schema.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS archived_memories (
    id TEXT PRIMARY KEY NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT NOT NULL,
    archived_at TEXT NOT NULL
);

-- Index on archived_at DESC so list_archived pagination skips a sort.
CREATE INDEX IF NOT EXISTS idx_archived_memories_archived_at
    ON archived_memories(archived_at DESC);
