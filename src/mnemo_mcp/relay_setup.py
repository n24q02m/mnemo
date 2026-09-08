"""Credential resolution for mnemo-mcp.

Resolution order (relay only when ALL local sources are empty):
1. ENV VARS          -- User explicitly set (highest priority, skip everything)
2. RELAY CONFIG      -- Saved from previous relay setup (~/.config/mcp/config.enc)
3. RELAY SETUP       -- Interactive, ONLY when steps 1-2 are ALL empty (30s timeout)
4. LOCAL MODE        -- Fallback (Qwen3-Embedding ONNX)
"""

from __future__ import annotations

import os
import sys
from typing import Any

from loguru import logger

SERVER_NAME = "mnemo-mcp"
CLOUD_KEYS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
    "GOOGLE_VERTEX_EXPRESS_API_KEY",
]
# All config keys that indicate a valid saved config
_ALL_CONFIG_KEYS = [*CLOUD_KEYS, "GOOGLE_DRIVE_CLIENT_ID"]

# Shorter timeout for optional-credential servers (user can skip)
RELAY_TIMEOUT_S = 300.0


def load_relay_config() -> dict[str, str] | None:
    """Try to load cloud config from encrypted config file.

    Only checks the config file -- env vars are handled by pydantic-settings
    in Settings. This is a synchronous, non-blocking check.

    Returns:
        Config dict with cloud API keys, or None if no config file found.
    """
    try:
        from mcp_core.storage.per_plugin_store import PerPluginStore

        saved = PerPluginStore("mnemo").load()
        if saved and any(saved.get(k) for k in _ALL_CONFIG_KEYS):
            logger.info("Config loaded from file")
            return saved
        return None
    except Exception:
        return None


def apply_config(config: dict[str, str]) -> None:
    """Apply config dict to environment variables."""
    for key, value in config.items():
        if value and key not in os.environ:
            os.environ[key] = value
            logger.debug("Applied relay config: {}", key)


async def ensure_config() -> dict[str, str] | None:
    """Resolve config: env vars -> config file -> relay setup -> local fallback.

    Relay is ONLY triggered when steps 1-2 are ALL empty.
    Uses 30s timeout since mnemo-mcp works locally without credentials.

    Returns:
        Config dict with credential keys, or None if skipped/failed (local mode).
    """
    # 1. Check local credentials
    local_res = _check_local_credentials()
    if local_res is True:
        return None
    if isinstance(local_res, dict):
        return local_res

    # 2. No local credentials found -- trigger relay setup.
    # Per mode-matrix 2.5, mnemo-mcp default is `http local relay`; `remote-relay`
    # mode requires user-supplied URL (no centralized mnemo-mcp.n24q02m.com).
    relay_url = os.environ.get("MCP_RELAY_URL")
    if not relay_url:
        raise RuntimeError(
            "MCP_RELAY_URL env var is required for remote-relay mode. "
            "mnemo-mcp default mode is 'http local relay' (no remote URL needed). "
            "For self-host remote-relay, set MCP_RELAY_URL=https://<your-instance>."
        )

    logger.info("No cloud credentials found. Starting relay setup...")
    try:
        session = await _initiate_relay_session(relay_url)
    except Exception:
        logger.debug("Cannot reach relay server at {}. Using local mode.", relay_url)
        return None

    # Log URL to stderr (visible to user in MCP client)
    print(
        f"\nConfigure cloud providers (optional, 30s timeout):"
        f"\n{session.relay_url}"
        f"\nSkip to use local mode (Qwen3-Embedding ONNX).\n",
        file=sys.stderr,
        flush=True,
    )

    # 3. Poll for result with shorter timeout
    try:
        from mcp_core.relay.client import poll_for_result

        config = await poll_for_result(relay_url, session, timeout_s=RELAY_TIMEOUT_S)

        await _handle_post_config_setup(relay_url, session, config)
        return config

    except RuntimeError as e:
        _handle_relay_error(e)
        return None


def _check_local_credentials() -> dict[str, str] | None | bool:
    """Check for credentials in environment variables or saved config file.

    Returns:
        True if credentials found in environment (env takes priority).
        Dict if credentials found in saved config file.
        None if no credentials found locally.
    """
    # 1. Check if env vars already provide cloud keys (highest priority)
    if any(os.environ.get(k) for k in CLOUD_KEYS):
        logger.info("Cloud API keys found in environment, skipping relay")
        return True

    # 2. Check saved relay config file
    config = load_relay_config()
    if config is not None:
        return config

    return None


async def _initiate_relay_session(relay_url: str) -> Any:
    """Create a new relay session for configuration."""
    from mcp_core.relay.client import create_session

    from .relay_schema import RELAY_SCHEMA

    return await create_session(relay_url, SERVER_NAME, RELAY_SCHEMA)  # ty: ignore[invalid-argument-type]


async def _handle_post_config_setup(
    relay_url: str, session: Any, config: dict[str, str]
) -> bool:
    """Save and apply config, then trigger Google Drive setup if needed."""
    from mcp_core.storage.per_plugin_store import PerPluginStore

    # Save to per-plugin store
    PerPluginStore("mnemo").save(config)
    logger.info("Cloud config saved successfully")

    apply_config(config)

    # Notify relay page: config saved (info, NOT complete — GDrive OAuth follows)
    await _send_relay_message(
        relay_url,
        session.session_id,
        "info",
        "API keys saved. Starting Google Drive sync setup...",
    )

    # Trigger GDrive OAuth Device Code using default client ID from settings
    gdrive_ok = await _setup_gdrive_sync(relay_url, session.session_id)

    # NOW send complete (after GDrive OAuth finishes or skips)
    msg = (
        "Setup complete!"
        if gdrive_ok
        else "API keys saved. Google Drive sync can be configured later via config tool."
    )
    await _send_relay_message(relay_url, session.session_id, "complete", msg)

    return gdrive_ok


async def _setup_gdrive_sync(relay_url: str, session_id: str) -> bool:
    """Handle Google Drive OAuth setup if a client ID is configured."""
    from mnemo_mcp.config import settings as _settings

    if not _settings.google_drive_client_id:
        return False

    logger.info("Starting Google Drive OAuth setup...")
    try:
        from mnemo_mcp.sync import setup_google_auth

        return await setup_google_auth(
            relay_url=relay_url,
            session_id=session_id,
        )
    except Exception as e:
        logger.warning(f"GDrive OAuth setup failed: {e}")
        return False


async def _send_relay_message(
    relay_url: str, session_id: str, msg_type: str, text: str
) -> None:
    """Send a status message to the relay server."""
    try:
        import httpx

        async with httpx.AsyncClient() as http:
            await http.post(
                f"{relay_url}/api/sessions/{session_id}/messages",
                json={"type": msg_type, "text": text},
            )
    except Exception:
        pass


def _handle_relay_error(e: Exception) -> None:
    """Log appropriate messages for relay setup errors."""
    if "RELAY_SKIPPED" in str(e):
        logger.info("Relay setup skipped by user. Using local mode.")
    elif "timed out" in str(e).lower():
        logger.info("Relay setup timed out. Using local mode.")
    else:
        logger.debug("Relay setup ended: {}", e)
