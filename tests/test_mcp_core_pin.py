"""Guard: mnemo must depend on a mcp-core release that ships the CF storage
backends (D1Backend + VectorizeBackend), promoted in 1.18.0b12."""

import tomllib
from pathlib import Path


def test_mcp_core_pin_includes_cf_backends():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    core = next(d for d in deps if d.startswith("n24q02m-mcp-core"))
    # D1Backend + VectorizeBackend promoted into mcp-core storage at 1.18.0b12;
    # the per-sub credential regex fix (#501) in the deployed CF image lands at
    # 1.18.0b12, and this floor pins it.
    assert "1.18.0b12" in core, f"expected >=1.18.0b12 floor, got: {core}"


def test_no_uv_path_source_for_mcp_core():
    raw = Path("pyproject.toml").read_text(encoding="utf-8")
    if "[tool.uv.sources]" in raw:
        block = raw.split("[tool.uv.sources]", 1)[1]
        assert "mcp-core" not in block.lower(), "must use PyPI dep, not a path source"
