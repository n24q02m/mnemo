-- 0003_vector_state.sql -- track successful Vectorize writes for reindexing.
--
-- D1 cannot store sqlite-vec vectors, and the Vectorize API has no list or
-- get-by-id operation. The dense values remain in Vectorize; this table is
-- only the authoritative D1-side ledger of which current memory ids were
-- successfully upserted, together with the embedding identity that produced
-- them. Backfill uses the absence of a matching row to find work.

CREATE TABLE IF NOT EXISTS memory_vectors (
    sub TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_dims INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sub, memory_id),
    FOREIGN KEY (sub, memory_id)
        REFERENCES memories(sub, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_vectors_sub_updated
    ON memory_vectors(sub, updated_at);
