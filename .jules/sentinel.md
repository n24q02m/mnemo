## 2025-03-09 - Protect against malformed JSON in `json_each` DoS
**Vulnerability:** Unvalidated JSON strings inserted into SQLite columns queried with `json_each()` will cause a query-crashing exception (`malformed JSON`), creating a potential Denial-of-Service vulnerability.
**Learning:** `json_each` raises exceptions when passed malformed JSON. This is an issue when filtering is done directly via SQL queries.
**Prevention:** Guard `json_each()` calls with `json_valid()` (e.g., `json_valid(column) AND EXISTS(SELECT 1 FROM json_each(column)...)`).
