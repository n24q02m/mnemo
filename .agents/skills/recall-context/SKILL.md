---
name: recall-context
description: Context retrieval — search memories, filter by relevance, compose context summary
argument-hint: "[topic or question]"
---

# Recall Context

Retrieve relevant memories to build context for the current task.

## Steps

1. **Identify what context is needed**:
   - What is the current task or question?
   - What past decisions, preferences, or conventions might be relevant?

2. **Search memories** using mnemo-mcp:
   - `memory(action="search", query="[broad topic terms]")`
   - Try multiple search angles if first results are insufficient
   - Use `memory(action="search", query="[specific terms]")` to narrow down

3. **Filter by relevance**:
   - Discard memories that are outdated or no longer applicable
   - Prioritize recent memories and strong matches
   - Cross-reference multiple memories for consistency

4. **Compose context summary**:
   - Organize relevant findings by topic
   - Note any conflicts between memories (may indicate outdated info)
   - Present as actionable context for the current task

5. **Apply context** to inform the current response or action.

## When to Use

- Starting work on a project you've worked on before
- When user asks "do you remember..." or "what did we decide about..."
- Before making decisions that may contradict past preferences
- When encountering patterns that might have established conventions
