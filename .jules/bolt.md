## 2024-05-24 - N+1 Query in Hybrid Search
**Learning:** When performing hybrid search (FTS + Vector) in `src/mnemo_mcp/db.py`, fetching full memory details for vector-only results individually causes an N+1 query bottleneck. While `sqlite-vec` returns `id` and `distance`, it does not return the full row. A loop executing `SELECT * FROM memories WHERE id = ?` for each missing ID severely degrades performance as the number of results grows.
**Action:** Always batch these lookups using a single `SELECT * FROM memories WHERE id IN (...)` query to fetch all missing records efficiently.
