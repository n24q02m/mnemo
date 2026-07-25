## 2026-07-07 - Optimize JSON payload serialization
**Learning:** Returning large JSON lists of objects (like search or list results) with `indent=2` adds significant byte overhead due to unnecessary whitespace and newlines, hurting serialization performance and increasing network latency/token cost.
**Action:** Replaced `json.dumps(obj, indent=2)` with `json.dumps(obj, separators=(",", ":"))` in `_json` helper to eliminate all unnecessary whitespace from MCP tool responses while preserving schema compatibility.

## 2026-07-07 - Use json_each for multi-column IN clauses in SQLite
**Learning:** For multi-column IN clauses (like (name, entity_type)), dynamically generating batch queries with `f"IN (VALUES {placeholders})"` and unrolling parameters adds Python-side string interpolation and looping overhead while hitting `SQLITE_MAX_VARIABLE_NUMBER` limits.
**Action:** Replace batched multi-column IN clauses with a single parameter containing a JSON array of tuples and query it using `IN (SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]') FROM json_each(?))`. This is both faster and eliminates the need for loop-based parameter batching.

## 2026-07-25 - Merge partial upserts in SQL, not in Python
**Learning:** `MemoryDB.upsert_sync_state` merged a partial update by reading the current row, filling the blanks in Python, then writing the whole row back with `INSERT OR REPLACE`. `MemoryDB` opens SQLite with `check_same_thread=False` and `mnemo_mcp.sync.delta` calls this through `asyncio.to_thread`, so two partial updates to different columns could interleave and the later writer would restore the stale value it had read. `INSERT OR REPLACE` also deletes and re-inserts the row rather than editing it, so the row identity changed on every write.

**Action:** Merge partial upserts inside the statement with `INSERT ... ON CONFLICT(<key>) DO UPDATE SET col = COALESCE(excluded.col, col)`. The read disappears and the write becomes a single atomic statement. Regression cover is `tests/test_migrations.py::test_mem_002_upsert_sync_state_updates_in_place`, which asserts the row keeps its rowid across a partial update; that fails against the read-modify-write version, because `INSERT OR REPLACE` deletes and re-inserts.

**When proposing this as a speed change, measure it.** The justification that carried here was atomicity, not throughput; a benchmark run in a scratch script is not evidence about this code path and should not be quoted as an impact figure.

**A thread-hammering test was tried here and dropped.** Driving `upsert_sync_state` from two threads in a loop raises `SystemError: error return without exception set` from the `sqlite3` module, intermittently, on both the old and new code. `MemoryDB` shares one connection opened with `check_same_thread=False`, and that connection is not safe under genuinely simultaneous use — a separate pre-existing problem this change narrows but does not solve. Do not add a concurrency test here until the connection itself is guarded.

## Rejected

### 2026-07-25 - Unmeasured speedup figures on `upsert_sync_state` (#1000, #1004)
Both PRs proposed the correct change and justified it with impact numbers that could not be checked: "~30% improvement based on benchmark profiling" (#1004) and "~2.12x speedup, 0.24s to 0.11s over 10,000 cycles" (#1000). The scripts producing them were not in the diff, the figures disagree with each other, and neither reflects this call site, which runs at most twice per sync and is dominated by network I/O against the remote backend. The change landed on the atomicity argument instead. Quote a number only when the harness that produced it is in the repo and runs the real code path.

### 2026-07-25 - Unexpanded shell substitution in ledger headings (#1000)
The proposed entry was headed `## $(date +%Y-%m-%d)`, a literal shell command written into Markdown. Two entries in `.jules/palette.md` already carried this and both have been corrected to their real commit dates. Write the date out.
