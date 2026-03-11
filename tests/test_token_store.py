"""Tests for token_store module."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def token_dir(tmp_path):
    """Provide a temporary token directory."""
    d = tmp_path / "tokens"
    d.mkdir()
    with patch("mnemo_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        yield d


class TestLoadToken:
    def test_load_valid_token(self, token_dir):
        from mnemo_mcp.token_store import load_token

        token = {"access_token": "abc123", "token_type": "Bearer"}
        (token_dir / "drive.json").write_text(json.dumps(token))

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            result = load_token("drive")
        assert result == token

    def test_load_missing_token(self, token_dir):
        from mnemo_mcp.token_store import load_token

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            result = load_token("drive")
        assert result is None

    def test_load_invalid_json(self, token_dir):
        from mnemo_mcp.token_store import load_token

        (token_dir / "drive.json").write_text("not json{{{")

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            result = load_token("drive")
        assert result is None

    def test_load_missing_access_token(self, token_dir):
        from mnemo_mcp.token_store import load_token

        (token_dir / "drive.json").write_text(json.dumps({"refresh": "only"}))

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            result = load_token("drive")
        assert result is None

    def test_load_non_dict(self, token_dir):
        from mnemo_mcp.token_store import load_token

        (token_dir / "drive.json").write_text(json.dumps(["not", "a", "dict"]))

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            result = load_token("drive")
        assert result is None


class TestSaveToken:
    def test_save_creates_file(self, token_dir):
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "abc", "token_type": "Bearer"}
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            save_token("drive", token)

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "abc"

    def test_save_creates_dir_if_missing(self, tmp_path):
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "abc"}
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path / "new_data"
            save_token("drive", token)

        assert (tmp_path / "new_data" / "tokens" / "drive.json").exists()

    def test_save_overwrites_existing(self, token_dir):
        from mnemo_mcp.token_store import save_token

        (token_dir / "drive.json").write_text(json.dumps({"access_token": "old"}))
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            save_token("drive", {"access_token": "new"})

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "new"


class TestDeleteToken:
    def test_delete_existing(self, token_dir):
        from mnemo_mcp.token_store import delete_token

        (token_dir / "drive.json").write_text("{}")
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            assert delete_token("drive") is True
        assert not (token_dir / "drive.json").exists()

    def test_delete_nonexistent(self, token_dir):
        from mnemo_mcp.token_store import delete_token

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            assert delete_token("drive") is False


class TestGetTokenPath:
    def test_returns_correct_path(self, token_dir):
        from mnemo_mcp.token_store import get_token_path

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            path = get_token_path("drive")
        assert path == token_dir / "drive.json"
