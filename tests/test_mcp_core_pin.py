"""Guard: mnemo must depend on a mcp-core release that ships the CF storage
backends (D1Backend + VectorizeBackend, promoted in 1.18.0b12) AND the
capability provider-chain primitive (mcp_core.chains, added in 1.18.0b13)."""

import tomllib
from pathlib import Path


def test_mcp_core_pin_includes_cf_backends():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    core = next(d for d in deps if d.startswith("n24q02m-mcp-core"))
    # 1.18.0b12 promoted the CF storage backends; 1.18.0b13 added mcp_core.chains
    # (resolve_backend); 1.18.0b14 added mcp_core.llm.key_rotation, so the embed/
    # rerank dispatch rotates provider API keys on rate-limit. 1.18.0b19 added the
    # F2 relay model-search catalog + OAuth refresh-TTL fix. 1.18.0b20 added the
    # relay catalog Jina live providers + bare-name normalization + keyword search.
    # Pin the latter.
    assert "1.18.0b20" in core, f"expected >=1.18.0b20 floor, got: {core}"


def test_no_uv_path_source_for_mcp_core():
    raw = Path("pyproject.toml").read_text(encoding="utf-8")
    if "[tool.uv.sources]" in raw:
        block = raw.split("[tool.uv.sources]", 1)[1]
        assert "mcp-core" not in block.lower(), "must use PyPI dep, not a path source"
