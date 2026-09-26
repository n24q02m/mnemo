"""Path-traversal guards for per-sub namespace stores (runtime)."""

import pytest

from mnemo_mcp.runtime import db_path_for_namespace, mnemo_config_dir, validate_namespace


@pytest.mark.parametrize(
    "malicious",
    [
        "../../../outside",
        "..",
        "../peek",
        "sub/../../escape",
        "a/b",
        "has space",
        "x" * 65,  # over the 64-char cap
    ],
)
def test_validate_namespace_rejects_traversal(malicious):
    with pytest.raises(ValueError):
        validate_namespace(malicious)


def test_validate_namespace_accepts_safe_names():
    assert validate_namespace("default") == "default"
    assert validate_namespace("alice") == "alice"
    assert validate_namespace("team.01_sub-x") == "team.01_sub-x"


def test_db_path_for_namespace_stays_under_config_dir():
    malicious = "../../../outside"
    with pytest.raises(ValueError):
        db_path_for_namespace(malicious)


def test_db_path_for_namespace_layout():
    root = mnemo_config_dir()
    assert db_path_for_namespace(None) == root / "memories.db"
    assert db_path_for_namespace("default") == root / "memories.db"
    assert db_path_for_namespace("alice") == root / "subs" / "alice" / "memories.db"
