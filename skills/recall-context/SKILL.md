---
name: recall-context
description: Use at session start, before significant decisions, or when a new task references a known project to recall mnemo memories matching the current working directory, recently edited files, or topic keywords. Helps maintain continuity across sessions and avoid redoing past research.
argument-hint: "[topic or 'cwd' or 'recent']"
---

# Recall Context

Proactive memory retrieval that pulls prior context relevant to the work
about to happen. Reduces "starting from scratch" errors and prevents the
agent from re-deriving conclusions already captured in mnemo.

## When to Use

- **Session start**: load any preferences, decisions, or open questions
  tied to the current cwd / project before the user types their first
  prompt.
- **Before a significant decision**: surface prior decisions in the same
  area (e.g. database choice, lint rules, deployment target) so the agent
  does not contradict an earlier conclusion.
- **When the user names a topic**: e.g. "let's work on the auth flow" -
  pull memories tagged or describing auth before proposing a plan.
- **After a long context gap**: if the conversation referenced earlier
  decisions but the agent does not have them in working memory, recall
  them on demand.

## Steps

1. **Resolve query terms** from the trigger:
   - `cwd`: use the current working directory path + project name as the
     query (e.g. `mnemo-mcp` or `/c/Users/.../wet-mcp`).
   - `recent`: use the last 5-10 file paths the agent edited or read.
   - `<topic>`: use the topic verbatim (the user's words).
   - Default (no arg): combine cwd + last 3 file paths.

2. **Search mnemo** with `context_type` filtering when applicable:
   ```
   memory(action="search",
          query="<resolved query>",
          context_type=null,
          limit=10,
          include_archived=false)
   ```
   - For decisions only: pass `context_type="decision"`.
   - For preferences only: pass `context_type="preference"`.
   - Without filter, results span all six context types.

3. **Synthesize results** into a 2-3 sentence summary grouped by type:
   - decisions, preferences, facts, open tasks
   - Present to the user as: "From prior sessions: ..."
   - Include memory IDs for any item the user might want to update or
     delete later.

4. **Skip silently** if mnemo is offline (tool errors), returns 0 results,
   or only returns low-relevance matches (rerank_score < 0.3). Do not
   inject noise into the conversation.

## Output Template

```
## Recalled context (<N> memories)

**Decisions** ([id1], [id2])
- ...

**Preferences** ([id3])
- ...

**Open tasks** ([id4])
- ...

(Recalled via mnemo:recall-context. Use memory(action="get", id=...) for full text.)
```

If 0 useful results: stay silent.

## Quality Rules

- **No injection on every prompt**: this skill is invoked by the agent on
  judgment, not auto-fired by a hook on every user message.
- **Filter by context_type when intent is clear**: searching all types is
  noisy; restrict to `decision`/`preference` when the user is about to
  make a choice.
- **Cite memory IDs**: enables follow-up update/delete without re-search.
- **Short summary > long dump**: never paste raw memory contents - the
  agent should already have full memory access via the `memory` tool if
  it needs detail.
