"""OAuth token storage, routed through mcp-core's PerPluginStore.

Tokens are persisted as AES-GCM ciphertext via ``PerPluginStore``, which writes
to the active credential backend -- ``LocalFsBackend`` on a workstation,
``CfKvBackend`` on Cloudflare -- and never sees plaintext. Per-JWT-``sub``
variants key the token by sub so concurrent users on a remote deployment never
share a refresh-token. The on-disk plaintext layout (``~/.mnemo-mcp/tokens``)
is gone; ``get_token_path`` is retained for callers that report a conventional
location (e.g. setup status).

Token lifecycle:
1. First run: no token -> Device Code OAuth flow -> token saved (encrypted)
2. Subsequent runs: token loaded + decrypted -> auto-refreshed when expired
3. Re-auth: ``delete_token`` -> next run triggers a new OAuth flow
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from loguru import logger

from mnemo_mcp.config import settings

SERVER_NAME = "mnemo"  # PerPluginStore plugin name (matches credential_state)


def _get_token_dir() -> Path:
    """Conventional single-user token dir (``$MNEMO_DATA_DIR/tokens``)."""
    return settings.get_data_dir() / "tokens"


def get_token_path(provider: str) -> Path:
    """Conventional local token path -- informational only; the real store is the
    selected credential backend (encrypted), not this file."""
    return _get_token_dir() / f"{provider}.json"


def _get_token_dir_for_sub(sub: str) -> Path:
    """Conventional per-sub token dir; the sub is hashed to avoid path traversal."""
    safe_sub = hashlib.sha256(sub.encode("utf-8")).hexdigest()
    return settings.get_data_dir() / "subs" / safe_sub / "tokens"


def get_token_path_for_sub(sub: str, provider: str) -> Path:
    """Conventional per-sub token path (informational; see :func:`get_token_path`)."""
    return _get_token_dir_for_sub(sub) / f"{provider}.json"


def _token_store(provider: str, sub: str | None, backend):
    """PerPluginStore facade keyed at ``mnemo[/subs/<hash(sub)>]/tokens/<provider>``.

    The JWT ``sub`` is SHA-256 hashed before it reaches the store key/path so an
    arbitrary sub (any charset, including base64url chars PerPluginStore would
    reject) cannot traverse or collide -- matching ``get_token_path_for_sub``.
    ``provider`` is an internal constant (e.g. ``google_drive``), not user input.
    """
    from mcp_core.storage.backends import backend_from_env
    from mcp_core.storage.per_plugin_store import PerPluginStore

    safe_sub = hashlib.sha256(sub.encode("utf-8")).hexdigest() if sub else None
    return PerPluginStore(
        SERVER_NAME,
        safe_sub,
        backend=backend or backend_from_env(),
        sub_key=f"tokens/{provider}",
    )


def load_token(provider: str, backend=None) -> dict | None:
    """Load stored OAuth token (decrypted). None when absent/undecryptable."""
    try:
        data = _token_store(provider, None, backend).load()
    except Exception as e:  # corrupt blob / rotated key -> treat as absent
        logger.warning(f"Failed to load token for {provider}: {e}")
        return None
    if isinstance(data, dict) and "access_token" in data:
        return data
    return None


def save_token(provider: str, token: dict, backend=None) -> None:
    """Save OAuth token, encrypted via PerPluginStore + the selected backend."""
    _token_store(provider, None, backend).save(token)
    logger.info(f"Token saved (encrypted): {SERVER_NAME}/tokens/{provider}")


def delete_token(provider: str, backend=None) -> bool:
    """Delete a stored token. With ``backend`` clears it from the store; otherwise
    unlinks the legacy on-disk file. Returns True if something was removed."""
    if backend is not None:
        _token_store(provider, None, backend).clear()
        logger.info(f"Token cleared: {SERVER_NAME}/tokens/{provider}")
        return True
    path = get_token_path(provider)
    if path.exists():
        path.unlink()
        logger.info(f"Token deleted: {path}")
        return True
    return False


async def async_load_token(provider: str) -> dict | None:
    """Load stored OAuth token asynchronously."""
    return await asyncio.to_thread(load_token, provider)


async def async_save_token(provider: str, token: dict) -> None:
    """Save OAuth token asynchronously."""
    await asyncio.to_thread(save_token, provider, token)


def save_token_for_sub(sub: str, provider: str, token: dict, backend=None) -> None:
    """Save a per-JWT-sub OAuth token, encrypted via PerPluginStore."""
    _token_store(provider, sub, backend).save(token)
    logger.info(
        f"Token saved (encrypted, sub={sub}): {SERVER_NAME}/subs/{sub}/tokens/{provider}"
    )


def load_token_for_sub(sub: str, provider: str, backend=None) -> dict | None:
    """Load a per-JWT-sub OAuth token. None when absent/undecryptable."""
    try:
        data = _token_store(provider, sub, backend).load()
    except Exception as e:
        logger.warning(f"Failed to load token sub={sub} provider={provider}: {e}")
        return None
    if isinstance(data, dict) and "access_token" in data:
        return data
    return None


async def async_save_token_for_sub(sub: str, provider: str, token: dict) -> None:
    """Save per-sub OAuth token asynchronously."""
    await asyncio.to_thread(save_token_for_sub, sub, provider, token)


async def async_load_token_for_sub(sub: str, provider: str) -> dict | None:
    """Load per-sub OAuth token asynchronously."""
    return await asyncio.to_thread(load_token_for_sub, sub, provider)
