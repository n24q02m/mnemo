"""Supply-chain guard: security-pinned dependencies must stay patched.

Several transitive dependencies are pinned to patched releases in
``pyproject.toml`` to close known CVEs. A lock regeneration that silently
dropped or weakened a pin would reintroduce the vulnerability, so the
resolved ``uv.lock`` versions are asserted here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

_LOCK = Path(__file__).resolve().parent.parent / "uv.lock"

# package name -> minimum patched version (the CVE is closed at/above this).
_SECURITY_FLOORS = {
    "urllib3": "2.7.0",  # PYSEC-2026-141, PYSEC-2026-142 (2 high)
    "idna": "3.15",  # CVE-2026-45409
    "python-multipart": "0.0.27",  # CVE-2026-42561
}


def _locked_versions() -> dict[str, str]:
    data = tomllib.loads(_LOCK.read_text(encoding="utf-8"))
    return {pkg["name"]: pkg["version"] for pkg in data["package"]}


def test_uv_lock_exists():
    assert _LOCK.is_file(), f"uv.lock not found at {_LOCK}"


@pytest.mark.parametrize(("name", "floor"), sorted(_SECURITY_FLOORS.items()))
def test_security_pinned_dependency_meets_floor(name: str, floor: str):
    locked = _locked_versions()
    assert name in locked, f"{name} missing from uv.lock"
    assert Version(locked[name]) >= Version(floor), (
        f"{name} {locked[name]} is below the security floor {floor}"
    )
