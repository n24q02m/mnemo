import hashlib

from mnemo_mcp.credential_state import _sub_data_dir
from mnemo_mcp.token_store import _get_token_dir_for_sub


def test_credential_state_sub_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))

    # Malicious sub
    malicious_sub = "../../../outside"
    d = _sub_data_dir(malicious_sub)

    # Verification
    expected_hash = hashlib.sha256(malicious_sub.encode("utf-8")).hexdigest()
    assert d == tmp_path / "subs" / expected_hash
    assert "outside" not in str(d)
    assert ".." not in str(d)
    # Check it is truly under the expected base
    assert str(d).startswith(str(tmp_path / "subs"))


def test_token_store_sub_path_traversal(tmp_path, monkeypatch):
    from mnemo_mcp.config import settings

    # We must not monkeypatch methods on Pydantic models with validate_assignment=True.
    # Instead, we set the field that the method depends on.
    # Settings.get_data_dir() returns Settings.get_db_path().parent.
    # Settings.get_db_path() returns Path(Settings.db_path) if set.
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "fake" / "memories.db"))

    # Malicious sub
    malicious_sub = "../../../outside"
    d = _get_token_dir_for_sub(malicious_sub)

    # Verification
    expected_hash = hashlib.sha256(malicious_sub.encode("utf-8")).hexdigest()
    # d should be tmp_path / "fake" / "subs" / expected_hash / "tokens"
    assert d == tmp_path / "fake" / "subs" / expected_hash / "tokens"
    assert "outside" not in str(d)
    assert ".." not in str(d)
    assert str(d).startswith(str(tmp_path / "fake" / "subs"))
