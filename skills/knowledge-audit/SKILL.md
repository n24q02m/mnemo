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
