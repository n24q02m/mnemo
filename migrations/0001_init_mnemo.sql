-- mnemo-mcp D1 schema. Consolidated from the local SQLite schema (db.py
-- _init_*_schema) PLUS every Alembic migration (baseline_001, mem_001 context
-- types, mem_002 compression + sync_state, mem_003 temporal, mem_004 store_meta).
-- Every table carries a `sub` column (DECISION D3: shared-D1 per-sub isolation);
-- per-sub composite PKs + indexes scope all access. Vectors are NOT here
-- (sqlite-vec vec0 cannot run on D1) -- they live in Vectorize, filtered by sub.
--
-- Parity note vs the plan draft: `memories.valid_to` and `memories.superseded_by`
-- are INCLUDED (mem_003 adds both). valid_to is actively queried by
-- temporal/queries.py (`valid_to IS NULL` bitemporal filter); superseded_by is a
-- dormant forward-pointer kept for column parity with the OCI source so Task 19
-- data cutover maps 1:1. `memory_audit` + `memory_entities_vec` are INTENTIONALLY
-- ABSENT: memory_audit has no runtime reader/writer (migration-only), and
-- memory_entities_vec is a sqlite-vec table that temporal/resolve.py guards on
-- existence and falls back to name-only entity match when missing.

CREATE TABLE IF NOT EXISTS memories (
    id TEXT NOT NULL,
    sub TEXT NOT NULL DEFAULT 'default',
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
    archived_at TEXT,
    text_raw TEXT,
    compressed INTEGER NOT NULL DEFAULT 0,
    compression_provider TEXT,
    commit_sha TEXT,
    valid_from TEXT,
    valid_to TEXT,
    superseded_by TEXT,
    PRIMARY KEY (sub, id)
);
CREATE INDEX IF NOT EXISTS idx_memories_sub_cat_updated ON memories(sub, category, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_sub_accessed ON memories(sub, last_accessed);
CREATE INDEX IF NOT EXISTS idx_memories_sub_archived ON memories(sub, archived_at);

-- FTS5 external-content over memories (db.py:342-353). bm25 column weights are
-- applied at query time (db.py:996 bm25(memories_fts, 0.0, 1.0, 0.0, 5.0)).
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    content,
    category UNINDEXED,
    tags,
    content=memories,
    content_rowid=rowid,
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, id, content, tags) VALUES (new.rowid, new.id, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, tags) VALUES ('delete', old.rowid, old.id, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, tags) VALUES ('delete', old.rowid, old.id, old.content, old.tags);
    INSERT INTO memories_fts(rowid, id, content, tags) VALUES (new.rowid, new.id, new.content, new.tags);
END;

-- archived_memories side table (db.py:448-460) -- private, MUST be in the migration.
CREATE TABLE IF NOT EXISTS archived_memories (
    id TEXT NOT NULL,
    sub TEXT NOT NULL DEFAULT 'default',
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    PRIMARY KEY (sub, id)
);
CREATE INDEX IF NOT EXISTS idx_archived_sub_at ON archived_memories(sub, archived_at DESC);

-- Knowledge graph (db.py:408-442). sub column + per-sub uniqueness.
CREATE TABLE IF NOT EXISTS memory_entities (
    id TEXT NOT NULL,
    sub TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sub, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_sub_name_type ON memory_entities(sub, name, entity_type);

CREATE TABLE IF NOT EXISTS memory_edges (
    id TEXT NOT NULL,
    sub TEXT NOT NULL DEFAULT 'default',
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    memory_id TEXT,
    valid_from TEXT,
    valid_to TEXT,
    PRIMARY KEY (sub, id)
);
CREATE INDEX IF NOT EXISTS idx_edges_sub_source ON memory_edges(sub, source_id);
CREATE INDEX IF NOT EXISTS idx_edges_sub_target ON memory_edges(sub, target_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_sub_unique ON memory_edges(sub, source_id, target_id, relation_type);

CREATE TABLE IF NOT EXISTS memory_entity_links (
    sub TEXT NOT NULL DEFAULT 'default',
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (sub, memory_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_links_sub_entity ON memory_entity_links(sub, entity_id);

-- sync_state: PK (sub, backend) -- fixes mem_002 collision (mem_002:84 PK=backend only).
CREATE TABLE IF NOT EXISTS sync_state (
    sub TEXT NOT NULL DEFAULT 'default',
    backend TEXT NOT NULL,
    last_sync_at REAL,
    last_commit_sha TEXT,
    upload_cursor INTEGER,
    PRIMARY KEY (sub, backend)
);

-- store_meta: per-sub embedding identity guard (db.py:201-206 + :290-294).
CREATE TABLE IF NOT EXISTS store_meta (
    sub TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (sub, key)
);
