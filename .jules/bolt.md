## 2026-07-07 - Optimize JSON payload serialization
**Learning:** Returning large JSON lists of objects (like search or list results) with `indent=2` adds significant byte overhead due to unnecessary whitespace and newlines, hurting serialization performance and increasing network latency/token cost.
**Action:** Replaced `json.dumps(obj, indent=2)` with `json.dumps(obj, separators=(",", ":"))` in `_json` helper to eliminate all unnecessary whitespace from MCP tool responses while preserving schema compatibility.
