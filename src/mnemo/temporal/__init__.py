"""Phase 3 temporal knowledge graph package.

Modules:

* :mod:`mnemo.temporal.extract` -- entity + relation extraction via the
  Phase 1 :func:`mnemo.llm.call_llm` dispatch (replaces the local
  ``graph._llm_completion`` path).
* :mod:`mnemo.temporal.resolve` -- cross-memory entity resolution via
  embedding similarity + name fuzzy match.
* :mod:`mnemo.temporal.supersede` -- supersession detection +
  apply-to-old-rows orchestration.
* :mod:`mnemo.temporal.audit` -- mutation audit trail with
  prev/new state hashes.
* :mod:`mnemo.temporal.visualize` -- Mermaid / DOT / JSON graph export.
"""

from __future__ import annotations
