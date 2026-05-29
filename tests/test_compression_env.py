import pytest

from mnemo_mcp.compression import _env_compression_enabled


def test_env_compression_enabled_default(monkeypatch):
    """If COMPRESSION_ENABLED is not set, it should return True."""
    monkeypatch.delenv("COMPRESSION_ENABLED", raising=False)
    assert _env_compression_enabled() is True


@pytest.mark.parametrize("val", ["1", "true", "TRUE", " yes ", "ON"])
def test_env_compression_enabled_truthy(monkeypatch, val):
    """If COMPRESSION_ENABLED is set to a truthy value, it should return True."""
    monkeypatch.setenv("COMPRESSION_ENABLED", val)
    assert _env_compression_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "maybe", "blue"])
def test_env_compression_enabled_falsy(monkeypatch, val):
    """If COMPRESSION_ENABLED is set to anything else, it should return False."""
    monkeypatch.setenv("COMPRESSION_ENABLED", val)
    assert _env_compression_enabled() is False


def test_env_compression_enabled_empty(monkeypatch):
    """Empty string should be False."""
    monkeypatch.setenv("COMPRESSION_ENABLED", "")
    assert _env_compression_enabled() is False
