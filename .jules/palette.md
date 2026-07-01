## YYYY-MM-DD - Initial Entry
**Learning:** Found an opportunity to improve the `suggestion` for unknown topics in the `help` tool.
**Action:** Always provide actionable fallbacks for missing or misspelled parameters.
## 2024-05-18 - Improve configuration setting error reporting
**Learning:** Returning a raw "Invalid key" or "Invalid log level" message forces users to look up documentation. A small fuzzy match with `difflib.get_close_matches` combined with a fallback list provides immediate, actionable feedback in the API response.
**Action:** When returning validation errors for enumerated values (like settings keys or predefined constants), always try fuzzy matching to catch typos and include the full list of valid options as a fallback `suggestion`.
## $(date +%Y-%m-%d) - Consistent Error Suggestions
**Learning:** Returning error messages without actionable next steps leaves the developer guessing what went wrong, which degrades Developer Experience (DX). In backend MCP servers, returning structured errors with `suggestion` strings is crucial.
**Action:** When a tool returns an error structure (e.g., in `import_passport`), ensure it includes a `suggestion` key to guide the developer/agent on how to fix the issue.
