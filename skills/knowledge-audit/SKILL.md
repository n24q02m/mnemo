---
name: knowledge-audit
description: Review and clean up stored memories — find duplicates, contradictions, stale entries, and consolidate
argument-hint: "[topic or 'all']"
---

# Knowledge Audit

Systematic review of stored memories to maintain quality. Finds duplicates, detects contradictions, flags stale entries, and consolidates overlapping memories.

## Steps

1. **Scope the audit**:
   - If topic specified: `memory(action="search", query="[topic]")` to find all related memories
   - If "all": `memory(action="list")` to get full inventory, then `memory(action="stats")` for overview
   - Group memories by tag/category for systematic review

2. **Identify duplicates**:
   - Search for memories with similar content or overlapping keywords
   - Compare pairs that cover the same topic
   - Decision: keep the more detailed/recent one, delete the other
   - Use `memory(action="delete", id="[duplicate-id]")` for removals

3. **Detect contradictions**:
   - Look for memories that make opposing claims about the same topic
   - Examples: "Use library A" vs "Switched to library B", conflicting conventions
   - Decision tree:
     - Both have dates -> keep the newer one (it supersedes)
     - Neither has date -> ask user which is current
     - Both are valid (context-dependent) -> update both to clarify their scope
   - Update the surviving memory to note it supersedes the old one

4. **Flag stale entries**:
   - Memories referencing specific versions that are now outdated
   - Memories about temporary workarounds that may have been resolved
   - Memories about tools/libraries that have been replaced
   - Action: mark as stale with `memory(action="update", ...)` adding `[STALE]` prefix, or delete if clearly obsolete

5. **Consolidate overlapping memories**:
   - Multiple memories about the same topic that each have partial info
   - Merge into a single comprehensive memory
   - Steps: create new consolidated memory -> verify retrieval -> delete originals
   - Use `memory(action="consolidate", ...)` if available, otherwise manual merge

6. **Produce audit report**:
   ```
   ## Knowledge Audit — [topic/all] — [date]

   ### Summary
   - Total memories reviewed: [N]
   - Duplicates removed: [N]
   - Contradictions resolved: [N]
   - Stale entries flagged/removed: [N]
   - Memories consolidated: [N merged into M]

   ### Actions Taken
   - [list of specific changes]

   ### Recommendations
   - [any patterns noticed, e.g., "many memories lack WHY context"]
   ```

## Staleness Indicators

- References to specific version numbers (check if still current)
- Contains "temporary", "workaround", "until X is fixed"
- References removed/renamed files, deprecated APIs, old URLs
- Predates a major migration or refactor (check project history)
- Contains "TODO" or "will be" — was it done?

## Contradiction Resolution Rules

- **Explicit supersession**: If memory B says "switched from A to B", delete memory about using A
- **Scope difference**: "Use X for backend" and "Use Y for frontend" are NOT contradictions
- **Evolution**: "Started with X" and "Migrated to Y" — keep Y, delete X (unless X context is still relevant)
- **Ambiguous**: When unclear, DO NOT delete — ask the user

## When to Use

- Periodically (monthly or after major project changes)
- When memory search returns confusing or contradictory results
- After a major migration or architecture change
- When starting a new phase of a project
- When memory count grows large and retrieval quality degrades

## Phase 3: Temporal KG Audit (v2.0+)

Phase 3 ships a temporal knowledge graph (entities + edges + bitemporal
versioning + supersession). The audit checklist now also covers KG
hygiene:

### KG-aware audit dimensions

7. **Stale entities**: entity rows that no longer link to any active
   memory (their last `memory_entity_links` row points at an archived /
   superseded memory).
   - Detect: `memory(action="entity_search", name="<entity>")` returning
     0 currently-valid hits → candidate stale.
   - Action: confirm with the user, then delete the orphaned entity row
     (cascade removes edges).

8. **Orphan edges**: edges in `memory_edges` whose source or target
   `memory_entities` row was deleted but the edge survived.
   - Detect: server logs show "edge with missing endpoint" warnings, or
     `entity_graph` returns nodes referenced from edges that aren't in
     the nodes list.
   - Action: ask user; either re-extract the originating capture or
     hand-delete the edge by id.

9. **Contradicting / superseded chains**: a memory in a supersession
   chain still surfaces in default `memory.get` results because someone
   left `valid_to = NULL` on an old fact.
   - Detect: `memory(action="history", entity_id=<x>)` returning multiple
     rows with `valid_to = NULL` for the same entity.
   - Action: pick the most-recent / most-correct row and update
     `valid_to` on the others to the supersession timestamp.

10. **Bitemporal drift**: capture has no `valid_from` set, falls outside
    the bitemporal index. Usually a pre-Phase-3 row that was missed by
    backfill, or a manual `db.add` that bypassed the capture pipeline.
    - Detect: SQL spot check
      `SELECT COUNT(*) FROM memories WHERE valid_from IS NULL`.
    - Action: re-run the Phase 3 backfill (`MemoryDB._backfill_phase3_temporal`)
      or update the rows manually.

11. **Audit-trail integrity**: every mutation (insert / update / supersede
    / delete) should write a `memory_audit` row with `prev_state_hash`
    and `new_state_hash`. A gap in the chain (audit row absent for an
    update) signals a bug or out-of-band write.
    - Detect: `SELECT m.id FROM memories m LEFT JOIN memory_audit a
      ON a.memory_id = m.id WHERE a.id IS NULL`.
    - Action: investigate which path wrote the row; do NOT rewrite the
      audit history (preserves tamper-detection guarantees).

### When to run the temporal sub-audit

- After running the Phase 1/2 "Knowledge Audit" steps above.
- After importing a Phase 2 passport bundle (legacy schema → can leave
  bitemporal columns NULL).
- After any large `memory(action="capture", auto=True)` batch with
  `KG_AUTO_ENABLED=true` (entity resolution may need tuning).
- Before exporting a Phase 3 passport bundle (so receiver gets a clean KG).
