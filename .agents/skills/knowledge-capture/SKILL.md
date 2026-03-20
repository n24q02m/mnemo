---
name: knowledge-capture
description: Structured memory capture workflow — identify key insights, categorize, store with tags, verify retrieval
argument-hint: "[topic or context]"
---

# Knowledge Capture

Structured workflow for capturing and organizing knowledge into persistent memory.

## Steps

1. **Identify key insights** from the current conversation or context:
   - What decisions were made and why?
   - What preferences or corrections did the user express?
   - What project conventions or patterns were established?
   - What external references or resources were mentioned?

2. **Categorize each insight**:
   - `preference` — User preferences, workflow choices
   - `decision` — Technical decisions with rationale
   - `convention` — Project patterns, naming, architecture rules
   - `reference` — External URLs, tools, documentation
   - `correction` — Things the user corrected (important for avoiding repeat mistakes)

3. **Store using mnemo-mcp** memory tool:
   - `memory(action="add", content="...", metadata={"tags": ["category", "project"], "source": "conversation"})`
   - Include context: WHY this matters, not just WHAT it is
   - Tag appropriately for future retrieval

4. **Verify retrieval**:
   - `memory(action="search", query="[key terms from what was just stored]")`
   - Confirm the memory is retrievable with natural search terms
   - If not found, adjust tags or content for better discoverability

5. **Report** what was captured to the user for confirmation.

## When to Use

- End of a productive session with decisions made
- When user explicitly says "remember this"
- After debugging sessions (capture the root cause and fix)
- When project conventions are established or changed
