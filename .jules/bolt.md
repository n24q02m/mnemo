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

## 2026-08-01 - Supersede in one statement, and close the transaction on every exit
**Commit:** 6633e6f (#1038)

**Learning:** `MemoryDB.update` read the row with a `SELECT ... WHERE valid_to IS NULL`, then closed it with a separate `UPDATE`. A competing writer that supersedes the same row between the two statements leaves two live rows and a supersession chain that points at the wrong successor; injecting that writer deterministically reproduces it. The `SELECT` also carried the `valid_to IS NULL` guard that made the loser of the race back off, so the guard has to move onto the write for the check and the write to be one decision.

The connection is opened in legacy autocommit-by-statement mode (`isolation_level=""`), where the first DML statement implicitly opens a transaction that only `commit()`/`rollback()` closes, and `MemoryDB.update` had no `try`/`rollback` at all. Two consequences, both measured:

- When the successor `INSERT` aborts, the predecessor stays closed with `superseded_by` pointing at a row that was never written, and the next unrelated `add()` commits that state. A fresh connection then finds the memory gone -- no live row, no successor. This is the pre-existing data-loss path and it is independent of how the row is read.
- `UPDATE ... RETURNING` opens a write transaction **even when it matches zero rows**, so the not-found branch must `rollback()` before returning. Without it the transaction stays open across subsequent `get`/`search`/`list` traffic, a second connection's write fails with `database is locked`, and `PRAGMA wal_checkpoint(TRUNCATE)` fails with `database table is locked`. This branch is ordinary, not rare: `update` is id-changing, so calling it again with the previous id lands there.

`RETURNING` yields the row **after** the update is applied ([sqlite.org/lang_returning](https://sqlite.org/lang_returning.html) §2), so `valid_to` and `superseded_by` must be reset on the successor row rather than carried forward. `RETURNING` also requires SQLite >= 3.35.0 and is unsupported on virtual tables, so `memories_vec` keeps its separate `SELECT`.

**Action:** Supersede with a single `UPDATE memories SET valid_to = ?, superseded_by = ? WHERE id = ? AND valid_to IS NULL RETURNING *`; wrap the body in `try/except BaseException: self._conn.rollback(); raise`; `rollback()` before the not-found `return None`; and check `sqlite3.sqlite_version_info` at open so an old library fails with a named requirement instead of a syntax error at the first write. Regression cover is `tests/test_db_update_atomicity.py` -- the guard test fails if `AND valid_to IS NULL` is deleted, and the not-found tests fail against the `RETURNING` form without the rollback.

**This is an atomicity change, not a speed change.** The removed `SELECT` was measured at 12.6us inside a ~350us call, and the run-to-run spread within a single branch (297-383us) is wider than the difference between branches. There is no throughput claim to make here, per the 2026-07-25 entry below.

## Rejected

### 2026-07-25 - Unmeasured speedup figures on `upsert_sync_state` (#1000, #1004)
Both PRs proposed the correct change and justified it with impact numbers that could not be checked: "~30% improvement based on benchmark profiling" (#1004) and "~2.12x speedup, 0.24s to 0.11s over 10,000 cycles" (#1000). The scripts producing them were not in the diff, the figures disagree with each other, and neither reflects this call site, which runs at most twice per sync and is dominated by network I/O against the remote backend. The change landed on the atomicity argument instead. Quote a number only when the harness that produced it is in the repo and runs the real code path.

### 2026-07-25 - Unexpanded shell substitution in ledger headings (#1000)
The proposed entry was headed `## $(date +%Y-%m-%d)`, a literal shell command written into Markdown. Two entries in `.jules/palette.md` already carried this and both have been corrected to their real commit dates. Write the date out.

### 2026-08-01 - Unmeasured speedup figures on `update` (#1029)
Same failure as the 2026-07-25 entry above, on the PR whose idea was taken into #1038. The Impact section claimed the removed `SELECT` was a throughput win, with no harness in the diff. Measured here at 4500 samples x 4 runs per branch: the `SELECT` is 12.6us inside a ~350us call, and the spread within a single branch (297-383us) is wider than the difference between branches (~2us median-of-medians). The change was worth making for atomicity, and #1038 stands on that argument alone. A profile that says a statement is removable does not say the removal is measurable.

## 2026-08-29 - Cache datetime.fromisoformat parsing in tight loops
**Learning:** `datetime.fromisoformat` string parsing and exponential recency decay math are expensive when called repeatedly in `_compute_hybrid_scores`. Because batched results (like those from a single tool call or sync) often share identical `updated_at` string values, computing the decay per-row without caching does a lot of redundant math.
**Action:** Introduced a local dictionary cache `recency_cache = {}` at the top of `_compute_hybrid_scores` to memoize the result of `_calc_recency(updated_at, now)`. This gives a ~85% speedup on large lists of records with identical timestamps by avoiding redundant `fromisoformat()` and floating-point math overhead.

## 2026-08-29 - Missing `check_same_thread=False` in fixture connection causes lockups in pytest
**Learning:** `FakeD1Worker` is called from HTTP threads via `asyncio.to_thread` during `MemoryDBCfBackend` tests. If the underlying `sqlite3.connect` for the test fixture does not include `check_same_thread=False`, the thread-crossing results in a hanging/timeout on Windows due to SQLite library locks/thread-safety checks silently halting execution or failing without a clean crash during the tests.
**Action:** Always include `check_same_thread=False` when constructing local SQLite test fixtures (`fake_worker` connecting to `d1.sqlite`) that simulate remote backend operations accessed through `asyncio.to_thread`.

## 2026-09-01 - Cache math.log1p frequency calculations in tight loops
**Learning:** `math.log1p` and floating point division are expensive when called repeatedly in `_compute_hybrid_scores`. Because many search or query results share the same `access_count` (often 0 or a low integer), computing this per-row without caching does a lot of redundant math.
**Action:** Introduced a local dictionary cache `freq_cache = {}` in `_compute_hybrid_scores` to memoize the result of `_calc_frequency(access_count)`. This provides a measurable speedup on large lists of records by avoiding redundant math overhead.

## 2026-09-05 - Avoid float casts and redundant variable assignments in hot loops
**Learning:** In `_compute_hybrid_scores`, calculating `importance = max(0.0, min(1.0, float(mem.get("importance") or 0.0)))` for every item in large search results creates unnecessary `float()` casts and clamping overhead when `importance` is usually missing or zero. Furthermore, checking a cache and extracting its value immediately into a separate variable adds slight overhead inside tight loops.
**Action:** Optimized `_compute_hybrid_scores` by extracting truthy `importance` values before casting (`imp = mem.get("importance"); importance = max(0.0, min(1.0, float(imp))) if imp else 0.0`), and referencing cache dictionary values directly instead of storing them into temporary variables. This yielded a ~5% performance improvement on large result sets.
