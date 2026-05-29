"""Google Drive sync backend for memory database (Phase 2 refactor).

Provides both the legacy function-style API (``sync_full``, ``sync_push``,
``sync_pull``, ``setup_google_auth``, ``start_auto_sync``,
``stop_auto_sync``) AND a new class-based :class:`GDriveBackend` that
implements :class:`mnemo_mcp.sync.base.SyncBackend` for the Phase 2
passport delta-sync orchestrator.

The function-style API is preserved unchanged so existing call sites
(``server.py``, ``setup_tool.py``, ``relay_setup.py``, the legacy test
suite) keep working. The class-based path lets the new orchestrator
treat GDrive uniformly with the S3 backend.

Sync flow (legacy):
1. Authenticate via OAuth Device Code flow
2. Push: upload local DB to Google Drive folder
3. Pull: download remote DB, merge via JSONL export/import
4. Auto-sync: periodic push/pull in background

Auth flow (Device Code -- no browser redirect needed):
1. POST /device/code -> get user_code + verification_url
2. User visits URL, enters code (or relay sends it)
3. Poll /token until authorized
4. Save access_token + refresh_token locally
5. Auto-refresh when expired
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mnemo_mcp.config import settings
from mnemo_mcp.sync.base import SyncBackend

if TYPE_CHECKING:
    from mnemo_mcp.db import MemoryDB

# Google OAuth endpoints
_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

# OAuth scope: only access files created by this app
_SCOPE = "https://www.googleapis.com/auth/drive.file"

# Device code flow grant type
_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# Background sync task reference
_sync_task: asyncio.Task | None = None

# Token provider name for token_store
_TOKEN_PROVIDER = "google_drive"

# In-memory folder ID cache to avoid duplicate folder creation
_folder_id_cache: dict[str, str] = {}

# Lock to prevent race conditions during disk cache operations
_folder_id_disk_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


async def _load_token() -> dict | None:
    """Load Google Drive OAuth token from local storage."""
    from mnemo_mcp.token_store import async_load_token

    return await async_load_token(_TOKEN_PROVIDER)


async def _save_token(token: dict) -> None:
    """Save Google Drive OAuth token to local storage."""
    from mnemo_mcp.token_store import async_save_token

    await async_save_token(_TOKEN_PROVIDER, token)


async def _has_token_available() -> bool:
    """Check if a Google Drive token is available."""
    return await _load_token() is not None


async def _refresh_token(token: dict) -> dict | None:
    """Refresh an expired access token using the refresh_token.

    Returns updated token dict, or None if refresh failed.
    """
    refresh_token = token.get("refresh_token")
    client_id = token.get("client_id", settings.google_drive_client_id)
    client_secret = settings.google_drive_client_secret

    if not refresh_token or not client_id or not client_secret:
        logger.warning(
            "Cannot refresh token: missing refresh_token, client_id, or client_secret"
        )
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: (status={response.status_code})")
                return None

            data = response.json()

            # Update token (keep existing refresh_token if not returned)
            updated = {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "expiry": time.time() + data.get("expires_in", 3600),
                "client_id": client_id,
                "token_type": data.get("token_type", "Bearer"),
            }
            await _save_token(updated)
            logger.debug("Token refreshed successfully")
            return updated

    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return None


async def _get_valid_token() -> dict | None:
    """Get a valid (non-expired) access token, refreshing if needed.

    Returns token dict with valid access_token, or None.
    """
    token = await _load_token()
    if not token:
        return None

    # Check expiry (refresh 60s before actual expiry)
    expiry = token.get("expiry", 0)
    if time.time() >= expiry - 60:
        logger.debug("Token expired, refreshing...")
        token = await _refresh_token(token)

    return token


# ---------------------------------------------------------------------------
# Google Drive API helpers
# ---------------------------------------------------------------------------


async def _drive_request(
    method: str,
    url: str,
    token: dict,
    *,
    params: dict | None = None,
    json_data: dict | None = None,
    content: bytes | None = None,
    headers: dict | None = None,
    timeout: float = 120.0,
) -> httpx.Response:
    """Make an authenticated Google Drive API request."""
    req_headers = {
        "Authorization": f"Bearer {token['access_token']}",
        **(headers or {}),
    }

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            url,
            params=params,
            json=json_data,
            content=content,
            headers=req_headers,
            timeout=timeout,
        )

    return response


async def _load_folder_id(folder_name: str) -> str | None:
    """Load cached folder ID from disk."""
    path = settings.get_data_dir() / "sync_folder_ids.json"
    async with _folder_id_disk_lock:
        try:
            if await asyncio.to_thread(path.exists):
                text = await asyncio.to_thread(path.read_text, encoding="utf-8")
                data = json.loads(text)
                return data.get(folder_name)
        except (json.JSONDecodeError, OSError):
            pass
    return None


async def _save_folder_id(folder_name: str, folder_id: str) -> None:
    """Persist folder ID to disk."""
    path = settings.get_data_dir() / "sync_folder_ids.json"
    async with _folder_id_disk_lock:
        data: dict[str, str] = {}
        try:
            if await asyncio.to_thread(path.exists):
                text = await asyncio.to_thread(path.read_text, encoding="utf-8")
                data = json.loads(text)
        except (json.JSONDecodeError, OSError):
            pass
        data[folder_name] = folder_id
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, json.dumps(data), encoding="utf-8")


async def _verify_folder_exists(token: dict, folder_id: str) -> bool:
    """Verify a folder ID still exists and is not trashed."""
    response = await _drive_request(
        "GET",
        f"{_DRIVE_API_BASE}/files/{folder_id}",
        token,
        params={"fields": "id,trashed"},
    )
    if response.status_code == 200:
        return not response.json().get("trashed", False)
    return False


async def _find_or_create_folder(token: dict, folder_name: str) -> str | None:
    """Find or create a Google Drive folder by name.

    Lookup order: memory cache -> disk cache -> Drive API search -> create.
    Folder ID is persisted to avoid duplicate creation from eventual consistency.
    """
    # 1. Check in-memory cache
    if folder_name in _folder_id_cache:
        fid = _folder_id_cache[folder_name]
        if await _verify_folder_exists(token, fid):
            return fid
        del _folder_id_cache[folder_name]

    # 2. Check disk cache
    saved_id = await _load_folder_id(folder_name)
    if saved_id:
        if await _verify_folder_exists(token, saved_id):
            _folder_id_cache[folder_name] = saved_id
            return saved_id

    # 3. Search by name on Drive (retry for eventual consistency)
    import asyncio

    query = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    for attempt in range(3):
        response = await _drive_request(
            "GET",
            f"{_DRIVE_API_BASE}/files",
            token,
            params={"q": query, "fields": "files(id,name)", "spaces": "drive"},
        )

        if response.status_code == 200:
            files = response.json().get("files", [])
            if files:
                fid = files[0]["id"]
                _folder_id_cache[folder_name] = fid
                await _save_folder_id(folder_name, fid)
                return fid

        if attempt < 2:
            await asyncio.sleep(1.0 * (2**attempt))  # 1s, 2s backoff

    # 4. Create new folder (only after 3 search attempts)
    metadata: dict[str, Any] = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    response = await _drive_request(
        "POST",
        f"{_DRIVE_API_BASE}/files",
        token,
        json_data=metadata,
        params={"fields": "id"},
    )

    if response.status_code == 200:
        fid = response.json().get("id")
        if fid:
            _folder_id_cache[folder_name] = fid
            await _save_folder_id(folder_name, fid)
        return fid

    logger.error(f"Failed to create folder '{folder_name}': {response.text[:100]}")
    return None


async def _find_file_in_folder(
    token: dict, folder_id: str, file_name: str
) -> dict | None:
    """Find a file by name in a specific folder.

    Returns file metadata dict (id, name, modifiedTime), or None.
    """
    query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
    response = await _drive_request(
        "GET",
        f"{_DRIVE_API_BASE}/files",
        token,
        params={
            "q": query,
            "fields": "files(id,name,modifiedTime)",
            "spaces": "drive",
        },
    )

    if response.status_code == 200:
        files = response.json().get("files", [])
        if files:
            return files[0]

    return None


async def _upload_file(
    token: dict,
    file_path: Path,
    folder_id: str,
    existing_file_id: str | None = None,
) -> bool:
    """Upload or update a file in Google Drive.

    If existing_file_id is provided, updates the file content.
    Otherwise creates a new file in the specified folder.
    """
    file_content = await asyncio.to_thread(file_path.read_bytes)

    if existing_file_id:
        # Update existing file content
        response = await _drive_request(
            "PATCH",
            f"{_DRIVE_UPLOAD_BASE}/files/{existing_file_id}",
            token,
            content=file_content,
            params={"uploadType": "media"},
            headers={"Content-Type": "application/x-sqlite3"},
        )
    else:
        # Create new file with multipart upload (metadata + content)

        metadata = json.dumps(
            {
                "name": file_path.name,
                "parents": [folder_id],
            }
        )

        # Use simple two-part upload
        boundary = "mnemo_mcp_upload_boundary"
        body = (
            (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{metadata}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: application/x-sqlite3\r\n\r\n"
            ).encode()
            + file_content
            + f"\r\n--{boundary}--".encode()
        )

        response = await _drive_request(
            "POST",
            f"{_DRIVE_UPLOAD_BASE}/files",
            token,
            content=body,
            params={"uploadType": "multipart", "fields": "id"},
            headers={
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
        )

    if response.status_code in (200, 201):
        return True

    logger.error(f"Upload failed ({response.status_code}): {response.text[:100]}")
    return False


async def _download_file(token: dict, file_id: str, dest_path: Path) -> bool:
    """Download a file from Google Drive to a local path."""
    response = await _drive_request(
        "GET",
        f"{_DRIVE_API_BASE}/files/{file_id}",
        token,
        params={"alt": "media"},
        timeout=300.0,
    )

    if response.status_code == 200:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(dest_path.write_bytes, response.content)
        return True

    logger.error(f"Download failed ({response.status_code}): {response.text[:100]}")
    return False


# ---------------------------------------------------------------------------
# Public sync operations
# ---------------------------------------------------------------------------


async def sync_push(db_path: Path, folder_name: str) -> bool:
    """Push local database to Google Drive folder.

    Uploads the SQLite database file to Google Drive.
    Updates existing file or creates new one.
    """
    token = await _get_valid_token()
    if not token:
        logger.error("No valid token for push")
        return False

    logger.info(f"Pushing {db_path.name} to Google Drive/{folder_name}...")

    folder_id = await _find_or_create_folder(token, folder_name)
    if not folder_id:
        logger.error("Failed to find/create sync folder")
        return False

    existing = await _find_file_in_folder(token, folder_id, db_path.name)
    existing_id = existing["id"] if existing else None

    success = await _upload_file(token, db_path, folder_id, existing_id)
    if success:
        logger.info(f"Push complete: {db_path.name} -> Google Drive/{folder_name}")
    else:
        logger.error("Push failed")

    return success


async def sync_pull(db_path: Path, folder_name: str) -> Path | None:
    """Pull remote database from Google Drive to local temp directory.

    Downloads the remote DB file to a temp location for merging.
    Returns path to downloaded file, or None on failure.
    """
    token = await _get_valid_token()
    if not token:
        logger.error("No valid token for pull")
        return None

    logger.info(f"Pulling from Google Drive/{folder_name}...")

    folder_id = await _find_or_create_folder(token, folder_name)
    if not folder_id:
        logger.warning("Sync folder not found")
        return None

    remote_file = await _find_file_in_folder(token, folder_id, db_path.name)
    if not remote_file:
        logger.info("No remote DB file found")
        return None

    temp_dir = db_path.parent / "sync_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_dir / f"remote_{db_path.name}"

    success = await _download_file(token, remote_file["id"], temp_db)
    if success and temp_db.exists():
        logger.info(f"Pull complete: Google Drive/{folder_name} -> {temp_db}")
        return temp_db

    logger.warning("Pull failed or downloaded file missing")
    temp_db.unlink(missing_ok=True)
    return None


async def sync_full(db: MemoryDB) -> dict:
    """Full sync cycle: pull -> merge -> push.

    Returns:
        Dict with sync results.
    """
    from mnemo_mcp.db import MemoryDB

    if not settings.sync_enabled:
        return {"status": "disabled", "message": "Sync is disabled"}

    if not settings.google_drive_client_id:
        return {
            "status": "error",
            "message": "GOOGLE_DRIVE_CLIENT_ID not configured",
        }

    # Check for valid token
    if not await _has_token_available():
        return {
            "status": "error",
            "message": "No Google Drive token available. "
            "Run setup_sync to complete OAuth setup.",
        }

    token = await _get_valid_token()
    if not token:
        return {
            "status": "error",
            "message": "Google Drive token expired and refresh failed. "
            "Run setup_sync to re-authenticate.",
        }

    db_path = settings.get_db_path()
    folder = settings.sync_folder

    result: dict = {"status": "ok", "pull": None, "push": None}

    # 1. Pull remote DB
    remote_db_path = await sync_pull(db_path, folder)
    if remote_db_path:
        try:

            def _merge_dbs() -> dict:
                _remote_db = MemoryDB(remote_db_path, embedding_dims=0)
                _remote_jsonl, _ = _remote_db.export_jsonl()
                _remote_db.close()
                if _remote_jsonl.strip():
                    return db.import_jsonl(_remote_jsonl, mode="merge")
                return {"imported": 0, "skipped": 0}

            # Run DB operations in thread pool to prevent blocking asyncio loop
            import_result = await asyncio.to_thread(_merge_dbs)

            result["pull"] = import_result
            if import_result.get("imported", 0) > 0:
                logger.info(f"Merged {import_result['imported']} memories from remote")

        except Exception as e:
            logger.error(f"Merge failed: {e}")
            result["pull"] = {"error": str(e)}
        finally:
            # Cleanup temp file and directory
            remote_db_path.unlink(missing_ok=True)
            try:
                remote_db_path.parent.rmdir()
            except OSError:
                pass
    else:
        result["pull"] = {"imported": 0, "skipped": 0, "note": "No remote DB found"}

    # 2. Push local DB to remote
    push_ok = await sync_push(db_path, folder)
    result["push"] = {"success": push_ok}

    return result


# ---------------------------------------------------------------------------
# Device Code OAuth flow
# ---------------------------------------------------------------------------


async def _request_device_code(client_id: str) -> dict | None:
    """Request a device code from Google OAuth2."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _DEVICE_CODE_URL,
                data={
                    "client_id": client_id,
                    "scope": _SCOPE,
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(
                    f"Device code request failed: (status={response.status_code})"
                )
                return None

            return response.json()

    except Exception as e:
        logger.error(f"Device code request error: {e}")
        return None


async def _present_user_code(
    user_code: str,
    verification_url: str,
    relay_url: str | None = None,
    session_id: str | None = None,
) -> None:
    """Present the device code to the user (via relay or stderr)."""
    import sys

    auth_message = (
        f"Google Drive Authorization\n"
        f"Visit: {verification_url}\n"
        f"Enter code: {user_code}"
    )

    if relay_url and session_id:
        # Send via relay messaging
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{relay_url}/api/sessions/{session_id}/messages",
                    json={
                        "type": "oauth_device_code",
                        "text": auth_message,
                        "data": {
                            "verification_url": verification_url,
                            "user_code": user_code,
                        },
                    },
                )
        except Exception as e:
            logger.warning(f"Failed to send code via relay: {e}")
    else:
        print(f"\n{auth_message}\n", file=sys.stderr, flush=True)


async def _poll_for_token(
    client_id: str,
    client_secret: str,
    device_code: str,
    interval: int,
    expires_in: int,
) -> bool:
    """Poll Google's token endpoint until the user authorizes."""
    deadline = time.time() + expires_in

    while time.time() < deadline:
        await asyncio.sleep(interval)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    _TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "device_code": device_code,
                        "grant_type": _DEVICE_CODE_GRANT,
                    },
                    timeout=30.0,
                )

                data = response.json()

                if response.status_code == 200:
                    # Success -- save token
                    token = {
                        "access_token": data["access_token"],
                        "refresh_token": data.get("refresh_token", ""),
                        "expiry": time.time() + data.get("expires_in", 3600),
                        "client_id": client_id,
                        "token_type": data.get("token_type", "Bearer"),
                    }
                    await _save_token(token)
                    logger.info("Google Drive authentication successful!")
                    return True

                error = data.get("error", "")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    interval += 1
                    continue
                elif error in ("access_denied", "expired_token"):
                    logger.error(f"Auth failed: {error}")
                    return False
                else:
                    logger.error(f"Unexpected error: {data}")
                    return False

        except Exception as e:
            logger.error(f"Token poll error: {e}")
            return False

    logger.error("Device code expired")
    return False


async def setup_google_auth(
    relay_url: str | None = None,
    session_id: str | None = None,
) -> bool:
    """Interactive Google OAuth setup via Device Code flow.

    If relay_url + session_id provided, send device code via relay messaging.
    Otherwise print to stderr.

    Returns True on success, False on failure.
    """
    client_id = settings.google_drive_client_id
    client_secret = settings.google_drive_client_secret
    if not client_id or not client_secret:
        logger.error("GOOGLE_DRIVE_CLIENT_ID or CLIENT_SECRET not configured")
        return False

    # 1. Request device code
    device_data = await _request_device_code(client_id)
    if not device_data:
        return False

    device_code = device_data["device_code"]
    user_code = device_data["user_code"]
    verification_url = device_data["verification_url"]
    interval = device_data.get("interval", 5)
    expires_in = device_data.get("expires_in", 1800)

    # 2. Present code to user
    await _present_user_code(user_code, verification_url, relay_url, session_id)

    # 3. Poll for token
    return await _poll_for_token(
        client_id, client_secret, device_code, interval, expires_in
    )


# ---------------------------------------------------------------------------
# Auto-sync loop
# ---------------------------------------------------------------------------


async def _auto_sync_loop(db: MemoryDB) -> None:
    """Background auto-sync loop."""
    interval = settings.sync_interval
    if interval <= 0:
        return

    logger.info(f"Auto-sync started (interval={interval}s)")
    # Run first sync immediately (don't wait for interval)
    try:
        await sync_full(db)
    except asyncio.CancelledError:
        logger.info("Auto-sync stopped")
        return
    except Exception as e:
        logger.error(f"Initial sync error: {e}")

    while True:
        try:
            await asyncio.sleep(interval)
            await sync_full(db)
        except asyncio.CancelledError:
            logger.info("Auto-sync stopped")
            break
        except Exception as e:
            logger.error(f"Auto-sync error: {e}")
            # Continue running despite errors


def start_auto_sync(db: MemoryDB) -> None:
    """Start background auto-sync task."""
    global _sync_task

    if not settings.sync_enabled:
        return

    if not settings.google_drive_client_id or settings.sync_interval <= 0:
        return

    if _sync_task and not _sync_task.done():
        return  # Already running

    _sync_task = asyncio.create_task(_auto_sync_loop(db))


def stop_auto_sync() -> None:
    """Stop background auto-sync task."""
    global _sync_task
    if _sync_task and not _sync_task.done():
        _sync_task.cancel()
        _sync_task = None


# ---------------------------------------------------------------------------
# CLI setup entry point
# ---------------------------------------------------------------------------


def setup_sync() -> None:
    """Set up Google Drive sync interactively.

    Usage: mnemo-mcp setup-sync
    Runs Device Code OAuth flow, saves token locally.
    """
    import sys

    print("=== Mnemo MCP: Setup Google Drive Sync ===")

    client_id = settings.google_drive_client_id
    if not client_id:
        print(
            "ERROR: GOOGLE_DRIVE_CLIENT_ID not set.\n"
            "Create an OAuth client ID at:\n"
            "  https://console.cloud.google.com/apis/credentials\n"
            "Set GOOGLE_DRIVE_CLIENT_ID in your MCP config.",
            file=sys.stderr,
        )
        sys.exit(1)

    success = asyncio.run(setup_google_auth())
    if success:
        print(f"\n{'=' * 60}")
        print("SUCCESS! Token saved locally.")
        print(f"{'=' * 60}\n")
        print("All you need in your MCP config:")
        print('  "SYNC_ENABLED": "true"')
        print(f'  "GOOGLE_DRIVE_CLIENT_ID": "{client_id}"')
        print("\nThe server will auto-load the token from disk.")
    else:
        print(
            "\nERROR: Authentication failed. Please try again.",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 2 SyncBackend implementation - bundle-based passport sync
# ---------------------------------------------------------------------------


_BUNDLE_FOLDER = "passport"


def _bundle_filename(sequence: int) -> str:
    """Return the GDrive filename for a passport bundle at ``sequence``.

    Mirrors the S3 backend layout (``passport/seq-NNNNNN.bin``) so an
    operator inspecting either backend sees the same naming scheme.
    """
    return f"seq-{sequence:06d}.bin"


async def _ensure_bundle_folder(token: dict, base_folder: str) -> str | None:
    """Create / locate the ``passport/`` subfolder inside the sync folder."""
    base_id = await _find_or_create_folder(token, base_folder)
    if not base_id:
        return None
    # GDrive does not support nested folder names in queries directly; we
    # find-or-create a folder named "passport" whose parent is base_id.
    query = (
        f"name='{_BUNDLE_FOLDER}' and '{base_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    response = await _drive_request(
        "GET",
        f"{_DRIVE_API_BASE}/files",
        token,
        params={"q": query, "fields": "files(id,name)", "spaces": "drive"},
    )
    if response.status_code == 200:
        files = response.json().get("files", [])
        if files:
            return files[0]["id"]

    create = await _drive_request(
        "POST",
        f"{_DRIVE_API_BASE}/files",
        token,
        json_data={
            "name": _BUNDLE_FOLDER,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [base_id],
        },
        params={"fields": "id"},
    )
    if create.status_code == 200:
        return create.json().get("id")
    return None


class GDriveBackend(SyncBackend):
    """:class:`SyncBackend` adapter over the legacy GDrive helpers.

    Stores opaque bundle bytes at ``<sync_folder>/passport/seq-NNNNNN.bin``.
    Authentication piggybacks on the existing token store + Device Code
    flow so users who already configured GDrive sync in Phase 1 do not
    need to reauthenticate for Phase 2 passport sync.
    """

    name = "gdrive"

    def __init__(self, folder_name: str | None = None) -> None:
        self._folder_name = folder_name or settings.sync_folder

    async def push(self, bundle: bytes, sequence: int) -> None:
        token = await _get_valid_token()
        if not token:
            raise RuntimeError("GDriveBackend.push: no valid token available")
        bundle_folder_id = await _ensure_bundle_folder(token, self._folder_name)
        if not bundle_folder_id:
            raise RuntimeError("GDriveBackend.push: failed to ensure bundle folder")

        filename = _bundle_filename(sequence)
        existing = await _find_file_in_folder(token, bundle_folder_id, filename)
        existing_id = existing["id"] if existing else None

        boundary = "mnemo_mcp_bundle_boundary"
        if existing_id:
            response = await _drive_request(
                "PATCH",
                f"{_DRIVE_UPLOAD_BASE}/files/{existing_id}",
                token,
                content=bundle,
                params={"uploadType": "media"},
                headers={"Content-Type": "application/octet-stream"},
            )
        else:
            metadata = json.dumps({"name": filename, "parents": [bundle_folder_id]})
            body = (
                (
                    f"--{boundary}\r\n"
                    f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                    f"{metadata}\r\n"
                    f"--{boundary}\r\n"
                    f"Content-Type: application/octet-stream\r\n\r\n"
                ).encode()
                + bundle
                + f"\r\n--{boundary}--".encode()
            )
            response = await _drive_request(
                "POST",
                f"{_DRIVE_UPLOAD_BASE}/files",
                token,
                content=body,
                params={"uploadType": "multipart", "fields": "id"},
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"GDriveBackend.push: upload failed ({response.status_code}): "
                f"{response.text[:100]}"
            )

    async def pull(self, sequence: int | None = None) -> bytes | None:
        token = await _get_valid_token()
        if not token:
            return None
        bundle_folder_id = await _ensure_bundle_folder(token, self._folder_name)
        if not bundle_folder_id:
            return None
        if sequence is None:
            sequence = await self._max_sequence(token, bundle_folder_id)
            if sequence == 0:
                return None
        filename = _bundle_filename(sequence)
        existing = await _find_file_in_folder(token, bundle_folder_id, filename)
        if not existing:
            return None
        response = await _drive_request(
            "GET",
            f"{_DRIVE_API_BASE}/files/{existing['id']}",
            token,
            params={"alt": "media"},
            timeout=300.0,
        )
        if response.status_code == 200:
            return response.content
        return None

    async def last_remote_sequence(self) -> int:
        token = await _get_valid_token()
        if not token:
            return 0
        bundle_folder_id = await _ensure_bundle_folder(token, self._folder_name)
        if not bundle_folder_id:
            return 0
        return await self._max_sequence(token, bundle_folder_id)

    async def health_check(self) -> bool:
        token = await _get_valid_token()
        if not token:
            return False
        try:
            base_id = await _find_or_create_folder(token, self._folder_name)
            return base_id is not None
        except Exception:
            return False

    @staticmethod
    async def _max_sequence(token: dict, folder_id: str) -> int:
        query = f"'{folder_id}' in parents and trashed=false"
        response = await _drive_request(
            "GET",
            f"{_DRIVE_API_BASE}/files",
            token,
            params={"q": query, "fields": "files(name)", "spaces": "drive"},
        )
        if response.status_code != 200:
            return 0
        files = response.json().get("files", [])
        max_seq = 0
        for f in files:
            n = f.get("name", "")
            if n.startswith("seq-") and n.endswith(".bin"):
                try:
                    seq = int(n[len("seq-") : -len(".bin")])
                except ValueError:
                    continue
                if seq > max_seq:
                    max_seq = seq
        return max_seq
