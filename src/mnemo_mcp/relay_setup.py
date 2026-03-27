"""Relay-first setup flow for mnemo-mcp.

Always shows the relay URL at startup so users can configure cloud providers
via browser. If the user skips or relay is unreachable, falls back to local
ONNX mode (Qwen3-Embedding, works without any credentials).

Resolution order:
1. Environment variables (highest priority, checked by pydantic Settings)
2. Encrypted config file (~/.config/mcp/config.enc)
3. Relay setup (browser-based form, 30s timeout for optional-cred server)
4. Local mode fallback (Qwen3-Embedding ONNX)
"""

from __future__ import annotations

import os
import sys

from loguru import logger

DEFAULT_RELAY_URL = "https://mnemo-mcp.n24q02m.com"
SERVER_NAME = "mnemo-mcp"
REQUIRED_FIELDS = ["JINA_AI_API_KEY"]  # At least one provider key needed
ALL_POSSIBLE_FIELDS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
]

# Shorter timeout for optional-credential servers (user can skip)
RELAY_TIMEOUT_S = 30.0


def load_relay_config() -> dict[str, str] | None:
    """Try to load cloud config from encrypted config file.

    Only checks the config file -- env vars are handled by pydantic-settings
    in Settings. This is a synchronous, non-blocking check.

    Returns:
        Config dict with API_KEYS, or None if no config file found.
    """
    try:
        from mcp_relay_core.storage.resolver import resolve_config

        result = resolve_config(SERVER_NAME, REQUIRED_FIELDS)
        if result.config is not None:
            logger.info("Relay config loaded from {}", result.source)
            return result.config
        return None
    except Exception:
        return None


async def ensure_config() -> dict[str, str] | None:
    """Resolve config: env vars -> config file -> relay setup -> local fallback.

    Always shows relay URL at startup for relay-first design.
    Uses 30s timeout since mnemo-mcp works locally without credentials.

    Returns:
        Config dict with credential keys, or None if skipped/failed (local mode).
    """
    # 1. Check if env vars already provide cloud keys
    if any(os.environ.get(k) for k in ALL_POSSIBLE_FIELDS):
        logger.info("Cloud API keys found in environment")
        return None  # env vars take priority, no relay needed

    # 2. Check config file
    config = load_relay_config()
    if config is not None:
        return config

    # 3. Always trigger relay setup (relay-first design)
    logger.info("No cloud credentials found. Starting relay setup...")

    relay_url = DEFAULT_RELAY_URL
    try:
        from mcp_relay_core.relay.client import create_session, poll_for_result

        from .relay_schema import RELAY_SCHEMA

        session = await create_session(relay_url, SERVER_NAME, RELAY_SCHEMA)
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
        return config

    except RuntimeError as e:
        if "RELAY_SKIPPED" in str(e):
            logger.info("Relay setup skipped by user. Using local mode.")
        elif "timed out" in str(e).lower():
            logger.info("Relay setup timed out. Using local mode.")
        else:
            logger.debug("Relay setup ended: {}", e)
        return None
