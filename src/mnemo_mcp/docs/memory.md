# Memory Tool - Full Documentation

## Overview

The `memory` tool manages persistent AI memories with hybrid search (text + semantic).
Memories survive across sessions, projects, and machines (with sync enabled).

## Actions

### `add` - Save a new memory

Save facts, preferences, decisions, code patterns, project context.

**Parameters:**
- `content` (required): The memory content to save
- `category` (optional): Organize by category (default: "general")
- `tags` (optional): List of tags for filtering

**Categories (recommended):**
- `preference` - User preferences, settings, workflow choices
- `decision` - Architecture decisions, trade-offs, rationale
- `fact` - Facts about the user, project, or environment
- `pattern` - Code patterns, idioms, conventions the user prefers
- `context` - Project context, goals, constraints
- `general` - Everything else

**Example:**
```json
{"action": "add", "content": "User prefers Polars over Pandas for DataFrames", "category": "preference", "tags": ["python", "dataframes"]}
```

### `search` - Find relevant memories

Hybrid search combining full-text and semantic similarity.

**Parameters:**
- `query` (required): Search query
- `category` (optional): Filter by category
- `tags` (optional): Filter by tags (any match)
- `limit` (optional): Max results (default: 5)

**Search behavior:**
- FTS5 full-text search (always active, works offline)
- Semantic vector search (when embedding model is configured)
- Results scored by: text relevance + semantic similarity + recency + access frequency
- Access count is incremented for returned results

**Example:**
```json
{"action": "search", "query": "dataframe library preference"}
```

### `list` - Browse memories

List memories with optional filtering, ordered by most recently updated.

**Parameters:**
- `category` (optional): Filter by category
- `limit` (optional): Max results (default: 5)

**Example:**
```json
{"action": "list", "category": "decision", "limit": 10}
```

### `update` - Modify an existing memory

Update content, category, or tags of a memory.

**Parameters:**
- `memory_id` (required): ID of the memory to update
- `content` (optional): New content
- `category` (optional): New category
- `tags` (optional): New tags

**Example:**
```json
{"action": "update", "memory_id": "abc123", "content": "Updated preference: Polars > Pandas > DuckDB"}
```

### `delete` - Remove a memory

**Parameters:**
- `memory_id` (required): ID of the memory to delete

**Example:**
```json
{"action": "delete", "memory_id": "abc123"}
```

### `export` - Export all memories as JSONL

Returns all memories as a JSONL string for backup or migration.

**Parameters:** None

### `import` - Import memories from JSONL

Import memories from JSONL string, list of objects, or single object.

**Parameters:**
- `data` (required): JSONL string, list of objects, or single object
- `mode` (optional): "merge" (skip existing, default) or "replace" (clear + import)

### `stats` - Get database statistics

Returns total count, categories breakdown, last update time, and sync status.

**Parameters:** None

## Proactive Memory Guidelines

The AI SHOULD proactively save memories when it detects:
- User states a preference or choice
- A technical decision is made with rationale
- User corrects the AI (save the correction)
- Project-specific conventions are established
- Recurring patterns or workflows emerge
- Important facts about the environment are discovered

The AI SHOULD search memories:
- At the start of new conversations (recall context)
- When making recommendations (check past preferences)
- Before suggesting alternatives (check past decisions)
- When the user references something discussed before
