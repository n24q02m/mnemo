"""Non-blocking credential state management for mnemo-mcp.

State machine: awaiting_setup -> setup_in_progress -> (configured | local)
Reset: configured/local -> awaiting_setup (via setup tool).

mnemo-mcp works fully in local mode (Qwen3-Embedding ONNX), so credentials
are optional. In stdio mode, credentials are read from env vars only -- no
local form spawn. In HTTP mode, ``run_http_server`` renders the relay schema
form for the user to paste API keys; ``save_credentials`` persists them to
``config.enc``. GDrive device-code progress is surfaced through
``setup_complete_hook``.

See ``~/projects/.superpower/mcp-core/specs/2026-05-01-stdio-pure-http-multiuser.md``
for the architecture (stdio-pure + HTTP-multi-user; daemon-bridge auto-spawn
removed).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

SERVER_NAME = "mnemo-mcp"

# Grace window so the browser renders "Setup complete!" before the local spawn closes.
_SPAWN_CLEANUP_S = 5.0

CLOUD_KEYS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
]

# All config keys that indicate a valid saved config (includes GDrive)
_ALL_CONFIG_KEYS = [*CLOUD_KEYS, "GOOGLE_DRIVE_CLIENT_ID"]


class CredentialState(Enum):
    AWAITING_SETUP = "awaiting_setup"
    SETUP_IN_PROGRESS = "setup_in_progress"
    CONFIGURED = "configured"
    LOCAL = "local"


# Module-level state
_state = CredentialState.AWAITING_SETUP
_setup_url: str | None = None
_active_handle: Any | None = None  # LocalServerHandle
_on_gdrive_complete: Callable[[], None] | None = None
# Failure callback signature matches mcp-core's mark_setup_failed: optional
# key + error message. Wired by the HTTP server so the browser's
# /setup-status poll receives ``error:<message>`` instead of spinning forever
# when Google rejects the device code (invalid_grant / expired_token / etc.)
# or when save_token fails silently (ported from wet-mcp Bug #2 fix).
_on_gdrive_failed: Callable[[str, str], None] | None = None


def set_gdrive_complete_callback(cb: Callable[[], None]) -> None:
    """Set callback for when GDrive OAuth completes (used by HTTP server)."""
    global _on_gdrive_complete
    _on_gdrive_complete = cb


def set_gdrive_failed_callback(cb: Callable[[str, str], None]) -> None:
    """Set callback for when GDrive OAuth fails upstream (used by HTTP server).

    The callback receives ``(key, error_message)`` matching the
    ``mark_setup_failed(key, error)`` signature exposed by mcp-core's local
    OAuth app. It is invoked by ``_gdrive_token_poll`` whenever Google
    returns a terminal error (``invalid_grant``, ``expired_token``,
    ``access_denied``, etc.) or when the local ``save_token`` call raises
    after a successful exchange -- so the browser's ``/setup-status`` poll
    surfaces the error and stops waiting.
    """
    global _on_gdrive_failed
    _on_gdrive_failed = cb


def wire_gdrive_callbacks(
    mark_complete: Callable[[], None],
    mark_failed: Callable[..., None] | None = None,
) -> None:
    """Wire GDrive completion + optional failure callbacks in one call.

    Intended for use as ``setup_complete_hook``. mcp-core detects the hook
    signature by arity:

    - Older mcp-core (<1.3.0) passes 1 positional arg: ``hook(mark_complete)``.
      ``mark_failed`` stays ``None`` and GDrive terminal errors go
      server-log-only (legacy behavior).
    - Newer mcp-core (>=1.3.0) passes 2 args: ``hook(mark_complete, mark_failed)``.
      ``mark_failed`` wires through ``mark_setup_failed`` so the browser
      form stops spinning and shows the error.

    Making ``mark_failed`` optional here keeps mnemo-mcp forward-compatible
    with both versions; no lock-step release required between mnemo-mcp and
    mcp-core.
    """

    def _complete_then_cleanup() -> None:
        try:
            mark_complete()
        finally:
            _schedule_spawn_cleanup()

    set_gdrive_complete_callback(_complete_then_cleanup)

    global _on_gdrive_failed

    if mark_failed is None:
        _on_gdrive_failed = None
        return

    def _cb(_key: str, error: str) -> None:
        # mcp-core's mark_setup_failed(key, error) expects the key positionally.
        # We always operate on "gdrive" so hardcode it here.
        try:
            mark_failed("gdrive", error)
        except Exception:
            logger.opt(exception=True).debug("mark_setup_failed call failed")

    _on_gdrive_failed = _cb


def get_state() -> CredentialState:
    """Return current credential state."""
    return _state


def get_setup_url() -> str | None:
    """Return current relay setup URL (if any)."""
    return _setup_url


def resolve_credential_state() -> CredentialState:
    """Fast, synchronous credential check. Called during lifespan startup.

    Checks (in order):
    1. ENV VARS -- if any CLOUD_KEYS present, state = CONFIGURED
    2. CONFIG FILE -- if saved config has cloud keys, apply to env, state = CONFIGURED
    3. LOCAL MODE MARKER -- if user explicitly skipped, state = LOCAL
    4. NOTHING -- state = AWAITING_SETUP (server starts fast, relay triggered lazily)

    Returns new state. Takes <10ms.
    """
    global _state

    # 1. Check env vars
    if any(os.environ.get(k) for k in CLOUD_KEYS):
        logger.info("Cloud API keys found in environment")
        _state = CredentialState.CONFIGURED
        return _state

    # 2. Check config file
    try:
        from mcp_core.storage.per_plugin_store import PerPluginStore

        saved = PerPluginStore("mnemo").load()
        if saved and any(saved.get(k) for k in _ALL_CONFIG_KEYS):
            # Apply to env vars
            for key, value in saved.items():
                if value and key not in os.environ:
                    os.environ[key] = value
            logger.info("Config loaded from encrypted file")
            _state = CredentialState.CONFIGURED
            return _state
    except Exception:
        pass

    # 3. Check local mode marker
    try:
        from mcp_core import get_mode

        mode = get_mode(SERVER_NAME)
        if mode == "local":
            logger.info("Local mode marker found, skipping relay")
            _state = CredentialState.LOCAL
            return _state
    except Exception:
        pass

    # 4. Nothing found
    logger.info("No credentials found -- server starting in awaiting_setup mode")
    _state = CredentialState.AWAITING_SETUP
    return _state


async def _close_active_handle() -> None:
    """Best-effort close of the module-level local credential-form handle."""
    global _active_handle

    handle = _active_handle
    _active_handle = None
    if handle is None:
        return
    try:
        await handle.close()
    except Exception:
        logger.opt(exception=True).debug(
            "Best-effort close of credential-form handle failed"
        )


def _schedule_spawn_cleanup(grace_s: float = _SPAWN_CLEANUP_S) -> None:
    """Schedule detached cleanup of the local credential-form spawn."""
    if _active_handle is None:
        return

    async def _delayed_close() -> None:
        try:
            await asyncio.sleep(grace_s)
            await _close_active_handle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.opt(exception=True).debug("Delayed spawn cleanup failed")

    try:
        task = asyncio.create_task(_delayed_close())
        task.add_done_callback(lambda _t: None)
    except RuntimeError:
        pass


def _sub_data_dir(sub: str) -> Path:
    """Return per-subject data dir for multi-user remote mode.

    Layout: ``$MNEMO_DATA_DIR/subs/<sub>/`` (default base
    ``~/.mnemo-mcp``). Each per-authorize JWT ``sub`` gets its own
    directory so credentials never bleed across users.
    """
    base = Path(os.environ.get("MNEMO_DATA_DIR", str(Path.home() / ".mnemo-mcp")))
    d = base / "subs" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_for_sub(sub: str, config: dict[str, str]) -> None:
    """Persist a config dict for a single JWT subject (multi-user remote mode)."""
    (_sub_data_dir(sub) / "config.json").write_text(json.dumps(config))


def read_for_sub(sub: str) -> dict[str, str]:
    """Load the config dict for a single JWT subject (empty if missing)."""
    p = _sub_data_dir(sub) / "config.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_credentials(config: dict[str, str], context: dict[str, str]) -> dict | None:
    """Save credentials from OAuth form to config.enc and apply to environment.

    ``context`` carries the per-authorize ``sub``. In multi-user remote mode
    (``PUBLIC_URL`` set), credentials are scoped per-subject under
    ``$MNEMO_DATA_DIR/subs/<sub>/config.json`` and we skip the shared
    single-user state machine + GDrive device-code flow (each subject runs
    their own OAuth via the relay form). In single-user local mode, the
    SQLite memory DB and optional API keys live in one shared ``config.enc``
    on the host so the subject is intentionally unused.

    Called by the local OAuth AS when the user submits API keys via the
    browser form. Returns optional dict with next_step info.
    """
    global _state

    # Multi-user remote mode: per-subject credential storage. Skip the shared
    # config.enc + module-level state to keep subjects fully isolated. The
    # GDrive device-code flow is ALSO per-sub: token lands in
    # ``$MNEMO_DATA_DIR/subs/<sub>/tokens/google_drive.json`` so user A's
    # refresh-token is invisible to user B sharing the same deployment.
    if os.environ.get("PUBLIC_URL"):
        sub = context.get("sub") if context else None
        if not sub:
            raise RuntimeError("multi-user mode: SubjectContext sub required")
        store_for_sub(sub, config)
        logger.info("Credentials saved for sub={} (multi-user remote mode)", sub)

        try:
            from mnemo_mcp.config import settings as s

            if s.google_drive_client_id and s.google_drive_client_secret:
                import httpx

                response = httpx.post(
                    "https://oauth2.googleapis.com/device/code",
                    data={
                        "client_id": s.google_drive_client_id,
                        "scope": "https://www.googleapis.com/auth/drive.file",
                    },
                    timeout=15.0,
                )
                if response.status_code == 200:
                    device_data = response.json()
                    logger.info(
                        "GDrive device code (sub={}), user_code={}",
                        sub,
                        device_data.get("user_code"),
                    )
                    import asyncio
                    import threading

                    def _poll() -> None:
                        asyncio.run(
                            _gdrive_token_poll(
                                s.google_drive_client_id,
                                s.google_drive_client_secret,
                                device_data["device_code"],
                                device_data.get("interval", 5),
                                device_data.get("expires_in", 1800),
                                sub=sub,
                            )
                        )

                    threading.Thread(target=_poll, daemon=True).start()
                    return {
                        "type": "oauth_device_code",
                        "verification_url": device_data["verification_url"],
                        "user_code": device_data["user_code"],
                    }
        except Exception:
            logger.opt(exception=True).debug(
                "Multi-user GDrive device code request failed (non-fatal)"
            )
        return None

    from mcp_core.storage.per_plugin_store import PerPluginStore

    from mnemo_mcp.relay_setup import apply_config

    PerPluginStore("mnemo").save(config)
    apply_config(config)
    _state = CredentialState.CONFIGURED
    logger.info("Credentials saved via local OAuth form")

    try:
        from mnemo_mcp.config import settings

        settings.setup_providers()
    except Exception:
        logger.opt(exception=True).debug(
            "Provider re-init after save failed (non-fatal)"
        )

    # Trigger GDrive OAuth Device Code flow if configured
    try:
        from mnemo_mcp.config import settings as s

        if s.google_drive_client_id and s.google_drive_client_secret:
            import httpx

            response = httpx.post(
                "https://oauth2.googleapis.com/device/code",
                data={
                    "client_id": s.google_drive_client_id,
                    "scope": "https://www.googleapis.com/auth/drive.file",
                },
                timeout=15.0,
            )
            if response.status_code == 200:
                device_data = response.json()
                logger.info(
                    "GDrive device code requested, user_code={}",
                    device_data.get("user_code"),
                )

                import asyncio
                import threading

                def _poll_gdrive_token():
                    asyncio.run(
                        _gdrive_token_poll(
                            s.google_drive_client_id,
                            s.google_drive_client_secret,
                            device_data["device_code"],
                            device_data.get("interval", 5),
                            device_data.get("expires_in", 1800),
                        )
                    )

                threading.Thread(target=_poll_gdrive_token, daemon=True).start()

                # Auto-launch the default browser at Google's device-code page.
                # Best-effort -- headless hosts silently no-op and the user
                # still sees the URL rendered in the credential form.
                from mcp_core import try_open_browser

                try_open_browser(device_data["verification_url"])

                return {
                    "type": "oauth_device_code",
                    "verification_url": device_data["verification_url"],
                    "user_code": device_data["user_code"],
                }
    except Exception:
        logger.opt(exception=True).debug(
            "GDrive device code request failed (non-fatal)"
        )

    # No GDrive: cloud-only setup is done -- schedule local spawn cleanup so
    # the browser renders "Setup complete!" then the local server closes.
    _schedule_spawn_cleanup()
    return None


async def _gdrive_token_poll(
    client_id: str,
    client_secret: str,
    device_code: str,
    interval: int,
    expires_in: int,
    sub: str | None = None,
) -> None:
    """Background poll Google OAuth for device code token completion.

    Terminal outcomes:
    * ``access_token`` in response  -> save token + fire complete callback.
      If ``save_token`` raises, surface the failure via ``_notify_failed`` at
      WARNING level so the browser form stops spinning and the user knows to
      restart setup (the device_code cannot be re-exchanged).
    * ``authorization_pending``     -> keep polling (user hasn't approved yet).
    * ``slow_down``                 -> increase interval + keep polling.
    * Any other ``error`` value (``invalid_grant``, ``expired_token``,
      ``access_denied``, etc.) -> fire failure callback with the error
      string and stop. The failure callback wires into mcp-core's
      ``/setup-status`` so the browser shows the message instead of
      waiting forever.
    * Loop exits via ``deadline`` without success -> fire failure callback
      with ``expired`` so the browser surfaces the timeout.
    """
    import asyncio
    import time

    import httpx

    def _notify_failed(error: str) -> None:
        if _on_gdrive_failed is None:
            return
        try:
            _on_gdrive_failed("gdrive", error)
        except Exception:
            logger.opt(exception=True).debug("GDrive failed callback raised")

    deadline = time.time() + expires_in
    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            await asyncio.sleep(interval)
            try:
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    timeout=15.0,
                )
                data = resp.json()
                if "access_token" in data:
                    # Multi-user remote mode (``sub`` set) routes the token
                    # into a per-sub bucket so concurrent users do not share
                    # a single GDrive refresh-token. Single-user keeps the
                    # legacy shared path.
                    from mnemo_mcp.token_store import (
                        async_save_token,
                        async_save_token_for_sub,
                    )

                    try:
                        if sub:
                            await async_save_token_for_sub(sub, "google_drive", data)
                        else:
                            await async_save_token("google_drive", data)
                        logger.info("GDrive OAuth token saved successfully")
                    except Exception as exc:
                        logger.opt(exception=True).warning(
                            "GDrive token save FAILED after successful exchange: {}. "
                            "Token lost; device_code cannot be re-exchanged. "
                            "User must restart setup.",
                            exc,
                        )
                        _notify_failed(f"save_token failed: {exc}")
                        return
                    logger.info(
                        "GDrive authorized. Sync will start on next server restart."
                    )
                    if _on_gdrive_complete:
                        try:
                            _on_gdrive_complete()
                        except Exception:
                            logger.opt(exception=True).debug(
                                "GDrive complete callback failed"
                            )
                    return
                err = data.get("error")
                if err == "authorization_pending":
                    continue
                if err == "slow_down":
                    interval += 5
                    continue
                # Any other error from Google is terminal -- stop polling AND
                # tell the browser so the spinner stops.
                err_desc = data.get("error_description") or err or "unknown"
                logger.warning(
                    "GDrive token poll terminal error: {} ({})",
                    err,
                    err_desc,
                )
                _notify_failed(str(err_desc))
                return
            except Exception:
                logger.opt(exception=True).debug("GDrive token poll request failed")
        # Deadline exceeded without success -> surface timeout.
        logger.warning("GDrive device code flow expired before user approved")
        _notify_failed("expired")


def set_state(state: CredentialState) -> None:
    """For testing and setup tool actions."""
    global _state
    _state = state


def reset_state() -> None:
    """Reset to awaiting_setup (used by setup reset action)."""
    global _state, _setup_url
    _state = CredentialState.AWAITING_SETUP
    _setup_url = None

    # Close any active local credential-form spawn; fire-and-forget so callers
    # don't need to be async.
    if _active_handle is not None:
        try:
            task = asyncio.create_task(_close_active_handle())
            task.add_done_callback(lambda _t: None)
        except RuntimeError:
            pass

    try:
        from mcp_core import clear_mode
        from mcp_core.storage.per_plugin_store import PerPluginStore

        clear_mode(SERVER_NAME)
        PerPluginStore("mnemo").clear()
    except Exception:
        pass
