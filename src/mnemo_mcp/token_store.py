"""Local token storage for OAuth tokens.

Stores tokens in ~/.mnemo-mcp/tokens/<provider>.json with secure
file permissions (0600). Eliminates the need to paste long tokens
into MCP config -- tokens are persisted locally after the
first interactive OAuth flow.

Token lifecycle:
1. First run: no token -> Device Code OAuth flow -> token saved
2. Subsequent runs: token loaded from disk -> auto-refreshed when expired
3. Re-auth: delete token file -> next run triggers new OAuth flow
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from pathlib import Path

from loguru import logger

from mnemo_mcp.config import settings


def _get_token_dir() -> Path:
    """Get directory for token storage (~/.mnemo-mcp/tokens/).

    Single-user (default) layout. Multi-user remote mode uses
    :func:`_get_token_dir_for_sub` so concurrent JWT subjects do not
    share a GDrive refresh-token.
    """
    return settings.get_data_dir() / "tokens"


def get_token_path(provider: str) -> Path:
    """Get path for a provider's token file."""
    return _get_token_dir() / f"{provider}.json"


def _get_token_dir_for_sub(sub: str) -> Path:
    """Per-sub token directory (``$MNEMO_DATA_DIR/subs/<hashed_sub>/tokens``).

    Multi-user remote mode (``PUBLIC_URL`` set) keys every artifact by
    JWT ``sub`` so user A's GDrive refresh-token is not visible to
    user B sharing the same mnemo-mcp deployment. The sub is hashed to
    prevent path traversal vulnerabilities.
    """
    safe_sub = hashlib.sha256(sub.encode("utf-8")).hexdigest()
    return settings.get_data_dir() / "subs" / safe_sub / "tokens"


def get_token_path_for_sub(sub: str, provider: str) -> Path:
    """Get path for a provider's token file scoped to a specific JWT sub."""
    return _get_token_dir_for_sub(sub) / f"{provider}.json"


def load_token(provider: str) -> dict | None:
    """Load stored OAuth token for a provider.

    Returns the token dict, or None if not found/invalid.
    """
    path = get_token_path(provider)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "access_token" in data:
            return data
        logger.warning(f"Invalid token format in {path}")
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load token from {path}: {e}")
        return None


def save_token(provider: str, token: dict) -> None:
    """Save OAuth token to local storage with secure permissions.

    File permissions: 0600 (owner read/write only)
    Directory permissions: 0700 (owner read/write/execute only)
    """
    token_dir = _get_token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)

    # Secure directory permissions (Unix only)
    if os.name != "nt":
        try:
            token_dir.chmod(stat.S_IRWXU)  # 0700
        except OSError:
            pass

    path = get_token_path(provider)
    token_json = json.dumps(token, indent=2)

    if os.name != "nt":
        try:
            # Prevent TOCTOU vulnerability by setting permissions on creation
            flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
            mode = stat.S_IRUSR | stat.S_IWUSR  # 0600
            fd = os.open(path, flags, mode)
            try:
                # Ensure existing files also get their permissions restricted
                os.fchmod(fd, mode)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token_json)
        except OSError:
            path.write_text(token_json, encoding="utf-8")
            try:
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
    else:
        path.write_text(token_json, encoding="utf-8")

    logger.info(f"Token saved: {path}")


def delete_token(provider: str) -> bool:
    """Delete a stored token. Returns True if deleted."""
    path = get_token_path(provider)
    if path.exists():
        path.unlink()
        logger.info(f"Token deleted: {path}")
        return True
    return False


async def async_load_token(provider: str) -> dict | None:
    """Load stored OAuth token for a provider asynchronously."""
    return await asyncio.to_thread(load_token, provider)


async def async_save_token(provider: str, token: dict) -> None:
    """Save OAuth token to local storage asynchronously."""
    await asyncio.to_thread(save_token, provider, token)


def save_token_for_sub(sub: str, provider: str, token: dict) -> None:
    """Save OAuth token under the per-sub directory (multi-user remote).

    Same 0600 / 0700 hardening as :func:`save_token`. Token lands at
    ``$MNEMO_DATA_DIR/subs/<sub>/tokens/<provider>.json``.
    """
    token_dir = _get_token_dir_for_sub(sub)
    token_dir.mkdir(parents=True, exist_ok=True)

    if os.name != "nt":
        try:
            token_dir.chmod(stat.S_IRWXU)
        except OSError:
            pass

    path = get_token_path_for_sub(sub, provider)
    token_json = json.dumps(token, indent=2)

    if os.name != "nt":
        try:
            flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
            mode = stat.S_IRUSR | stat.S_IWUSR
            fd = os.open(path, flags, mode)
            try:
                os.fchmod(fd, mode)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token_json)
        except OSError:
            path.write_text(token_json, encoding="utf-8")
            try:
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
    else:
        path.write_text(token_json, encoding="utf-8")

    logger.info(f"Token saved (sub={sub}): {path}")


def load_token_for_sub(sub: str, provider: str) -> dict | None:
    """Load a per-sub OAuth token. Returns None when absent or malformed."""
    path = get_token_path_for_sub(sub, provider)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "access_token" in data:
            return data
        logger.warning(f"Invalid token format in {path}")
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load token from {path}: {e}")
        return None


async def async_save_token_for_sub(sub: str, provider: str, token: dict) -> None:
    """Save per-sub OAuth token asynchronously."""
    await asyncio.to_thread(save_token_for_sub, sub, provider, token)


async def async_load_token_for_sub(sub: str, provider: str) -> dict | None:
    """Load per-sub OAuth token asynchronously."""
    return await asyncio.to_thread(load_token_for_sub, sub, provider)


async def async_delete_token(provider: str) -> bool:
    """Delete a stored token asynchronously."""
    return await asyncio.to_thread(delete_token, provider)
