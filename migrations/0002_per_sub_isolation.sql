-- 0002_per_sub_isolation.sql -- add request-sub tenancy to the D1 schema.
--
-- 0001 is already live in some databases. SQLite cannot add a composite
-- primary key with ALTER TABLE, so this migration rebuilds the affected tables
-- into temporary tables, copies every existing row into the explicit legacy
-- scope `default`, and recreates the FTS/index contract.

DROP TRIGGER IF EXISTS memories_ai;
DROP TRIGGER IF EXISTS memories_ad;
DROP TRIGGER IF EXISTS memories_au;
DROP TABLE IF EXISTS memories_fts;

CREATE TABLE memories_v2 (
    sub TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
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
    superseded_by TEXT,
    PRIMARY KEY (sub, id)
);

INSERT INTO memories_v2 (
    sub, id, content, category, tags, source, created_at, updated_at,
    access_count, last_accessed, importance, context_type, archived_at,
    text_raw, compressed, compression_provider, commit_sha, valid_from,
    valid_to, superseded_by
)
SELECT
    'default', id, content, category, tags, source, created_at, updated_at,
    access_count, last_accessed, importance, context_type, archived_at,
    text_raw, compressed, compression_provider, commit_sha, valid_from,
    valid_to, superseded_by
FROM memories;

CREATE TABLE archived_memories_v2 (
    sub TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
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

INSERT INTO archived_memories_v2 (
    sub, id, content, category, tags, source, importance, created_at,
    updated_at, access_count, last_accessed, archived_at
)
SELECT
    'default', id, content, category, tags, source, importance, created_at,
    updated_at, access_count, last_accessed, archived_at
FROM archived_memories;

CREATE TABLE memory_entities_v2 (
    sub TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sub, id)
);

INSERT INTO memory_entities_v2 (
    sub, id, name, entity_type, created_at, updated_at
)
SELECT 'default', id, name, entity_type, created_at, updated_at
FROM memory_entities;

CREATE TABLE memory_edges_v2 (
    sub TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    memory_id TEXT,
    valid_from DATETIME,
    valid_to DATETIME,
    PRIMARY KEY (sub, id),
    FOREIGN KEY (sub, source_id)
        REFERENCES memory_entities_v2(sub, id) ON DELETE CASCADE,
    FOREIGN KEY (sub, target_id)
        REFERENCES memory_entities_v2(sub, id) ON DELETE CASCADE
);

INSERT INTO memory_edges_v2 (
    sub, id, source_id, target_id, relation_type, created_at, memory_id,
    valid_from, valid_to
)
SELECT
    'default', id, source_id, target_id, relation_type, created_at, memory_id,
    valid_from, valid_to
FROM memory_edges;

CREATE TABLE memory_entity_links_v2 (
    sub TEXT NOT NULL DEFAULT 'default',
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (sub, memory_id, entity_id),
    FOREIGN KEY (sub, memory_id)
        REFERENCES memories_v2(sub, id) ON DELETE CASCADE,
    FOREIGN KEY (sub, entity_id)
        REFERENCES memory_entities_v2(sub, id) ON DELETE CASCADE
);

INSERT INTO memory_entity_links_v2 (sub, memory_id, entity_id)
SELECT 'default', memory_id, entity_id
FROM memory_entity_links;

CREATE TABLE store_meta_v2 (
    sub TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (sub, key)
);

INSERT INTO store_meta_v2 (sub, key, value)
SELECT 'default', key, value
FROM store_meta;

DROP TABLE memory_entity_links;
DROP TABLE memory_edges;
DROP TABLE memory_entities;
DROP TABLE archived_memories;
DROP TABLE memories;
DROP TABLE store_meta;

ALTER TABLE memories_v2 RENAME TO memories;
ALTER TABLE archived_memories_v2 RENAME TO archived_memories;
ALTER TABLE memory_entities_v2 RENAME TO memory_entities;
ALTER TABLE memory_edges_v2 RENAME TO memory_edges;
ALTER TABLE memory_entity_links_v2 RENAME TO memory_entity_links;
ALTER TABLE store_meta_v2 RENAME TO store_meta;

CREATE INDEX idx_memories_sub_category
    ON memories(sub, category);
CREATE INDEX idx_memories_sub_updated
    ON memories(sub, updated_at);
CREATE INDEX idx_memories_sub_accessed
    ON memories(sub, last_accessed);
CREATE INDEX idx_memories_sub_category_updated
    ON memories(sub, category, updated_at DESC);

CREATE INDEX idx_archived_memories_sub_archived_at
    ON archived_memories(sub, archived_at DESC);

CREATE UNIQUE INDEX idx_memory_entities_sub_name_type
    ON memory_entities(sub, name, entity_type);

CREATE INDEX idx_memory_edges_sub_source
    ON memory_edges(sub, source_id);
CREATE INDEX idx_memory_edges_sub_target
    ON memory_edges(sub, target_id);
CREATE UNIQUE INDEX idx_memory_edges_sub_unique
    ON memory_edges(sub, source_id, target_id, relation_type);

CREATE INDEX idx_memory_entity_links_sub_entity_id
    ON memory_entity_links(sub, entity_id);

CREATE TABLE sync_state (
    sub TEXT NOT NULL DEFAULT 'default',
    backend TEXT NOT NULL,
    last_sync_at REAL,
    last_commit_sha TEXT,
    upload_cursor INTEGER,
    PRIMARY KEY (sub, backend)
);

CREATE VIRTUAL TABLE memories_fts
USING fts5(
    id UNINDEXED,
    content,
    category UNINDEXED,
    tags,
    content=memories,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, id, content, tags)
    VALUES (new.rowid, new.id, new.content, new.tags);
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
    VALUES ('delete', old.rowid, old.id, old.content, old.tags);
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
    VALUES ('delete', old.rowid, old.id, old.content, old.tags);
    INSERT INTO memories_fts(rowid, id, content, tags)
    VALUES (new.rowid, new.id, new.content, new.tags);
END;

INSERT INTO memories_fts(memories_fts) VALUES ('rebuild');
