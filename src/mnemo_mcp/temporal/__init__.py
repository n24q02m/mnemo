"""Phase 3 temporal knowledge graph package.

Modules:

* :mod:`mnemo_mcp.temporal.extract` -- entity + relation extraction via the
  Phase 1 :func:`mnemo_mcp.llm.call_llm` dispatch (replaces the local
  ``graph._llm_completion`` path).
* :mod:`mnemo_mcp.temporal.resolve` -- cross-memory entity resolution via
  embedding similarity + name fuzzy match.
* :mod:`mnemo_mcp.temporal.supersede` -- supersession detection +
  apply-to-old-rows orchestration.
* :mod:`mnemo_mcp.temporal.audit` -- mutation audit trail with
  prev/new state hashes.
* :mod:`mnemo_mcp.temporal.visualize` -- Mermaid / DOT / JSON graph export.
"""

from __future__ import annotations
