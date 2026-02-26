# Style Guide - mnemo-mcp

## Architecture
Persistent memory MCP server. Python, single-package repo.

## Python
- Formatter/Linter: Ruff (default config)
- Type checker: ty
- Test: pytest + pytest-asyncio
- Package manager: uv
- SDK: mcp[cli]

## Code Patterns
- Async/await for all I/O operations
- SQLite with FTS5 for full-text search
- Vector embeddings for semantic search (numpy cosine similarity)
- JSONL format for import/export
- Pydantic for input validation
- Rclone integration for cloud sync (verify checksums on download)

## Commits
Conventional Commits (feat:, fix:, chore:, docs:, refactor:, test:).

## Security
Validate file paths. Use json instead of pickle for serialization. Verify integrity of downloaded binaries. Sanitize config modifications.
