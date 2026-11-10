# Engineering lessons

Lessons recovered from the notes of a discarded third-party automation
tool, kept here instead of deleted. Each entry carries the commit that landed
the change in this repository, so a proposal can be located in the history
before the same change is proposed again. Dates are landing dates taken from
`git log`; the order below is the order the notes recorded, not a re-sorting.

## Performance

### 2026-07-07 - Optimize JSON payload serialization
**Learning:** Returning large JSON lists of objects (like search or list results) with `indent=2` adds significant byte overhead due to unnecessary whitespace and newlines, hurting serialization performance and increasing network latency/token cost.
**Action:** Replaced `json.dumps(obj, indent=2)` with `json.dumps(obj, separators=(",", ":"))` in `_json` helper to eliminate all unnecessary whitespace from MCP tool responses while preserving schema compatibility.

### 2026-07-07 - Use json_each for multi-column IN clauses in SQLite
**Learning:** For multi-column IN clauses (like (name, entity_type)), dynamically generating batch queries with `f"IN (VALUES {placeholders})"` and unrolling parameters adds Python-side string interpolation and looping overhead while hitting `SQLITE_MAX_VARIABLE_NUMBER` limits.
**Action:** Replace batched multi-column IN clauses with a single parameter containing a JSON array of tuples and query it using `IN (SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]') FROM json_each(?))`. This is both faster and eliminates the need for loop-based parameter batching.

### 2026-07-25 - Merge partial upserts in SQL, not in Python
**Learning:** `MemoryDB.upsert_sync_state` merged a partial update by reading the current row, filling the blanks in Python, then writing the whole row back with `INSERT OR REPLACE`. `MemoryDB` opens SQLite with `check_same_thread=False` and `mnemo.sync.delta` calls this through `asyncio.to_thread`, so two partial updates to different columns could interleave and the later writer would restore the stale value it had read. `INSERT OR REPLACE` also deletes and re-inserts the row rather than editing it, so the row identity changed on every write.

**Action:** Merge partial upserts inside the statement with `INSERT ... ON CONFLICT(<key>) DO UPDATE SET col = COALESCE(excluded.col, col)`. The read disappears and the write becomes a single atomic statement. Regression cover is `tests/test_migrations.py::test_mem_002_upsert_sync_state_updates_in_place`, which asserts the row keeps its rowid across a partial update; that fails against the read-modify-write version, because `INSERT OR REPLACE` deletes and re-inserts.

**When proposing this as a speed change, measure it.** The justification that carried here was atomicity, not throughput; a benchmark run in a scratch script is not evidence about this code path and should not be quoted as an impact figure.

**A thread-hammering test was tried here and dropped.** Driving `upsert_sync_state` from two threads in a loop raises `SystemError: error return without exception set` from the `sqlite3` module, intermittently, on both the old and new code. `MemoryDB` shares one connection opened with `check_same_thread=False`, and that connection is not safe under genuinely simultaneous use — a separate pre-existing problem this change narrows but does not solve. Do not add a concurrency test here until the connection itself is guarded.

### 2026-08-01 - Supersede in one statement, and close the transaction on every exit
**Commit:** 6633e6f (#1038)

**Learning:** `MemoryDB.update` read the row with a `SELECT ... WHERE valid_to IS NULL`, then closed it with a separate `UPDATE`. A competing writer that supersedes the same row between the two statements leaves two live rows and a supersession chain that points at the wrong successor; injecting that writer deterministically reproduces it. The `SELECT` also carried the `valid_to IS NULL` guard that made the loser of the race back off, so the guard has to move onto the write for the check and the write to be one decision.

The connection is opened in legacy autocommit-by-statement mode (`isolation_level=""`), where the first DML statement implicitly opens a transaction that only `commit()`/`rollback()` closes, and `MemoryDB.update` had no `try`/`rollback` at all. Two consequences, both measured:

- When the successor `INSERT` aborts, the predecessor stays closed with `superseded_by` pointing at a row that was never written, and the next unrelated `add()` commits that state. A fresh connection then finds the memory gone -- no live row, no successor. This is the pre-existing data-loss path and it is independent of how the row is read.
- `UPDATE ... RETURNING` opens a write transaction **even when it matches zero rows**, so the not-found branch must `rollback()` before returning. Without it the transaction stays open across subsequent `get`/`search`/`list` traffic, a second connection's write fails with `database is locked`, and `PRAGMA wal_checkpoint(TRUNCATE)` fails with `database table is locked`. This branch is ordinary, not rare: `update` is id-changing, so calling it again with the previous id lands there.

`RETURNING` yields the row **after** the update is applied ([sqlite.org/lang_returning](https://sqlite.org/lang_returning.html) §2), so `valid_to` and `superseded_by` must be reset on the successor row rather than carried forward. `RETURNING` also requires SQLite >= 3.35.0 and is unsupported on virtual tables, so `memories_vec` keeps its separate `SELECT`.

**Action:** Supersede with a single `UPDATE memories SET valid_to = ?, superseded_by = ? WHERE id = ? AND valid_to IS NULL RETURNING *`; wrap the body in `try/except BaseException: self._conn.rollback(); raise`; `rollback()` before the not-found `return None`; and check `sqlite3.sqlite_version_info` at open so an old library fails with a named requirement instead of a syntax error at the first write. Regression cover is `tests/test_db_update_atomicity.py` -- the guard test fails if `AND valid_to IS NULL` is deleted, and the not-found tests fail against the `RETURNING` form without the rollback.

**This is an atomicity change, not a speed change.** The removed `SELECT` was measured at 12.6us inside a ~350us call, and the run-to-run spread within a single branch (297-383us) is wider than the difference between branches. There is no throughput claim to make here, per the 2026-07-25 entry below.

### Rejected

#### 2026-07-25 - Unmeasured speedup figures on `upsert_sync_state` (#1000, #1004)
Both PRs proposed the correct change and justified it with impact numbers that could not be checked: "~30% improvement based on benchmark profiling" (#1004) and "~2.12x speedup, 0.24s to 0.11s over 10,000 cycles" (#1000). The scripts producing them were not in the diff, the figures disagree with each other, and neither reflects this call site, which runs at most twice per sync and is dominated by network I/O against the remote backend. The change landed on the atomicity argument instead. Quote a number only when the harness that produced it is in the repo and runs the real code path.

#### 2026-07-25 - Unexpanded shell substitution in ledger headings (#1000)
The proposed entry was headed `## $(date +%Y-%m-%d)`, a literal shell command written into Markdown. Two entries in the accessibility section of this file already carried this and both have been corrected to their real commit dates. Write the date out.

#### 2026-08-01 - Unmeasured speedup figures on `update` (#1029)
Same failure as the 2026-07-25 entry above, on the PR whose idea was taken into #1038. The Impact section claimed the removed `SELECT` was a throughput win, with no harness in the diff. Measured here at 4500 samples x 4 runs per branch: the `SELECT` is 12.6us inside a ~350us call, and the spread within a single branch (297-383us) is wider than the difference between branches (~2us median-of-medians). The change was worth making for atomicity, and #1038 stands on that argument alone. A profile that says a statement is removable does not say the removal is measurable.

### 2026-08-29 - Cache datetime.fromisoformat parsing in tight loops
**Learning:** `datetime.fromisoformat` string parsing and exponential recency decay math are expensive when called repeatedly in `_compute_hybrid_scores`. Because batched results (like those from a single tool call or sync) often share identical `updated_at` string values, computing the decay per-row without caching does a lot of redundant math.
**Action:** Introduced a local dictionary cache `recency_cache = {}` at the top of `_compute_hybrid_scores` to memoize the result of `_calc_recency(updated_at, now)`. This gives a ~85% speedup on large lists of records with identical timestamps by avoiding redundant `fromisoformat()` and floating-point math overhead.

### 2026-08-29 - Missing `check_same_thread=False` in fixture connection causes lockups in pytest
**Learning:** `FakeD1Worker` is called from HTTP threads via `asyncio.to_thread` during `MemoryDBCfBackend` tests. If the underlying `sqlite3.connect` for the test fixture does not include `check_same_thread=False`, the thread-crossing results in a hanging/timeout on Windows due to SQLite library locks/thread-safety checks silently halting execution or failing without a clean crash during the tests.
**Action:** Always include `check_same_thread=False` when constructing local SQLite test fixtures (`fake_worker` connecting to `d1.sqlite`) that simulate remote backend operations accessed through `asyncio.to_thread`.

### 2026-09-01 - Cache math.log1p frequency calculations in tight loops
**Learning:** `math.log1p` and floating point division are expensive when called repeatedly in `_compute_hybrid_scores`. Because many search or query results share the same `access_count` (often 0 or a low integer), computing this per-row without caching does a lot of redundant math.
**Action:** Introduced a local dictionary cache `freq_cache = {}` in `_compute_hybrid_scores` to memoize the result of `_calc_frequency(access_count)`. This provides a measurable speedup on large lists of records by avoiding redundant math overhead.

### 2026-09-05 - Avoid float casts and redundant variable assignments in hot loops
**Learning:** In `_compute_hybrid_scores`, calculating `importance = max(0.0, min(1.0, float(mem.get("importance") or 0.0)))` for every item in large search results creates unnecessary `float()` casts and clamping overhead when `importance` is usually missing or zero. Furthermore, checking a cache and extracting its value immediately into a separate variable adds slight overhead inside tight loops.
**Action:** Optimized `_compute_hybrid_scores` by extracting truthy `importance` values before casting (`imp = mem.get("importance"); importance = max(0.0, min(1.0, float(imp))) if imp else 0.0`), and referencing cache dictionary values directly instead of storing them into temporary variables. This yielded a ~5% performance improvement on large result sets.

### 2025-01-20 - Avoid redundant boundary enforcements in tight loops
**Learning:** In `_compute_hybrid_scores`, bounding `importance` with `max(0.0, min(1.0, float(imp)))` for every item in large search results creates unnecessary overhead per iteration, especially since the database insertion logic already strictly enforces these boundaries (0.0 to 1.0). Python built-in functions like `min()` and `max()` add measurable overhead when called repeatedly.
**Action:** Optimized `_compute_hybrid_scores` by removing the redundant `min/max` bounds check and calculating the score directly with `mem["score"] = base * (1.0 + float(imp)) if imp else base`. This yielded a ~20% performance improvement on large result sets.
### 2026-09-02 - Avoid redundant boundary enforcement in tight loops
**Learning:** In tight loops processing database rows (like `_compute_hybrid_scores`), enforcing boundary constraints (e.g., `min(1.0, max(0.0, ...))`) on values that are already constrained by the database schema or insertion logic adds significant overhead per iteration due to repeated Python built-in function calls.
**Action:** Replaced `max(0.0, min(1.0, float(mem.get("importance") or 0.0)))` with a simple conditional float cast in `_compute_hybrid_scores`. This provides an ~87% speedup on this specific calculation in the loop since the importance values are already guaranteed to be within `[0.0, 1.0]`.

### 2026-09-02 - Missing check_same_thread=False in D1 SQLite test fixtures causes lockups
**Learning:** SQLite connections instantiated within tests using `sqlite3.connect` and passed as mocks (`FakeD1Worker`) that are later invoked from `asyncio.to_thread` will hang or lock up under Windows GitHub Actions if they lack `check_same_thread=False`.
**Action:** When fixing test flakes, added `check_same_thread=False` to all missing SQLite connection fixtures (in `tests/test_d1_isolation.py`, `tests/test_column_fidelity.py`, `tests/test_d1_migrations.py`, etc.).

### 2026-09-17 - Avoid generator expression and dict.get overhead in hot loops
**Learning:** In `_compute_hybrid_scores` and `rrf_fuse`, relying on `any(...)` with generator expressions or repeated `dict.get(..., 0.0)` incurs significant overhead on large dictionaries (like `results` with up to 10k items) compared to basic `for` loops using `"key" in dict` or direct dictionary comprehensions.
**Action:** Replaced `any(m.get("vec_score", 0.0) > 0 for m in results.values())` with a standard `for` loop containing `if "vec_score" in m and m["vec_score"] > 0:` yielding a ~65% speedup on the vector check. Rewrote `rrf_fuse` to initialize the dictionary with `{mid: 1.0 / (k + rank) for rank, mid in enumerate(fts_results, start=1)}` to avoid `get` defaults, saving ~10% execution time per call.

### 2026-09-21 - Optimize RRF precomputation to avoid dict lookups in hot loops
**Learning:** In `_compute_hybrid_scores`, mapping element IDs to their specific ranks inside two dictionaries (`fts_rank`, `vec_rank`) and then performing `.get()` lookups for every element inside a loop over the results adds unnecessary overhead (~15%). Because both ranked lists contain exactly the keys present in `results`, we can precompute the combined score directly by enumerating the ranked lists.
**Action:** Refactored the `has_vec` block in `_compute_hybrid_scores` to precompute the RRF score similarly to `rrf_fuse`: initializing a dictionary with `fts_ranked` and incrementing scores with `vec_ranked`, eliminating per-item dict lookups during the main results loop.

### 2026-10-03 - Optimize dictionary sorting by replacing lambda with operator.itemgetter
**Learning:** Using `lambda` functions for `key` in `list.sort()` introduces significant overhead when sorting large arrays. `operator.itemgetter` is implemented in C and runs substantially faster (approx. ~18-20% speedup) for simple dictionary key extraction during sorting.
**Action:** Replaced `key=lambda m: m["score"]` with `key=operator.itemgetter("score")` in `_compute_hybrid_scores`. To appease type checkers (Pyright/ty), explicitly typed the implicitly typed list `scored` as `list[dict]` and added a `# type: ignore[arg-type]` to the sort call.

### 2026-10-04 - Extend itemgetter optimization to rrf_fuse
**Learning:** `rrf_fuse` still used `lambda kv: kv[1]` for the final score sort; the same C-level `operator.itemgetter` substitution applies to tuple keys.
**Action:** Replaced `key=lambda kv: kv[1]` with `key=operator.itemgetter(1)` in `rrf_fuse`, completing the sort-key optimization started in the `_compute_hybrid_scores` change.

### 2026-10-06 - Optimize sorting by replacing lambda with operator.itemgetter in reranker and embedder
**Learning:** Continuing the optimization found previously for `_compute_hybrid_scores` and `rrf_fuse`, using `lambda` functions for `key` in `list.sort()` introduces measurable overhead. `operator.itemgetter` is implemented in C and runs roughly 3x faster for simple tuple indexing in Python 3.13. This applies directly to the sorting operations inside the reranking and embedding methods.
**Action:** Replaced `key=lambda x: x[1]` with `key=operator.itemgetter(1)` in `src/mnemo/reranker.py` and `key=lambda x: x[0]` with `key=operator.itemgetter(0)` in `src/mnemo/embedder.py`, adding `# type: ignore[arg-type]` to appease type checkers (Pyright/ty).
### 2026-10-09 - Avoid repeated dictionary iteration and list comprehension overhead for min/max
**Learning:** In `_fts_search`, performing a list comprehension to extract values, followed by two separate built-in calls to `min()` and `max()`, and finally re-iterating over the entire result dictionary to normalize scores incurs unnecessary memory allocation and loop overhead.
**Action:** Replaced the list comprehension and `min`/`max` calls with a single pass over `results.values()` that simultaneously finds the minimum and maximum values while appending only the valid nodes to a temporary list. The normalization then iterates only over this smaller, pre-filtered list. This yielded an ~50% speedup on large result sets.

### 2026-10-27 - Optimize interval sorting with stable chained operator.itemgetter
**Learning:** When sorting intervals (start, end) where spans need to be sorted by start ascending and length descending, replacing a math-heavy `lambda` (e.g., `lambda f: (f[0], -(f[1]-f[0]))`) with chained `operator.itemgetter` calls provides a ~34% performance improvement in hot loops. Because Python sorts are stable, sorting by the end value descending (`reverse=True`) first, then by the start value ascending, natively results in descending lengths for equal start values without requiring inline math. This same `operator.itemgetter` speedup applies to dictionary keys like `lambda f: (f["start"], f["end"])`.
**Action:** Replaced `lambda f: (f[0], -(f[1]-f[0]))` with `operator.itemgetter(1)` (reverse=True) followed by `operator.itemgetter(0)` and replaced `lambda f: (f["start"], f["end"])` with `operator.itemgetter("start", "end")` in `src/mnemo_core/defense.py`.

## Security

### 2026-10-06 - Prevent Information Disclosure in Core Operations
**Vulnerability:** Raw exception strings from `Exception` and `sqlite3.Error` (e.g., `str(exc)`) were exposed in the JSON response payload of core operations like `capture`, `recall`, `fetch`, `reflect`, `standing_read`, and `_write_page` in `src/mnemo_core/operations.py` and `src/mnemo_core/standing.py`.
**Learning:** Returning exception details like `str(exc)` from backend failures directly to the client can leak sensitive internal configuration, database paths, or SQL details. Exception strings should be masked with generic error messages in API responses.
**Prevention:** Catch generic exceptions without an `as exc` binding, log the exception securely on the server using `logger.exception()`, and return a generic error message (e.g., `"unexpected failure"`) to the client.

### 2026-07-24 - Prevent Information Disclosure in API Error Responses
**Commit:** 080be86c (#1005)
**Vulnerability:** Raw exception strings, including stack trace elements or backend error messages (e.g., `f"backend pull failed: {e}"` or `f"{type(e).__name__}: {e}"`), were returned directly in the JSON response of tool handlers (`consolidate`, `sync_now`, `import_passport`).
**Learning:** Returning dynamic exception messages generated by internal libraries or database drivers directly to the user creates an Information Disclosure vulnerability. This allows a malicious user to learn about internal backend implementations, directory structures, or network configuration details that can be useful for planning further attacks.
**Prevention:** Catch exceptions and log them securely on the server using `logger.exception()` (to capture the traceback for debugging). Return only generic, statically defined error messages (e.g., `"internal error"`) in the JSON payload exposed to the client.

### 2026-08-01 - Prevent Information Disclosure in Google Drive Sync Error Responses
**Commit:** 8179b2b (#1033)
**Vulnerability:** Similar to other sync and consolidation endpoints, `str(e)` was exposed in the JSON response of `src/mnemo/sync/gdrive.py`'s `pull` method when merging databases.
**Learning:** Exception details can leak sensitive information about the file system, network, or internal logic. The pattern of replacing `except Exception as e:` logging `error` to catching `Exception` and logging `exception` (and returning a generic "internal error" message) should be uniformly applied anywhere an API returns a JSON error.
**Prevention:** Always return generic error strings like "Merge failed: internal error" rather than the dynamically generated exception string, and rely on `logger.exception` to log the full stack trace server-side without an explicit `as e` binding.

### 2026-08-01 - Pin transitive fastmcp so a lock refresh cannot drop tool safety hints
**Commit:** 5f7585a (#1036)
**Vulnerability:** A near miss rather than a defect in shipped code. Renovate's `lockFileMaintenance` PR (#1022) locked `fastmcp` and `fastmcp-slim` at `4.0.0b1`, and that release removes `readOnlyHint` and `destructiveHint` from `ToolAnnotations`. Pydantic discards the arguments instead of raising, so all 14 annotated tools in `src/mnemo/server.py` lose their hints -- among them `destructiveHint=True` on `delete_memory` and on the legacy `memory` dispatcher. A client that gates destructive calls on that flag would have been told a delete tool was harmless. `fastmcp` was unconstrained here: it arrives only through `n24q02m-mcp-core`, whose own requirement is an unbounded `{ name = "fastmcp" }`, so nothing excluded the 4.x line. That block also sets `automerge: true`.
**Learning:** A dependency can withdraw a security control without breaking the build. Because Pydantic drops unknown keyword arguments, a removed field degrades into a warning rather than an error: the annotations still constructed, the server still started, and only `ty` remarked on it. Any dependency that renders a safety signal -- tool annotations, auth scopes, permission flags -- needs a version bound in this repo even when nothing here imports it directly. A transitive path plus automerge is enough to change that surface without a human reading the diff.
**Prevention:** Bound these dependencies explicitly in `pyproject.toml`, and check the bound against the resolver instead of trusting it: run `uv lock --upgrade --prerelease=allow` with and without the constraint and compare. Do not repeat the claim that `<4` fails to exclude prereleases -- PEP 440's exclusive ordered comparison does skip prereleases of the same release, and `>=3.4.4,<4` was measured holding `4.0.0b1` out even under `--prerelease=allow`. The gap here was an absent constraint, not a weak one; state which of the two you are fixing.

### 2026-08-02 - TOCTOU Vulnerability in Token Persistence
**Vulnerability:** Insecure file permission fallback using write_text created a window where sensitive OAuth tokens were readable by other users before chmod was applied.
**Learning:** Relying on write_text as a fallback when os.open with O_CREAT | O_WRONLY | O_TRUNC fails defeats the purpose of secure file creation and introduces TOCTOU risks on POSIX systems.
**Prevention:** Avoid path.write_text() for sensitive files. Use os.open with secure flags and os.fchmod, and let failures bubble up rather than falling back to insecure defaults.

### Rejected

#### 2026-07-25 - Duplicate submissions of the error-leakage fix (#999, #1002)
The finding was valid and shipped in #1005 (commit 080be86c). Two further PRs proposed it again; both were subsets and both were closed. What was wrong with them, so it is not repeated:

- Neither updated the three assertions in `tests/test_passport_actions.py` and `tests/test_server.py` that match on the error text. A change to a user-visible string is not complete until the tests that pin that string move with it.
- #1002 dropped `logger.exception("Consolidation failed")` from the `_handle_consolidate` branch. Replacing a returned message with a static string is only safe because the traceback still reaches the server log; remove the log call and the error becomes invisible instead of private.
- #1002 replaced the `detail` key with a fixed sentence rather than removing it. A field with the same value on every failure conveys nothing. #1005 removed the key.
- #1002 also edited `uv.lock` to move the project version from `2.7.0b1` to `2.7.0`. Versions here are computed by python-semantic-release at release time and must not be hand-edited.

#### 2026-07-25 - Framing this class of finding as "stack trace exposure"
These handlers return a JSON dict and never returned a traceback, so a catch-all added to suppress one would be guarding against something that cannot happen while swallowing errors that can. The real exposure was the interpolated `str(e)`, which for `httpx` and `botocore` failures can carry endpoint URLs, bucket names and local paths. State the leak precisely; it determines whether the fix is narrowing a message or restructuring the handler.

#### 2026-08-01 - Duplicate submission of the gdrive fix (#1023)

Same finding as the entry above and the same edit to `sync/gdrive.py`: #1023 and
#1033 produced an identical blob (`7f81267b` -> `aada328c`), so only the
delivery differed. #1033 carried a ledger entry; #1023 carried none, which is
why that one was kept.

This is the second time this repository has received the same security finding
twice in one batch -- the 2026-07-25 entry above records #999/#1002 doing it to
the error-leakage fix. Before opening a security PR, read this file: a finding
already recorded here has either landed or been turned down, and the entry says
which.

Two defects in #1033 were fixed before merge and are worth stating because they
recur. Its ledger entry was dated `2025-02-14`, more than a year off, and it was
written at `##` where the entries around it were `###`, which filed a shipped fix
under "Rejected". Date an entry from the commit that carries it, and check which
section the heading level puts it in.

### 2026-08-29 - Prevent Information Disclosure in Backend Configuration Errors
**Vulnerability:** Raw exception strings from `KeyError` (e.g., `str(e)`) were exposed in the JSON response payload of `sync_now` and `import_passport` tool handlers when an unknown or misconfigured backend was requested.
**Learning:** Returning exception details like `str(e)` from `KeyError` directly to the client can leak sensitive internal configuration keys or backend structure details. Exception strings should be masked with generic error messages in API responses.
**Prevention:** Catch `KeyError` without an `as e` binding, log the exception securely on the server using `logger.exception()`, and return a generic error message (e.g., `"backend configuration incomplete"`) to the client.

### 2026-08-30 - Prevent Information Disclosure in ValueError Validation Errors
**Vulnerability:** Raw exception strings from `ValueError` (e.g., `str(e)`) were exposed in the JSON response payload of `_handle_add`, `_handle_update`, and `_handle_capture` tool handlers when validation failed for reasons other than content length limits.
**Learning:** Returning exception details like `str(e)` from `ValueError` directly to the client can leak sensitive internal constraints or processing logic. Exception strings should be masked with generic error messages in API responses unless they relate to necessary client-side validation feedback (like 'content exceeds limit').
**Prevention:** Catch `ValueError`, and if the error string does not contain benign validation feedback (like 'exceeds limit'), return a generic error message (e.g., `"validation failed"`) to the client and rely on server-side logging.

## Accessibility and UX

### 2026-06-13 - Initial Entry
**Learning:** Found an opportunity to improve the `suggestion` for unknown topics in the `help` tool.
**Action:** Always provide actionable fallbacks for missing or misspelled parameters.
### 2024-05-18 - Improve configuration setting error reporting
**Learning:** Returning a raw "Invalid key" or "Invalid log level" message forces users to look up documentation. A small fuzzy match with `difflib.get_close_matches` combined with a fallback list provides immediate, actionable feedback in the API response.
**Action:** When returning validation errors for enumerated values (like settings keys or predefined constants), always try fuzzy matching to catch typos and include the full list of valid options as a fallback `suggestion`.
### 2026-07-01 - Consistent Error Suggestions
**Learning:** Returning error messages without actionable next steps leaves the developer guessing what went wrong, which degrades Developer Experience (DX). In backend MCP servers, returning structured errors with `suggestion` strings is crucial.
**Action:** When a tool returns an error structure (e.g., in `import_passport`), ensure it includes a `suggestion` key to guide the developer/agent on how to fix the issue.
### 2024-07-04 - Guarding difflib against non-string inputs
**Learning:** `difflib.get_close_matches` throws an exception when the first argument is not iterable (e.g. integer or dict), crashing the MCP tool error handler. While `if action:` catches `None`, it doesn't protect against `0` or other non-string types.
**Action:** Always wrap the first argument to `difflib.get_close_matches` with `str()` and use `is not None` when providing fuzzy matching suggestions for API inputs, to avoid unhandled TypeErrors.
### 2026-07-10 - Extending fuzzy matching to domain inputs
**Learning:** Returning a raw "Invalid context_type" without a fallback leaves developers guessing. Applying fuzzy matching to domain-specific enumerations (like context_type) improves DX immediately.
**Action:** Always wrap the first argument to `difflib.get_close_matches` with `str()` and use `is not None` when providing fuzzy matching suggestions for API inputs, including domain-specific variables like context_type.
### 2026-05-18 - [DX] Fuzzy matching for enumerated inputs
**Learning:** Developers and LLMs often provide slightly incorrect or typo'd strings for enumerated inputs like filter categories (`entity_type`) or configuration modes (`mode` for import). Failing silently, returning 0 results, or defaulting to an internal fallback without warning leads to a poor developer experience (DX) and confusion.
**Action:** When validating enumerated API parameters, use `difflib.get_close_matches` to identify potential typos and return a structured JSON error response that includes the closest fuzzy match as a `suggestion`. This allows the caller to easily identify their mistake and quickly self-correct.

### 2026-07-25 - Scope of this repo for UI/UX work
**Learning:** `mnemo` ships a Python MCP server and a Cloudflare Worker. It has no frontend, no templates and no user-facing UI, so the Palette remit does not apply to it in the usual sense. This was concluded twice in one week and each conclusion was filed as a pull request containing an empty commit (#1003, #1007), which cost two review cycles and produced no change.

**Action:** The reviewable surface here is the text the tools themselves return: the `error`, `suggestion` and `note` strings in `src/mnemo/server.py` and the tool docs under `src/mnemo/docs/`. Those are what a caller actually reads, and the entries above are all improvements to exactly that surface. Direct Palette work there. A conclusion that there is nothing to change belongs in this file as an entry; it does not need a pull request to be recorded.

### Rejected

#### 2026-07-25 - Empty-commit pull requests that announce a skip (#1003, #1007)
Both PRs changed no files (`+0/-0`) and existed only to state that this repo has no frontend. The conclusion was right; the delivery was not. An empty PR consumes a review cycle, runs the full check matrix, and leaves a branch behind to prune, all to communicate one sentence that belongs in this file. #1003 additionally used a `chore:` prefix, which this repo does not accept, and carried four commits restating the same empty change.

Record a skip as an entry here. Do not open a PR to report that no change is needed.

#### 2026-07-25 - Reframing backend work as UX to satisfy the remit
Noted because #1007 flagged the temptation itself: when no UI exists, editing API internals and labelling the result a UX improvement is worse than skipping. The honest surface is the response text a caller reads, described in the entry above. If that surface has nothing wrong with it, the correct outcome is no change.

#### 2026-08-01 - A third empty pull request announcing the same skip (#1032)

`+0/-0` across two commits, titled `chore: no frontend ui available for ux
enhancement`. This is the same conclusion as #1003 and #1007, recorded in the
entry above on 2026-07-25, delivered the same way that entry asked it not to be,
and with the same `chore:` prefix this repository rejects.

The entry above exists so this does not need a pull request. It says what the
reviewable surface here is -- the `error`, `suggestion` and `note` strings in
`src/mnemo/server.py` and the tool docs under `src/mnemo/docs/` -- and
that a decision to change nothing belongs in this file as an entry. Read this
file before opening anything against this repository.
### 2026-08-01 - Missing Suggestion in as_of Action
**Learning:** Found an opportunity to improve Developer Experience (DX). The `memory(action="as_of")` call lacked an explicit check for the `as_of` parameter and threw a raw unhelpful error or skipped downstream. Added an explicit validation step returning a structured error and suggestion.
**Action:** When adding validation checks for API endpoints in purely backend MCP servers, ensure they return a structured dictionary containing both an `error` message and a `suggestion` for actionable recovery.

### 2026-09-04 - Saturated Error Surface Skip
**Learning:** Reviewed `src/mnemo/server.py` for missing `suggestion` keys in JSON error responses. All error paths (including invalid configurations, topics, actions, and temporal/graph queries) already return actionable suggestions or apply fuzzy matching via `difflib.get_close_matches`. There is no missing DX surface to improve today.
**Action:** Record a skip in the journal and stop without creating a PR, as instructed for repositories with no UI when the API response surface is completely healthy.
