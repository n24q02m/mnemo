---
name: temporal-query
description: Answer time-travel questions over stored memory — what was believed at a past point in time, when a belief changed, and what replaced it. Use when the user says "as of", "back in", "at the time", "history of", "timeline", "what did I think then", or asks why a current memory contradicts an older one.
argument-hint: "[topic] [as-of timestamp or 'timeline']"
---

# Temporal Query

Point-in-time and version-chain lookups over the bitemporal columns
(`valid_from`, `valid_to`, `superseded_by`) that `mem_003_temporal` added
to `memories`. Ordinary search cannot answer these questions: `search`,
`list`, `stats` and single-id lookups all filter `valid_to IS NULL`, so
they only ever see the current state.

## What the temporal columns actually mean

Read this before phrasing an answer — getting the axis wrong produces
confident but false claims.

- `valid_from` / `valid_to` track **when the store recorded a version**,
  not when the fact was true in the outside world. `as_of=T` answers
  *"what did this memory store hold at T"*, not *"what was true at T"*.
  If the user recorded a 2024 decision yesterday, it enters the timeline
  yesterday.
- `update` does **not** edit in place. It closes the old row
  (`valid_to = <update time>`, `superseded_by = <new id>`) and inserts a
  new row with a **new id** and `valid_from = <update time>`. The id in
  the user's notes from last month no longer resolves through `search`.
- `delete` also closes the row (`valid_to` set) but leaves
  `superseded_by = NULL`. That is the discriminator: a closed row with a
  forward pointer was **replaced**; without one it was **retracted**.
- Rows created by `add` / `capture` carry `valid_from = NULL`; queries
  fall back to `created_at` via `COALESCE`. A `null` `valid_from` in a
  result means "original version", not a data defect.
- `commit_sha` is present in the schema but is not populated by the
  current write paths. Do not present it as provenance.

## Steps

1. **Resolve the temporal anchor** from the user's wording into a single
   UTC ISO timestamp: "last month" -> first day of that month,
   "before the migration" -> the timestamp of the migration memory,
   "at the time we chose X" -> the `created_at` of the decision memory.
   State the resolved timestamp in the answer so the user can correct it.

2. **Take the point-in-time snapshot**:
   ```
   memory(action="as_of", as_of="2026-06-01T00:00:00+00:00", limit=50)
   ```
   Returns rows satisfying
   `valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of)`,
   newest first. `as_of` accepts no query filter, so raise `limit`
   (max 100) and filter by topic yourself over the returned content.
   Omitting `as_of` returns the current state instead.

3. **Trace the version chain** for any row that matters. Each closed row
   carries `valid_to` (when the belief changed) and `superseded_by` (the
   id that replaced it). Follow the pointer forward by snapshotting just
   after that timestamp and matching the id:
   ```
   memory(action="as_of", as_of="<valid_to of the old row>", limit=50)
   ```
   Repeat until you reach a row with `valid_to = null` — that is the
   surviving belief.

4. **Use the entity timeline when the knowledge graph is populated**.
   `history` takes an entity id, and only `entity_graph` returns entity
   ids (`entity_search` returns memories with a `matched_entity` name,
   not the id):
   ```
   memory(action="entity_graph", name="FastAPI", depth=1, limit=20)
   memory(action="history", entity_id="<nodes[].id from the call above>")
   ```
   `history` returns every version ever linked to that entity, including
   closed ones, ordered oldest-first. It takes no `limit`.

5. **Fall back cleanly when the graph is empty.** Entity extraction runs
   as a background task and needs a configured LLM provider; without one
   `entity_search` / `entity_graph` / `history` return empty results even
   though the memories exist. In that case answer from steps 2-3 alone
   and say the timeline is reconstructed from version history rather than
   entity links.

## Query recipes

| Question | Call |
| --- | --- |
| "What did I believe about X last month?" | `as_of` at that date, `limit=50`, filter results for X |
| "When did this change, and what replaced it?" | read `valid_to` + `superseded_by` on the closed row, then step 3 |
| "What did I know when I decided Y?" | `search` for the decision -> take its `created_at` -> `as_of` at that timestamp |
| "Show the full timeline of X" | `entity_graph(name="X")` -> `history(entity_id=...)` |
| "Was this deleted or replaced?" | `superseded_by` non-null -> replaced; null -> retracted |

## Output template

```
## As of <resolved UTC timestamp>

**Then**: <content of the version valid at that time>  (id <old-id>)
**Changed**: <valid_to>  ->  superseded by id <new-id>
**Now**: <content of the surviving version>  (id <new-id>, valid_to null)

<one sentence on what the change means for the question asked>
```

If the snapshot is empty, say so plainly and give the earliest timestamp
that does return rows — do not present a current-state answer as history.

## Quality rules

- **Always pass UTC.** Timestamp comparison is lexicographic over ISO
  strings, so an equivalent instant written with a different offset gives
  wrong results: `2026-07-25T17:40:04+07:00` returns nothing where
  `2026-07-25T10:40:04+00:00` returns the row. Convert to `+00:00`
  before querying.
- **`as_of` pairs only with `action="as_of"`.** Passing it alongside
  `search` or `list` is rejected with an explicit error rather than
  silently returning current-state results; do not retry by dropping the
  parameter and presenting the answer as historical.
- **Never claim a fact was true at T** — only that it was recorded at T.
- **Quote both ids** when reporting a change. The user's older notes
  reference the pre-update id, which no longer resolves through search.
- **Know which action hides what.** `as_of` excludes archived rows on top
  of the validity window; `history` deliberately does not filter archived
  rows, because a retired memory is still part of the timeline;
  `entity_search` returns current rows only and is therefore the wrong
  tool for a timeline. Hand-written SQL over `memories` reproduces none
  of these filters — use the actions.

## When to Use

- The user asks what they thought, decided, or knew at an earlier time.
- A current memory contradicts something the user remembers storing, and
  the question is when it changed.
- Auditing why a past decision looked correct given what was known then.
- Before overwriting a long-lived memory, to show the user the chain they
  are about to extend.
