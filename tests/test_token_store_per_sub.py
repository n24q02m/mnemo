"""Tests for ``token_store.save_token_for_sub`` / ``load_token_for_sub``.

Multi-user remote mode keys every per-provider OAuth token by JWT ``sub``
under ``$MNEMO_DATA_DIR/subs/<sub>/tokens/<provider>.json``. Equivalent to
the single-user ``save_token`` / ``load_token`` tests but for the per-sub
path layout.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def data_dir(tmp_path):
    """Provide a temporary data directory rooted at ``tmp_path``."""
    with patch("mnemo_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        yield tmp_path


class TestPerSubPaths:
    def test_token_dir_for_sub_uses_subs_layout(self, data_dir):
        from mnemo_mcp.token_store import _get_token_dir_for_sub

        path = _get_token_dir_for_sub("sub-abc")
        expected_hash = hashlib.sha256(b"sub-abc").hexdigest()
        assert path == data_dir / "subs" / expected_hash / "tokens"

    def test_token_path_for_sub_includes_provider(self, data_dir):
        from mnemo_mcp.token_store import get_token_path_for_sub

        path = get_token_path_for_sub("sub-abc", "google_drive")
        expected_hash = hashlib.sha256(b"sub-abc").hexdigest()
        assert (
            path == data_dir / "subs" / expected_hash / "tokens" / "google_drive.json"
        )


class TestSaveTokenForSub:
    def test_writes_json_and_creates_dirs(self, data_dir):
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            save_token_for_sub,
        )

        token = {"access_token": "abc", "refresh_token": "ref", "expires_in": 3600}
        save_token_for_sub("user-1", "google_drive", token)

        path = get_token_path_for_sub("user-1", "google_drive")
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == token

    def test_overwrites_existing_token(self, data_dir):
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            save_token_for_sub,
        )

        save_token_for_sub("user-1", "google_drive", {"access_token": "old"})
        save_token_for_sub("user-1", "google_drive", {"access_token": "new"})

        path = get_token_path_for_sub("user-1", "google_drive")
        assert json.loads(path.read_text(encoding="utf-8")) == {"access_token": "new"}

    def test_isolated_per_sub(self, data_dir):
        """User A's token must never appear under user B's directory."""
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            save_token_for_sub,
        )

        save_token_for_sub("user-A", "google_drive", {"access_token": "A"})
        save_token_for_sub("user-B", "google_drive", {"access_token": "B"})

        path_a = get_token_path_for_sub("user-A", "google_drive")
        path_b = get_token_path_for_sub("user-B", "google_drive")
        assert json.loads(path_a.read_text(encoding="utf-8")) == {"access_token": "A"}
        assert json.loads(path_b.read_text(encoding="utf-8")) == {"access_token": "B"}

    def test_chmod_dir_oserror_swallowed(self, data_dir):
        from mnemo_mcp.token_store import save_token_for_sub

        original_chmod = Path.chmod

        def mock_chmod(self, mode):
            if self.name == "tokens":
                raise OSError("readonly fs")
            return original_chmod(self, mode)

        with patch.object(Path, "chmod", mock_chmod):
            # Must not raise.
            save_token_for_sub("user-x", "google_drive", {"access_token": "tok"})

    def test_fchmod_oserror_swallowed(self, data_dir):
        if os.name == "nt":
            pytest.skip("POSIX-only fchmod path")
        from mnemo_mcp.token_store import save_token_for_sub

        original_fchmod = os.fchmod

        def mock_fchmod(fd, mode):
            raise OSError("not supported")

        with patch.object(os, "fchmod", mock_fchmod):
            save_token_for_sub("user-y", "google_drive", {"access_token": "tok"})

        # Restore (defensive)
        os.fchmod = original_fchmod  # noqa: SLF001


class TestSaveTokenForSubFallback:
    """Cover the fallback branch when ``os.open`` raises OSError."""

    def test_falls_back_to_path_write_text(self, data_dir):
        if os.name == "nt":
            pytest.skip("POSIX-only os.open fallback path")
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            save_token_for_sub,
        )

        original_open = os.open

        def mock_open(path, flags, mode=0o777):
            if str(path).endswith("google_drive.json"):
                raise OSError("simulated")
            return original_open(path, flags, mode)

        with patch.object(os, "open", mock_open):
            save_token_for_sub("user-fb", "google_drive", {"access_token": "ok"})

        path = get_token_path_for_sub("user-fb", "google_drive")
        assert path.exists()


class TestLoadTokenForSub:
    def test_returns_none_when_missing(self, data_dir):
        from mnemo_mcp.token_store import load_token_for_sub

        assert load_token_for_sub("absent", "google_drive") is None

    def test_returns_token_when_present(self, data_dir):
        from mnemo_mcp.token_store import (
            load_token_for_sub,
            save_token_for_sub,
        )

        save_token_for_sub("user-r", "google_drive", {"access_token": "tok"})
        result = load_token_for_sub("user-r", "google_drive")
        assert result == {"access_token": "tok"}

    def test_invalid_json_returns_none(self, data_dir):
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            load_token_for_sub,
        )

        path = get_token_path_for_sub("user-bad", "google_drive")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json{{{", encoding="utf-8")

        assert load_token_for_sub("user-bad", "google_drive") is None

    def test_missing_access_token_returns_none(self, data_dir):
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            load_token_for_sub,
        )

        path = get_token_path_for_sub("user-noaccess", "google_drive")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"refresh_token": "only"}), encoding="utf-8")

        assert load_token_for_sub("user-noaccess", "google_drive") is None

    def test_oserror_returns_none(self, data_dir):
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            load_token_for_sub,
            save_token_for_sub,
        )

        save_token_for_sub("user-oserr", "google_drive", {"access_token": "ok"})
        path = get_token_path_for_sub("user-oserr", "google_drive")

        original_read_text = Path.read_text

        def mock_read_text(self, *args, **kwargs):
            if self == path:
                raise OSError("boom")
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", mock_read_text):
            assert load_token_for_sub("user-oserr", "google_drive") is None


class TestAsyncTokenForSub:
    """async_save_token_for_sub / async_load_token_for_sub thin wrappers."""

    async def test_round_trip(self, data_dir):
        from mnemo_mcp.token_store import (
            async_load_token_for_sub,
            async_save_token_for_sub,
        )

        await async_save_token_for_sub(
            "async-user", "google_drive", {"access_token": "tok"}
        )
        result = await async_load_token_for_sub("async-user", "google_drive")
        assert result == {"access_token": "tok"}


class TestNTBranch:
    """Cover Windows branch where POSIX hardening is skipped."""

    def test_save_uses_write_text_on_nt(self, data_dir):
        from mnemo_mcp.token_store import (
            get_token_path_for_sub,
            save_token_for_sub,
        )

        with patch("mnemo_mcp.token_store.os.name", "nt"):
            save_token_for_sub("nt-user", "google_drive", {"access_token": "ok"})

        path = get_token_path_for_sub("nt-user", "google_drive")
        assert path.exists()
        # No mode assertion -- Windows token files don't carry POSIX bits.
        assert json.loads(path.read_text(encoding="utf-8")) == {"access_token": "ok"}


def test_chmod_mode_is_owner_only_when_posix(data_dir):
    if os.name == "nt":
        pytest.skip("POSIX-only chmod assertion")
    from mnemo_mcp.token_store import (
        get_token_path_for_sub,
        save_token_for_sub,
    )

    save_token_for_sub("user-chmod", "google_drive", {"access_token": "ok"})
    path = get_token_path_for_sub("user-chmod", "google_drive")

    # 0600 -- owner read/write only, no group or other access.
    mode = path.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR
