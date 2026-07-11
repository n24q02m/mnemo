"""Tests for token_store module."""

from __future__ import annotations

import json
from pathlib import Path
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

    def test_load_oserror(self, token_dir):
        from mnemo_mcp.token_store import load_token

        (token_dir / "drive.json").write_text('{"access_token": "test"}')

        original_read_text = Path.read_text

        def mock_read_text(self, **kwargs):
            if self.name == "drive.json":
                raise OSError("Permission denied")
            return original_read_text(self, **kwargs)

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch.object(Path, "read_text", side_effect=mock_read_text, autospec=True),
        ):
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

    def test_save_chmod_dir_oserror(self, token_dir):
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "abc"}

        original_chmod = Path.chmod

        def mock_chmod(self, mode):
            if self.name == "tokens":
                raise OSError("Permission denied for dir")
            return original_chmod(self, mode)

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch.object(Path, "chmod", side_effect=mock_chmod, autospec=True),
        ):
            m.get_data_dir.return_value = token_dir.parent
            # This should ignore the OSError from token_dir.chmod
            save_token("drive", token)

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "abc"

    def test_save_fchmod_oserror(self, token_dir):
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "fchmod_fail"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch(
                "mnemo_mcp.token_store.os.fchmod",
                side_effect=OSError("Permission denied"),
            ),
        ):
            m.get_data_dir.return_value = token_dir.parent
            save_token("drive", token)

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "fchmod_fail"

    def test_save_os_open_oserror_fallback(self, token_dir):
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "fallback_token"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch("mnemo_mcp.token_store.os.open", side_effect=OSError("Cannot open")),
        ):
            m.get_data_dir.return_value = token_dir.parent
            save_token("drive", token)

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "fallback_token"

    def test_save_fallback_chmod_oserror(self, token_dir):
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "fallback_chmod_fail"}

        original_chmod = Path.chmod

        def mock_chmod(self, mode):
            if self.name == "drive.json":
                raise OSError("Permission denied for file")
            return original_chmod(self, mode)

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch("mnemo_mcp.token_store.os.open", side_effect=OSError("Cannot open")),
            patch.object(Path, "chmod", side_effect=mock_chmod, autospec=True),
        ):
            m.get_data_dir.return_value = token_dir.parent
            save_token("drive", token)

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "fallback_chmod_fail"

    def test_save_nt_os(self, token_dir):
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "abc"}
        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "nt"),
            patch.object(Path, "chmod") as mock_chmod,
        ):
            m.get_data_dir.return_value = token_dir.parent
            # This should skip chmod completely on Windows
            save_token("drive", token)
            mock_chmod.assert_not_called()

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "abc"

    def test_save_write_oserror_fallback(self, token_dir):
        from unittest.mock import MagicMock

        from mnemo_mcp.token_store import save_token

        token = {"access_token": "write_fail_fallback"}
        mock_file = MagicMock()
        mock_file.write.side_effect = OSError("Write failed")
        mock_file.__enter__.return_value = mock_file

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch("mnemo_mcp.token_store.os.open", return_value=999),
            patch("mnemo_mcp.token_store.os.fchmod"),
            patch("mnemo_mcp.token_store.os.fdopen", return_value=mock_file),
            patch("mnemo_mcp.token_store.os.close"),
        ):
            m.get_data_dir.return_value = token_dir.parent
            save_token("drive", token)

        saved = json.loads((token_dir / "drive.json").read_text())
        assert saved["access_token"] == "write_fail_fallback"


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


class TestAsyncTokenStore:
    @pytest.mark.asyncio
    async def test_async_load_valid_token(self, token_dir):
        from mnemo_mcp.token_store import async_load_token

        token = {"access_token": "async123", "token_type": "Bearer"}
        (token_dir / "async_drive.json").write_text(json.dumps(token))

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            result = await async_load_token("async_drive")
        assert result == token

    @pytest.mark.asyncio
    async def test_async_save_creates_file(self, token_dir):
        from mnemo_mcp.token_store import async_save_token

        token = {"access_token": "async_save", "token_type": "Bearer"}
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            await async_save_token("async_drive_save", token)

        saved = json.loads((token_dir / "async_drive_save.json").read_text())
        assert saved["access_token"] == "async_save"

    @pytest.mark.asyncio
    async def test_async_delete_removes_file(self, token_dir):
        from mnemo_mcp.token_store import async_delete_token, async_save_token

        token = {"access_token": "async_delete", "token_type": "Bearer"}
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            await async_save_token("async_drive_delete", token)
            assert (token_dir / "async_drive_delete.json").exists()

            deleted = await async_delete_token("async_drive_delete")

        assert deleted is True
        assert not (token_dir / "async_drive_delete.json").exists()

    @pytest.mark.asyncio
    async def test_async_delete_missing_is_noop(self, token_dir):
        from mnemo_mcp.token_store import async_delete_token

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = token_dir.parent
            deleted = await async_delete_token("async_drive_missing")

        assert deleted is False


class TestSubTokenStore:
    @pytest.fixture
    def sub_token_dir(self, tmp_path):
        """Provide a temporary sub-scoped token directory."""
        sub = "test-user"
        import hashlib

        safe_sub = hashlib.sha256(sub.encode("utf-8")).hexdigest()
        d = tmp_path / "subs" / safe_sub / "tokens"
        d.mkdir(parents=True, exist_ok=True)
        with patch("mnemo_mcp.token_store.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            yield d

    def test_get_token_path_for_sub(self, tmp_path):
        from mnemo_mcp.token_store import get_token_path_for_sub

        sub = "test-user"
        provider = "google"
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            path = get_token_path_for_sub(sub, provider)
            import hashlib

            safe_sub = hashlib.sha256(sub.encode("utf-8")).hexdigest()
            expected = tmp_path / "subs" / safe_sub / "tokens" / f"{provider}.json"
            assert path == expected

    def test_save_token_for_sub_creates_file(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import get_token_path_for_sub, save_token_for_sub

        sub = "test-user"
        provider = "google"
        token = {"access_token": "sub-abc", "token_type": "Bearer"}

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            save_token_for_sub(sub, provider, token)

        path = get_token_path_for_sub(sub, provider)
        assert path.exists()
        saved = json.loads(path.read_text())
        assert saved["access_token"] == "sub-abc"

    def test_load_token_for_sub_valid(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import load_token_for_sub

        sub = "test-user"
        provider = "google"
        token = {"access_token": "sub-load", "token_type": "Bearer"}
        path = sub_token_dir / f"{provider}.json"
        path.write_text(json.dumps(token))

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            result = load_token_for_sub(sub, provider)
        assert result == token

    def test_load_token_for_sub_missing(self, tmp_path):
        from mnemo_mcp.token_store import load_token_for_sub

        sub = "test-user"
        provider = "missing"
        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            result = load_token_for_sub(sub, provider)
        assert result is None

    def test_load_token_for_sub_invalid_json(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import load_token_for_sub

        sub = "test-user"
        provider = "google"
        path = sub_token_dir / f"{provider}.json"
        path.write_text("not json")

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            result = load_token_for_sub(sub, provider)
        assert result is None

    def test_load_token_for_sub_oserror(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import load_token_for_sub

        sub = "test-user"
        provider = "google"
        path = sub_token_dir / f"{provider}.json"
        path.write_text('{"access_token": "test"}')

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch.object(Path, "read_text", side_effect=OSError("Read error")),
        ):
            m.get_data_dir.return_value = tmp_path
            result = load_token_for_sub(sub, provider)
        assert result is None

    def test_save_token_for_sub_os_open_oserror_fallback(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import get_token_path_for_sub, save_token_for_sub

        sub = "test-user"
        provider = "google"
        token = {"access_token": "fallback"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch("mnemo_mcp.token_store.os.open", side_effect=OSError("Open error")),
        ):
            m.get_data_dir.return_value = tmp_path
            save_token_for_sub(sub, provider, token)

        path = get_token_path_for_sub(sub, provider)
        saved = json.loads(path.read_text())
        assert saved["access_token"] == "fallback"

    def test_save_token_for_sub_chmod_oserror(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import save_token_for_sub

        sub = "test-user"
        provider = "google"
        token = {"access_token": "chmod-fail"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch.object(Path, "chmod", side_effect=OSError("Chmod error")),
            patch(
                "mnemo_mcp.token_store.os.open", side_effect=OSError("Force fallback")
            ),
        ):
            m.get_data_dir.return_value = tmp_path
            # Should not raise
            save_token_for_sub(sub, provider, token)

    def test_save_token_for_sub_fchmod_oserror(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import get_token_path_for_sub, save_token_for_sub

        sub = "test-user"
        provider = "google"
        token = {"access_token": "fchmod-fail"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch(
                "mnemo_mcp.token_store.os.fchmod", side_effect=OSError("fchmod error")
            ),
        ):
            m.get_data_dir.return_value = tmp_path
            save_token_for_sub(sub, provider, token)

        path = get_token_path_for_sub(sub, provider)
        saved = json.loads(path.read_text())
        assert saved["access_token"] == "fchmod-fail"

    def test_save_token_for_sub_dir_chmod_oserror(self, tmp_path):
        from mnemo_mcp.token_store import save_token_for_sub

        sub = "test-user"
        provider = "google"
        token = {"access_token": "dir-chmod-fail"}

        # We need a custom side effect that only raises for the directory
        def mock_chmod(path_obj, mode):
            if "tokens" in str(path_obj) and not str(path_obj).endswith(".json"):
                raise OSError("Dir chmod fail")
            return None

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch.object(Path, "chmod", side_effect=mock_chmod, autospec=True),
        ):
            m.get_data_dir.return_value = tmp_path
            save_token_for_sub(sub, provider, token)

    @pytest.mark.asyncio
    async def test_async_sub_ops(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import (
            async_load_token_for_sub,
            async_save_token_for_sub,
        )

        sub = "test-user"
        provider = "async-google"
        token = {"access_token": "async-sub"}

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            await async_save_token_for_sub(sub, provider, token)
            result = await async_load_token_for_sub(sub, provider)

        assert result == token

    def test_save_token_for_sub_nt_os(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import get_token_path_for_sub, save_token_for_sub

        sub = "test-user"
        provider = "nt-google"
        token = {"access_token": "nt-sub"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "nt"),
            patch.object(Path, "chmod") as mock_chmod,
        ):
            m.get_data_dir.return_value = tmp_path
            save_token_for_sub(sub, provider, token)
            mock_chmod.assert_not_called()

        path = get_token_path_for_sub(sub, provider)
        saved = json.loads(path.read_text())
        assert saved["access_token"] == "nt-sub"

    def test_load_token_for_sub_missing_access_token(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import load_token_for_sub

        sub = "test-user"
        provider = "google"
        path = sub_token_dir / f"{provider}.json"
        path.write_text(json.dumps({"refresh": "only"}))

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            result = load_token_for_sub(sub, provider)
        assert result is None

    def test_load_token_for_sub_non_dict(self, sub_token_dir, tmp_path):
        from mnemo_mcp.token_store import load_token_for_sub

        sub = "test-user"
        provider = "google"
        path = sub_token_dir / f"{provider}.json"
        path.write_text(json.dumps(["not", "a", "dict"]))

        with patch("mnemo_mcp.token_store.settings") as m:
            m.get_data_dir.return_value = tmp_path
            result = load_token_for_sub(sub, provider)
        assert result is None
