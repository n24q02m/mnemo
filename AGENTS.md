# AGENTS.md - mnemo-mcp

Persistent AI memory MCP Server. Python 3.13, uv, src layout.

## Build / Lint / Test Commands

```bash
uv sync --group dev                # Install dependencies
uv build                           # Build package (hatchling)
uv run ruff check .                # Lint
uv run ruff format --check .       # Format check
uv run ruff format .               # Format fix
uv run ruff check --fix .          # Lint fix (with --unsafe-fixes for aggressive)
uv run ty check                    # Type check (Astral ty)
uv run pytest                      # Run all tests (integration excluded by default)
uv run pytest -v                   # Verbose
uv run pytest -m integration       # Run integration tests only

# Run a single test file
uv run pytest tests/test_db.py

# Run a single test class
uv run pytest tests/test_db.py::TestSearch

# Run a single test function
uv run pytest tests/test_db.py::TestSearch::test_basic_match -v

# Mise shortcuts
mise run setup     # Full dev environment setup
mise run lint      # ruff check + ruff format --check + ty check
mise run test      # pytest
mise run fix       # ruff check --fix + ruff format
mise run dev       # uv run mnemo-mcp
```

### Pytest Configuration

- `asyncio_mode = "auto"` -- no `@pytest.mark.asyncio` needed
- Default timeout: 30 seconds per test
- Integration tests excluded by default (`-m 'not integration'`)
- Test files: `test_*.py` in `tests/` directory

## Code Style

### Formatting (Ruff)

- **Line length**: 88
- **Quotes**: Double quotes
- **Indent**: 4 spaces (Python), 2 spaces (JSON/YAML/TOML)
- **Line endings**: LF
- **Target**: Python 3.13

### Ruff Rules

`select = ["E", "F", "W", "I", "UP", "B", "C4"]`, `ignore = ["E501"]`

- `I` = isort import ordering, `UP` = pyupgrade (modern syntax), `B` = bugbear, `C4` = comprehensions

### Type Checker (ty)

Lenient config: `unresolved-import`, `unresolved-attribute`, `possibly-missing-attribute` all `"ignore"`.

### Import Ordering (isort via Ruff)

1. `__future__` imports
2. Standard library (`import asyncio`, `import json`)
3. Third-party (`from loguru import logger`, `from pydantic_settings import BaseSettings`)
4. Local (`from mnemo_mcp.config import settings`, `from mnemo_mcp.db import MemoryDB`)

Blank line between groups. Lazy imports for heavy deps inside functions.

```python
import asyncio
import json
import sys
from collections.abc import AsyncIterator

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP

from mnemo_mcp.config import settings
from mnemo_mcp.db import MemoryDB
```

### Type Hints

- Full type hints on all signatures: parameters, return types
- Modern syntax: `str | None` (not `Optional`), `list[str]` (not `List`)
- `from __future__ import annotations` in some files
- `TYPE_CHECKING` guard for circular imports
- `Protocol` classes for backend abstraction
- `py.typed` marker file present

### Naming Conventions

| Element            | Convention       | Example                          |
|--------------------|------------------|----------------------------------|
| Functions/methods  | snake_case       | `setup_api_keys()`, `_build_fts_queries()` |
| Classes            | PascalCase       | `Settings`, `MemoryDB`, `LiteLLMBackend` |
| Constants          | UPPER_SNAKE_CASE | `MAX_RETRIES`, `_DEFAULT_EMBEDDING_DIMS` |
| Private            | Leading `_`      | `_backend`, `_sync_task`, `_embed()` |
| Test classes       | `Test` + feature | `TestAdd`, `TestSearch`          |
| Fixtures           | snake_case       | `tmp_db`, `mock_ctx`             |

### Error Handling

- MCP tools return `_json({"error": "..."})` instead of raising exceptions
- `match action:` (structural pattern matching) for routing tool actions
- try/except with `logger.warning()` or `logger.error()` for non-fatal failures
- Boolean returns for mutations (`db.update()`, `db.delete()`)
- `asyncio.to_thread()` for blocking I/O (SQLite, embedding)

### File Organization

```
src/mnemo_mcp/
  __init__.py, __main__.py    # Package + CLI entry
  config.py                   # Pydantic Settings (singleton)
  server.py                   # FastMCP server, tools, resources, prompts
  db.py                       # SQLite: CRUD, FTS5, vector search
  embedder.py                 # Dual-backend: LiteLLM + qwen3-embed
  sync.py                     # Rclone sync management
  docs/                       # Tool documentation markdown
tests/                        # One test file per source module (1:1 mapping)
  conftest.py                 # Shared fixtures
```

### Documentation

- Module-level docstrings on every `.py` file
- Google-style docstrings: `Args:`, `Returns:` sections
- Section comments: `# --- Lifespan ---`, `# --- Tools ---`

### Commits

Conventional Commits: `type(scope): message`. Automated semantic release.

### Pre-commit Hooks

1. Ruff lint (`--fix --target-version=py313`) + format
2. ty type check
3. pytest (`--timeout=30 --tb=short -q`)
