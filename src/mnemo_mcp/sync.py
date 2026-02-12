"""Embedded Rclone process management for multi-machine sync.

Replaces manual rclone setup with automatic download + configuration.
Rclone is auto-downloaded on first use if not already available.

Sync flow:
1. rclone installed/found → configured with remote
2. Push: copy local DB to remote folder
3. Pull: copy remote DB to local, merge via JSONL export/import
4. Auto-sync: periodic push/pull in background

Resilience:
- Auto-download rclone binary on first use
- Health check before sync operations
- Conflict resolution via timestamp-based merge
- Configurable sync interval (0 = manual only)
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from mnemo_mcp.config import settings

if TYPE_CHECKING:
    from mnemo_mcp.db import MemoryDB

# Rclone version to download
_RCLONE_VERSION = "v1.68.2"

# Background sync task reference
_sync_task: asyncio.Task | None = None


def _get_rclone_dir() -> Path:
    """Get directory for rclone binary."""
    return settings.get_data_dir() / "bin"


def _get_rclone_path() -> Path | None:
    """Find rclone binary.

    Priority:
    1. System-installed rclone (in PATH)
    2. Bundled rclone in data dir
    """
    # Check system PATH first
    system_rclone = shutil.which("rclone")
    if system_rclone:
        return Path(system_rclone)

    # Check bundled binary
    ext = ".exe" if sys.platform == "win32" else ""
    bundled = _get_rclone_dir() / f"rclone{ext}"
    if bundled.exists():
        return bundled

    return None


def _get_platform_info() -> tuple[str, str, str]:
    """Get OS, arch, and file extension for rclone download.

    Returns:
        Tuple of (os_name, arch_name, extension).
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        os_name = "windows"
        ext = ".exe"
    elif system == "darwin":
        os_name = "osx"
        ext = ""
    else:
        os_name = "linux"
        ext = ""

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("i386", "i686"):
        arch = "386"
    else:
        arch = "amd64"  # Fallback

    return os_name, arch, ext


async def _download_rclone() -> Path | None:
    """Download rclone binary for current platform.

    Returns path to binary on success, None on failure.
    """
    os_name, arch, ext = _get_platform_info()
    archive_name = f"rclone-{_RCLONE_VERSION}-{os_name}-{arch}.zip"
    url = f"https://github.com/rclone/rclone/releases/download/{_RCLONE_VERSION}/{archive_name}"

    install_dir = _get_rclone_dir()
    install_dir.mkdir(parents=True, exist_ok=True)
    target_path = install_dir / f"rclone{ext}"

    if target_path.exists():
        return target_path

    logger.info(f"Downloading rclone {_RCLONE_VERSION} for {os_name}-{arch}...")

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=120.0)
            response.raise_for_status()

            # Write to temp file
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = Path(tmp.name)

        # Extract rclone binary from zip
        with zipfile.ZipFile(tmp_path, "r") as zf:
            # Find rclone binary in archive
            binary_name = f"rclone{ext}"
            for info in zf.infolist():
                if info.filename.endswith(binary_name) and not info.is_dir():
                    # Extract to temp, then move
                    with zf.open(info) as src:
                        target_path.write_bytes(src.read())
                    break
            else:
                logger.error("rclone binary not found in archive")
                return None

        # Make executable on Unix
        if ext == "":
            target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC)

        # Cleanup temp zip
        tmp_path.unlink(missing_ok=True)

        logger.info(f"rclone installed: {target_path}")
        return target_path

    except Exception as e:
        logger.error(f"Failed to download rclone: {e}")
        return None


async def ensure_rclone() -> Path | None:
    """Ensure rclone is available, downloading if needed.

    Returns path to rclone binary, or None if unavailable.
    """
    path = await asyncio.to_thread(_get_rclone_path)
    if path:
        return path

    # Download
    return await _download_rclone()


def _run_rclone(
    rclone_path: Path, args: list[str], timeout: int = 120
) -> subprocess.CompletedProcess:
    """Run rclone command synchronously."""
    cmd = [str(rclone_path), *args]
    logger.debug(f"rclone: {' '.join(cmd)}")

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def check_remote_configured(rclone_path: Path, remote: str) -> bool:
    """Check if an rclone remote is configured."""
    result = await asyncio.to_thread(_run_rclone, rclone_path, ["listremotes"], 10)
    if result.returncode != 0:
        return False

    remotes = [
        r.strip().rstrip(":") for r in result.stdout.strip().split("\n") if r.strip()
    ]
    return remote in remotes


async def sync_push(rclone_path: Path, db_path: Path, remote: str, folder: str) -> bool:
    """Push local database to remote.

    Copies the SQLite database file to the remote folder.
    Uses rclone copy (not sync) to avoid deleting remote files.
    """
    remote_dest = f"{remote}:{folder}"

    logger.info(f"Pushing {db_path.name} to {remote_dest}...")

    result = await asyncio.to_thread(
        _run_rclone,
        rclone_path,
        ["copy", str(db_path), remote_dest, "--progress"],
        300,
    )

    if result.returncode == 0:
        logger.info(f"Push complete: {db_path.name} → {remote_dest}")
        return True
    else:
        logger.error(f"Push failed: {result.stderr[:300]}")
        return False


async def sync_pull(
    rclone_path: Path, db_path: Path, remote: str, folder: str
) -> Path | None:
    """Pull remote database to local temp directory.

    Downloads the remote DB file to a temp location for merging.
    Returns path to downloaded file, or None on failure.
    """
    remote_src = f"{remote}:{folder}/{db_path.name}"
    temp_dir = db_path.parent / "sync_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_dir / f"remote_{db_path.name}"

    logger.info(f"Pulling from {remote_src}...")

    result = await asyncio.to_thread(
        _run_rclone,
        rclone_path,
        ["copyto", remote_src, str(temp_db), "--progress"],
        300,
    )

    if result.returncode == 0 and temp_db.exists():
        logger.info(f"Pull complete: {remote_src} → {temp_db}")
        return temp_db
    else:
        logger.warning(f"Pull failed or no remote file: {result.stderr[:200]}")
        # Cleanup
        temp_db.unlink(missing_ok=True)
        return None


async def sync_full(db: MemoryDB) -> dict:
    """Full sync cycle: pull → merge → push.

    Returns:
        Dict with sync results.
    """
    from mnemo_mcp.db import MemoryDB

    if not settings.sync_enabled or not settings.sync_remote:
        return {"status": "disabled", "message": "Sync not configured"}

    rclone_path = await ensure_rclone()
    if not rclone_path:
        return {"status": "error", "message": "rclone not available"}

    # Check remote is configured
    if not await check_remote_configured(rclone_path, settings.sync_remote):
        return {
            "status": "error",
            "message": f"rclone remote '{settings.sync_remote}' not configured. "
            f"Run: rclone config create {settings.sync_remote} drive",
        }

    db_path = settings.get_db_path()
    remote = settings.sync_remote
    folder = settings.sync_folder

    result: dict = {"status": "ok", "pull": None, "push": None}

    # 1. Pull remote DB
    remote_db_path = await sync_pull(rclone_path, db_path, remote, folder)
    if remote_db_path:
        try:
            # Open remote DB and export JSONL
            remote_db = MemoryDB(remote_db_path, embedding_dims=0)
            remote_jsonl = remote_db.export_jsonl()
            remote_db.close()

            # Import into local DB (merge mode - skip existing)
            if remote_jsonl.strip():
                import_result = db.import_jsonl(remote_jsonl, mode="merge")
                result["pull"] = import_result
                logger.info(f"Merged {import_result['imported']} memories from remote")
            else:
                result["pull"] = {"imported": 0, "skipped": 0}

        except Exception as e:
            logger.error(f"Merge failed: {e}")
            result["pull"] = {"error": str(e)}
        finally:
            # Cleanup temp file
            remote_db_path.unlink(missing_ok=True)
            remote_db_path.parent.rmdir()
    else:
        result["pull"] = {"imported": 0, "skipped": 0, "note": "No remote DB found"}

    # 2. Push local DB to remote
    push_ok = await sync_push(rclone_path, db_path, remote, folder)
    result["push"] = {"success": push_ok}

    return result


async def _auto_sync_loop(db: MemoryDB) -> None:
    """Background auto-sync loop."""
    interval = settings.sync_interval
    if interval <= 0:
        return

    logger.info(f"Auto-sync started (interval={interval}s)")
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

    if not settings.sync_enabled or settings.sync_interval <= 0:
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
