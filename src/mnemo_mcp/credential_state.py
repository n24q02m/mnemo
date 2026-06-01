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
import contextvars
import hashlib
import json
import os
import sys
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
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
]

# All config keys that indicate a valid saved config (includes GDrive)
ALL_CONFIG_KEYS = [*CLOUD_KEYS, "GOOGLE_DRIVE_CLIENT_ID"]


# Per-request JWT subject (HTTP multi-user remote mode only).
# Set by ``_per_request_sub_scope`` middleware on every authenticated request.
# Stays ``None`` in stdio mode + single-user HTTP mode -- callers fall back to
# ``os.environ`` reads, preserving existing behavior.
_current_sub: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_sub", default=None
)


def set_current_sub(sub: str | None) -> None:
    """Set the per-request JWT sub (used by HTTP auth_scope middleware)."""
    _current_sub.set(sub)


def get_current_sub() -> str | None:
    """Return the per-request JWT sub if any, else ``None``.

    ``None`` indicates stdio mode or single-user HTTP -- callers should read
    credentials from environment variables.
    """
    return _current_sub.get()


def credentials_for_current_request() -> dict[str, str]:
    """Return the credential dict for the current request.

    HTTP multi-user mode (``_current_sub`` set): load from
    ``$MNEMO_DATA_DIR/subs/<sub>/config.json``.
    Stdio + single-user HTTP (``_current_sub`` None): fall back to
    ``os.environ`` filtered to ``CLOUD_KEYS`` so callers never see unrelated
    process env.
    """
    sub = _current_sub.get()
    if sub is None:
        return {k: v for k, v in os.environ.items() if k in CLOUD_KEYS and v}
    p = _sub_data_dir(sub) / "config.json"
    return json.loads(p.read_text()) if p.exists() else {}


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

    global _on_gdrive_complete, _on_gdrive_failed
    _on_gdrive_complete = _complete_then_cleanup

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


def _is_http_mode() -> bool:
    """Detect HTTP mode from CLI args + env vars.

    Mirrors `init-server.ts` / `__main__.py` HTTP detection. In stdio mode
    (the default after the 2026-05-01 stdio-pure flip) credentials come from
    env vars ONLY -- per spec §4.1 + OQ3 ("Cred source: env vars ONLY"). The
    PerPluginStore (~/.mnemo-mcp/config.json) is reserved for HTTP mode where
    the browser-form / paste-cred flow legitimately persists user input.

    Returns True if any of these are true:
    - ``--http`` flag in argv
    - ``MCP_TRANSPORT=http`` env var
    - ``TRANSPORT_MODE=http`` env var
    """
    return (
        "--http" in sys.argv
        or os.environ.get("MCP_TRANSPORT") == "http"
        or os.environ.get("TRANSPORT_MODE") == "http"
    )


def resolve_credential_state() -> CredentialState:
    """Fast, synchronous credential check. Called during lifespan startup.

    Checks (in order):
    1. ENV VARS -- if any CLOUD_KEYS present, state = CONFIGURED
    2. CONFIG FILE (HTTP mode only) -- if saved config has cloud keys, apply
       to env, state = CONFIGURED. Skipped in stdio mode per spec §4.1 + OQ3
       (stdio = env vars ONLY, no fallback to persisted store).
    3. LOCAL MODE MARKER -- if user explicitly skipped, state = LOCAL
    4. NOTHING -- state = AWAITING_SETUP (server starts fast, relay triggered lazily)

    mnemo-mcp has no required cred (local SQLite + Qwen3 ONNX work zero-config),
    so AWAITING_SETUP in stdio mode is a benign state -- tools that need cloud
    keys return per-call errors, the server itself is fully functional.

    Returns new state. Takes <10ms.
    """
    global _state

    # 1. Check env vars
    if any(os.environ.get(k) for k in CLOUD_KEYS):
        logger.info("Cloud API keys found in environment")
        _state = CredentialState.CONFIGURED
        return _state

    # 2. Check config file (HTTP mode only -- stdio = env vars ONLY per spec §4.1)
    if _is_http_mode():
        try:
            from mcp_core.storage.per_plugin_store import PerPluginStore

            saved = PerPluginStore("mnemo").load()
            if saved and any(saved.get(k) for k in ALL_CONFIG_KEYS):
                # Apply to env vars
                for key, value in saved.items():
                    if value and key not in os.environ:
                        os.environ[key] = value
                logger.info("Config loaded from encrypted file")
                _state = CredentialState.CONFIGURED
                return _state
        except Exception:
            logger.debug("Config loading from PerPluginStore failed")

    # 3. Check local mode marker
    try:
        from mcp_core import get_mode

        mode = get_mode(SERVER_NAME)
        if mode == "local":
            logger.info("Local mode marker found, skipping relay")
            _state = CredentialState.LOCAL
            return _state
    except Exception:
        logger.debug("Local mode marker check failed")

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
        logger.debug("Failed to schedule cleanup task (no event loop?)")


def _sub_data_dir(sub: str) -> Path:
    """Return per-subject data dir for multi-user remote mode.

    Layout: ``$MNEMO_DATA_DIR/subs/<hashed_sub>/`` (default base
    ``~/.mnemo-mcp``). Each per-authorize JWT ``sub`` gets its own
    directory so credentials never bleed across users. The sub is hashed to
    prevent path traversal vulnerabilities.
    """
    base = Path(os.environ.get("MNEMO_DATA_DIR", str(Path.home() / ".mnemo-mcp")))
    safe_sub = hashlib.sha256(sub.encode("utf-8")).hexdigest()
    d = base / "subs" / safe_sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_for_sub(sub: str, config: dict[str, str]) -> None:
    """Persist a config dict for a single JWT subject (multi-user remote mode)."""
    import stat

    path = _sub_data_dir(sub) / "config.json"
    config_json = json.dumps(config)

    # SECURITY: Ensure the credential file is created with 0600 permissions
    # (read/write for owner only) to prevent unauthorized access by other
    # local users, mitigating a TOCTOU vulnerability from using write_text.
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    mode = stat.S_IRUSR | stat.S_IWUSR
    fd = os.open(path, flags, mode)
    try:
        if os.name != "nt":
            os.fchmod(fd, mode)
    except OSError:
        pass
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(config_json)


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
    if os.environ.get("PUBLIC_URL"):
        sub = context.get("sub") if context else None
        if not sub:
            raise RuntimeError("multi-user mode: SubjectContext sub required")
        _save_remote_credentials(config, sub)
        return _trigger_gdrive_flow(sub=sub)

    _save_local_credentials(config)
    next_step = _trigger_gdrive_flow(auto_open=True)

    if not next_step:
        # No GDrive: cloud-only setup is done -- schedule local spawn cleanup so
        # the browser renders "Setup complete!" then the local server closes.
        _schedule_spawn_cleanup()

    return next_step


def passphrase_from_env() -> str | None:
    """Return ``SYNC_PASSPHRASE`` from the environment, or ``None`` if unset.

    Method 2/3 (HTTP / Docker deploy with ``SYNC_S3_BUCKET`` set) wires the
    passphrase via docker-env at container spawn — there is no relay form
    field for it in S3 mode. This helper centralises the read so callers
    do not need to import ``os`` inline at every site.

    The pydantic ``settings.sync_passphrase`` field is intentionally not
    consulted here: that field exists for the legacy ``_resolve_sync_passphrase``
    chain which is also driven by env, just one indirection further. Use
    this helper when you specifically want "passphrase from env at this
    instant" (e.g. during S3 mode startup validation).
    """
    raw = os.environ.get("SYNC_PASSPHRASE", "").strip()
    return raw or None


def _harden_passphrase(config: dict[str, str]) -> dict[str, str]:
    """Argon2id-hash ``SYNC_PASSPHRASE`` so the raw value never lands on disk.

    Phase 2 Task 7: the relay form collects ``SYNC_PASSPHRASE`` as a
    cleartext field for UX (single password input). Before persistence we
    swap it for ``SYNC_PASSPHRASE_SALT`` + ``SYNC_PASSPHRASE_HASH`` (both
    hex-encoded). Subsequent unlock attempts call
    :func:`mnemo_mcp.sync.bundle.verify_passphrase` against the stored
    pair so a leaked ``config.enc`` never exposes the raw passphrase.

    The raw passphrase is deliberately NOT kept in-memory beyond this
    function: the orchestrator passes the user-provided passphrase
    through directly when encrypting / decrypting bundles, so the only
    persistent artefact is the Argon2id digest.
    """
    raw = config.get("SYNC_PASSPHRASE", "").strip()
    if not raw:
        # Drop empty values so PerPluginStore does not pin an empty key
        # that would later be mistaken for "passphrase configured".
        config.pop("SYNC_PASSPHRASE", None)
        return config

    from mnemo_mcp.sync.bundle import hash_passphrase

    salt_hex, digest_hex = hash_passphrase(raw)
    config = dict(config)  # do not mutate caller's dict in place
    config.pop("SYNC_PASSPHRASE", None)
    config["SYNC_PASSPHRASE_SALT"] = salt_hex
    config["SYNC_PASSPHRASE_HASH"] = digest_hex
    logger.info("Sync passphrase hashed via Argon2id and stored")
    return config


def _save_remote_credentials(config: dict[str, str], sub: str) -> None:
    """Handle per-subject credential storage for multi-user remote mode."""
    config = _harden_passphrase(config)
    store_for_sub(sub, config)
    logger.info("Credentials saved for sub={} (multi-user remote mode)", sub)


def _save_local_credentials(config: dict[str, str]) -> None:
    """Handle global plugin storage and provider re-initialization for local mode."""
    global _state
    from mcp_core.storage.per_plugin_store import PerPluginStore

    from mnemo_mcp.relay_setup import apply_config

    config = _harden_passphrase(config)
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


def _trigger_gdrive_flow(
    sub: str | None = None, auto_open: bool = False
) -> dict | None:
    """Trigger GDrive OAuth Device Code flow if configured.

    Gated by :func:`mnemo_mcp.sync.resolve_active_backend` (XOR design):
    in S3 mode (``SYNC_S3_BUCKET`` set, Method 2/3 docker deploy) we
    SKIP the GDrive flow entirely — the operator wired S3 credentials at
    container spawn and end-users authenticating with cloud API keys via
    the relay form should NOT be prompted for a Google Drive account on
    top of that.
    """
    try:
        from mnemo_mcp.sync import resolve_active_backend

        if resolve_active_backend() == "s3":
            logger.info("GDrive flow skipped: SYNC_S3_BUCKET set (S3 mode active)")
            return None
    except Exception:
        # Resolver failure is non-fatal — fall through to legacy GDrive path.
        logger.opt(exception=True).debug("resolve_active_backend failed")

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
                if sub:
                    logger.info(
                        "GDrive device code (sub={}), user_code={}",
                        sub,
                        device_data.get("user_code"),
                    )
                else:
                    logger.info(
                        "GDrive device code requested, user_code={}",
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

                if auto_open:
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
            logger.debug(
                "No GDrive failure callback registered; terminal error: {}", error
            )
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
            logger.debug("Failed to schedule close handle task (no event loop?)")

    try:
        from mcp_core import clear_mode
        from mcp_core.storage.per_plugin_store import PerPluginStore

        clear_mode(SERVER_NAME)
        PerPluginStore("mnemo").clear()
    except Exception:
        logger.opt(exception=True).debug("Failed to clear local mode/config")
