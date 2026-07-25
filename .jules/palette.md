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
