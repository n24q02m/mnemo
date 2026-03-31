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

from loguru import logger

DEFAULT_RELAY_URL = "https://mnemo-mcp.n24q02m.com"
SERVER_NAME = "mnemo-mcp"
CLOUD_KEYS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
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
        from mcp_relay_core.storage.config_file import read_config

        saved = read_config(SERVER_NAME)
        if saved and any(saved.get(k) for k in _ALL_CONFIG_KEYS):
            logger.info("Config loaded from file")
            return saved
        return None
    except Exception:
        return None


async def ensure_config() -> dict[str, str] | None:
    """Resolve config: env vars -> config file -> relay setup -> local fallback.

    Relay is ONLY triggered when steps 1-2 are ALL empty.
    Uses 30s timeout since mnemo-mcp works locally without credentials.

    Returns:
        Config dict with credential keys, or None if skipped/failed (local mode).
    """
    # 1. Check if env vars already provide cloud keys (highest priority)
    if any(os.environ.get(k) for k in CLOUD_KEYS):
        logger.info("Cloud API keys found in environment, skipping relay")
        return None  # env vars take priority, no relay needed

    # 2. Check saved relay config file
    config = load_relay_config()
    if config is not None:
        return config

    # 3. No local credentials found -- trigger relay setup
    logger.info("No cloud credentials found. Starting relay setup...")

    relay_url = DEFAULT_RELAY_URL
    try:
        from mcp_relay_core.relay.client import create_session, poll_for_result

        from .relay_schema import RELAY_SCHEMA

        session = await create_session(relay_url, SERVER_NAME, RELAY_SCHEMA)  # ty: ignore[invalid-argument-type]
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

    # Poll for result with shorter timeout
    try:
        from mcp_relay_core.relay.client import poll_for_result
        from mcp_relay_core.storage.config_file import write_config

        config = await poll_for_result(relay_url, session, timeout_s=RELAY_TIMEOUT_S)

        # Save to config file
        write_config(SERVER_NAME, config)
        logger.info("Cloud config saved successfully")

        # Trigger GDrive OAuth Device Code using default client ID from settings
        from mnemo_mcp.config import settings as _settings

        if _settings.google_drive_client_id:
            logger.info("Starting Google Drive OAuth setup...")
            try:
                from mnemo_mcp.sync import setup_google_auth

                await setup_google_auth(
                    relay_url=relay_url,
                    session_id=session.session_id,
                )
            except Exception as e:
                logger.warning(f"GDrive OAuth setup failed: {e}")

        # Notify relay page that setup is complete
        try:
            import httpx

            async with httpx.AsyncClient() as http:
                await http.post(
                    f"{relay_url}/api/sessions/{session.session_id}/messages",
                    json={
                        "type": "complete",
                        "text": "mnemo-mcp config saved. Setup complete!",
                    },
                )
        except Exception:
            pass

        return config

    except RuntimeError as e:
        if "RELAY_SKIPPED" in str(e):
            logger.info("Relay setup skipped by user. Using local mode.")
        elif "timed out" in str(e).lower():
            logger.info("Relay setup timed out. Using local mode.")
        else:
            logger.debug("Relay setup ended: {}", e)
        return None
