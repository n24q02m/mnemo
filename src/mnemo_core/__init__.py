"""mnemo_core: domain layer for the mnemo pilot (TOOL-1, P0).

Surfaces (mnemo_cli, mnemo_mcp pilot tools) depend on this package;
this package depends on neither.
"""

from mnemo_core import results
from mnemo_core.operations import capture, fetch, recall

__all__ = ["capture", "fetch", "recall", "results"]
