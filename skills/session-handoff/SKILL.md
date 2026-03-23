---
name: session-handoff
description: End-of-session knowledge capture — decisions, preferences, corrections, conventions, open questions
argument-hint: "[session topic or project name]"
---

# Session Handoff

Structured end-of-session capture that ensures the NEXT session starts with full context. Enforces "WHY not just WHAT" — every memory must include the reasoning, not just the fact.

## Checklist (go through ALL categories)

Before storing anything, review the conversation for each category:

1. **Decisions made**: Technical choices, architecture decisions, tool selections
   - BAD: "Using PostgreSQL"
   - GOOD: "Using PostgreSQL over SQLite because we need concurrent writes from multiple workers and the data exceeds 10GB"

2. **Preferences expressed**: User's workflow preferences, style choices, communication preferences
   - BAD: "Prefers short commits"
   - GOOD: "Prefers atomic commits (one logical change per commit) because they review PRs commit-by-commit and need clean bisect history"

3. **Corrections given**: Things the user corrected — these are HIGH PRIORITY (prevents repeat mistakes)
   - BAD: "Don't use fmt.Println"
   - GOOD: "Corrected: use log.Printf not fmt.Println in Go services because stdout is not captured by the log aggregator (Alloy)"

4. **Conventions established**: Naming patterns, file organization, coding standards
   - BAD: "Use snake_case"
   - GOOD: "Convention: snake_case for Python files and functions, but PascalCase for Pydantic models. Established because the codebase mixes both and this was the cleanup decision"

5. **Open questions**: Unresolved items that need future attention
   - Store these explicitly so the next session can address them
   - Include what was already tried or considered

## Storage Process

For each item identified above:

1. **Store with context** using `memory(action="add", ...)`:
   - Content MUST include WHY, not just WHAT
   - Tag with category: `decision`, `preference`, `correction`, `convention`, `open-question`
   - Tag with project name for scoped retrieval
   - Include date context if time-sensitive

2. **Verify retrieval** (mandatory — do NOT skip):
   - `memory(action="search", query="[natural terms someone would use to find this]")`
   - If the memory does not appear in top results, either:
     - Rewrite content with better keywords
     - Add more specific tags
   - A memory that cannot be found is worthless

3. **Produce handoff summary** for the user:
   ```
   ## Session Handoff — [date]

   ### Stored
   - [N] decisions, [N] preferences, [N] corrections, [N] conventions

   ### Open Questions (carried forward)
   - [list unresolved items]

   ### Key Context for Next Session
   - [1-3 sentence summary of where things stand]
   ```

## Quality Rules

- **WHY not WHAT**: Every memory must answer "why was this decided/preferred/corrected?"
- **Specific over generic**: "Use Polars for dataframes" is useless without "because pandas is banned per project rules and Polars handles our 50M row dataset in 2s vs 45s"
- **One insight per memory**: Do not cram multiple unrelated facts into one entry
- **Verify or discard**: If retrieval verification fails after 2 rewrites, the content is too vague to be useful
- **No ephemeral facts**: Do not store things that will be outdated next session (e.g., "currently on line 42 of file X")

## When to Use

- End of any productive session (before the conversation closes)
- When explicitly asked to "remember this" or "save for next time"
- After debugging sessions — capture root cause and fix
- After architecture or design discussions with decisions
