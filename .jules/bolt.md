## 2024-05-24 - SQLite json_object vs Python json.dumps
**Learning:** For database exports, offloading JSON construction to SQLite via `json_object()` and `json()` is significantly faster (~78% improvement) than fetching rows, converting to dictionaries, and running `json.loads()`/`json.dumps()` row-by-row in Python.
**Action:** Always prefer database-native JSON generation (like `json_object()` in SQLite or `row_to_json()` in Postgres) over application-level serialization when the sole purpose is to format a payload for an API response or file export.
