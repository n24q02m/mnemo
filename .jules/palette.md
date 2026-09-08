## 2026-06-13 - Initial Entry
**Learning:** Found an opportunity to improve the `suggestion` for unknown topics in the `help` tool.
**Action:** Always provide actionable fallbacks for missing or misspelled parameters.
## 2024-05-18 - Improve configuration setting error reporting
**Learning:** Returning a raw "Invalid key" or "Invalid log level" message forces users to look up documentation. A small fuzzy match with `difflib.get_close_matches` combined with a fallback list provides immediate, actionable feedback in the API response.
**Action:** When returning validation errors for enumerated values (like settings keys or predefined constants), always try fuzzy matching to catch typos and include the full list of valid options as a fallback `suggestion`.
## 2026-07-01 - Consistent Error Suggestions
**Learning:** Returning error messages without actionable next steps leaves the developer guessing what went wrong, which degrades Developer Experience (DX). In backend MCP servers, returning structured errors with `suggestion` strings is crucial.
**Action:** When a tool returns an error structure (e.g., in `import_passport`), ensure it includes a `suggestion` key to guide the developer/agent on how to fix the issue.
## 2024-07-04 - Guarding difflib against non-string inputs
**Learning:** `difflib.get_close_matches` throws an exception when the first argument is not iterable (e.g. integer or dict), crashing the MCP tool error handler. While `if action:` catches `None`, it doesn't protect against `0` or other non-string types.
**Action:** Always wrap the first argument to `difflib.get_close_matches` with `str()` and use `is not None` when providing fuzzy matching suggestions for API inputs, to avoid unhandled TypeErrors.
## 2026-07-10 - Extending fuzzy matching to domain inputs
**Learning:** Returning a raw "Invalid context_type" without a fallback leaves developers guessing. Applying fuzzy matching to domain-specific enumerations (like context_type) improves DX immediately.
**Action:** Always wrap the first argument to `difflib.get_close_matches` with `str()` and use `is not None` when providing fuzzy matching suggestions for API inputs, including domain-specific variables like context_type.
## 2026-05-18 - [DX] Fuzzy matching for enumerated inputs
**Learning:** Developers and LLMs often provide slightly incorrect or typo'd strings for enumerated inputs like filter categories (`entity_type`) or configuration modes (`mode` for import). Failing silently, returning 0 results, or defaulting to an internal fallback without warning leads to a poor developer experience (DX) and confusion.
**Action:** When validating enumerated API parameters, use `difflib.get_close_matches` to identify potential typos and return a structured JSON error response that includes the closest fuzzy match as a `suggestion`. This allows the caller to easily identify their mistake and quickly self-correct.

## 2026-07-25 - Scope of this repo for UI/UX work
**Learning:** `mnemo-mcp` ships a Python MCP server and a Cloudflare Worker. It has no frontend, no templates and no user-facing UI, so the Palette remit does not apply to it in the usual sense. This was concluded twice in one week and each conclusion was filed as a pull request containing an empty commit (#1003, #1007), which cost two review cycles and produced no change.

**Action:** The reviewable surface here is the text the tools themselves return: the `error`, `suggestion` and `note` strings in `src/mnemo_mcp/server.py` and the tool docs under `src/mnemo_mcp/docs/`. Those are what a caller actually reads, and the entries above are all improvements to exactly that surface. Direct Palette work there. A conclusion that there is nothing to change belongs in this file as an entry; it does not need a pull request to be recorded.

## Rejected

### 2026-07-25 - Empty-commit pull requests that announce a skip (#1003, #1007)
Both PRs changed no files (`+0/-0`) and existed only to state that this repo has no frontend. The conclusion was right; the delivery was not. An empty PR consumes a review cycle, runs the full check matrix, and leaves a branch behind to prune, all to communicate one sentence that belongs in this file. #1003 additionally used a `chore:` prefix, which this repo does not accept, and carried four commits restating the same empty change.

Record a skip as an entry here. Do not open a PR to report that no change is needed.

### 2026-07-25 - Reframing backend work as UX to satisfy the remit
Noted because #1007 flagged the temptation itself: when no UI exists, editing API internals and labelling the result a UX improvement is worse than skipping. The honest surface is the response text a caller reads, described in the entry above. If that surface has nothing wrong with it, the correct outcome is no change.

### 2026-08-01 - A third empty pull request announcing the same skip (#1032)

`+0/-0` across two commits, titled `chore: no frontend ui available for ux
enhancement`. This is the same conclusion as #1003 and #1007, recorded in the
entry above on 2026-07-25, delivered the same way that entry asked it not to be,
and with the same `chore:` prefix this repository rejects.

The entry above exists so this does not need a pull request. It says what the
reviewable surface here is -- the `error`, `suggestion` and `note` strings in
`src/mnemo_mcp/server.py` and the tool docs under `src/mnemo_mcp/docs/` -- and
that a decision to change nothing belongs in this file as an entry. Read this
file before opening anything against this repository.
## 2026-08-01 - Missing Suggestion in as_of Action
**Learning:** Found an opportunity to improve Developer Experience (DX). The `memory(action="as_of")` call lacked an explicit check for the `as_of` parameter and threw a raw unhelpful error or skipped downstream. Added an explicit validation step returning a structured error and suggestion.
**Action:** When adding validation checks for API endpoints in purely backend MCP servers, ensure they return a structured dictionary containing both an `error` message and a `suggestion` for actionable recovery.
