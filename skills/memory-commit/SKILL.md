---
name: memory-commit
description: Use when the user explicitly says "remember this", "save this", "ghi nho", "luu lai", "save for next time", or otherwise asks to persist the immediately preceding context. Captures with the appropriate context_type (decision, preference, fact, skill, task, conversation) so future sessions can retrieve it accurately.
argument-hint: "[context_type or auto]"
---

# Memory Commit

Manual capture of a single decision, preference, fact, skill, task, or
conversation snippet into mnemo. Enforces the "WHY not just WHAT" rule
and chooses the correct `context_type` so retrieval is precise.

## When to Use

Trigger on explicit user signals:

- "remember this", "save this", "save for next time"
- "ghi nho", "luu lai", "nho lai"
- "let's commit this to memory", "store this"
- After a deliberate decision: "we picked X because Y"
- After a stated preference: "I always want X"
- After correcting the agent: high-value capture (prevents repeat)

Do NOT trigger on incidental mentions or speculative options not yet
chosen.

## Steps

1. **Identify the content** the user wants to remember:
   - Preceding 1-3 messages (default), OR
   - A specific quoted span the user references, OR
   - The current selection if invoked via slash command

2. **Determine `context_type`** via this decision tree:

   | Signal | context_type |
   |---|---|
   | "we decided", "we picked X over Y", "going with" | `decision` |
   | "I prefer", "I always want", "default to" | `preference` |
   | "X is at version Y", env vars, API shapes, file locations | `fact` |
   | "to do X you run Y then Z", procedure, how-to | `skill` |
   | "todo", "remember to", deadline, "by Friday" | `task` |
   | none of the above (general context) | `conversation` |

   When ambiguous, ask the user one short question. Do not silently
   default to `conversation` for high-signal content.

3. **Compose the capture text** with WHY included:
   - BAD: "Use Polars"
   - GOOD: "Use Polars for dataframes (not pandas) because the codebase
     processes 50M-row datasets and Polars is 20x faster than pandas in
     our benchmark."

4. **Capture** via the typed action:
   ```
   memory(action="capture",
          text="<composed text>",
          context_type="<chosen type>",
          category="<project-name or topic>",
          tags=["<topic>", "<scope>"])
   ```

5. **Confirm to the user**:
   ```
   Saved as <context_type>. Memory ID: <id>.
   (Deduplicated against existing similar memory: <existing_id>.)  # if applicable
   ```

   If the response includes `deduplicated: true`, surface the existing
   memory ID so the user can decide whether to update it instead.

6. **Verify retrieval** for high-stakes captures (decisions, corrections):
   ```
   memory(action="search", query="<the keywords a future agent would use>", limit=3)
   ```
   If the just-captured memory does not appear in top-3 results, rewrite
   with better keywords and re-capture (delete the original first).

## Quality Rules

- **WHY not WHAT**: every captured memory must explain reasoning.
- **One insight per capture**: do not cram multiple unrelated facts into
  one entry - they will not retrieve well.
- **Specific over generic**: include version numbers, file paths,
  percentages where relevant.
- **No ephemeral state**: do not save "currently on line 42 of file X" or
  "the test is failing right now" - these will be wrong tomorrow.
- **Honor user words**: when the user dictates exact phrasing for a
  preference or decision, use their words verbatim.

## Examples

User: "Remember that we always use ruff format, not black."

```
memory(action="capture",
       text="Use ruff format (not black) for Python formatting because ruff is the project standard - faster, single-binary, and configured in pyproject.toml.",
       context_type="preference",
       category="tooling",
       tags=["python", "formatting"])
```

User: "Ghi nho: deploy len VM dung make up-<service>, khong dung docker compose truc tiep."

```
memory(action="capture",
       text="VM deployment: dung make up-<service> / make down-<service> de inject secrets tu skret SSM qua RUN macro. KHONG chay docker compose truc tiep tren VM (mat secret injection).",
       context_type="skill",
       category="deployment",
       tags=["vm", "make", "skret"])
```
