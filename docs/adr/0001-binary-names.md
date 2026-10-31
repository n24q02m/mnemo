# ADR 0001: Distribution and Binary Executable Names for mnemo

## Status
Accepted

## Context
Following the stack stabilization plan (Q3, Q13), distribution packages across the n24q02m stack are renamed to use the standard publisher prefix `n24q02m-*` on PyPI to prevent namespace confusion, clarify ownership, and align with other tools in the suite (`n24q02m-telegram`, etc.).

Users invoke mnemo in multiple contexts:
1. `uvx` ephemeral execution with package name matching binary: `uvx n24q02m-mnemo`
2. Local shell invocation where a short, concise command is preferred: `mnemo`
3. Pilot CLI usage for domain operations: `mnemo-pilot`
4. Existing automation, scripts, and workflows expecting the historical binary name: `mnemo-mcp`

## Decision
We expose entry point aliases in `pyproject.toml`:
- `n24q02m-mnemo`: Canonical primary executable name matching the PyPI package distribution.
- `mnemo`: Short ergonomic alias for local interactive shell use.
- `mnemo-pilot`: Pilot CLI over mnemo_core operations.
- `mnemo-mcp`: Backward-compatible alias for existing configurations and scripts.

## Consequences
- PyPI package name is `n24q02m-mnemo`.
- Users running `uvx n24q02m-mnemo` execute without requiring `--from`.
- Historical configurations referencing `mnemo-mcp` remain supported.
