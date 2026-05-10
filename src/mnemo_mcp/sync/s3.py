"""S3-compatible passport-sync backend (Phase 2 Task 5).

Implements :class:`SyncBackend` against any S3-compatible object store
(AWS S3, Cloudflare R2, Backblaze B2, MinIO, etc.) via boto3. The same
opaque-bundle layout used by ``GDriveBackend`` applies here -
``<prefix>/seq-NNNNNN.bin`` keyed by monotonic sequence number.

Wiring:

* Settings live in :mod:`mnemo_mcp.config` (``SYNC_S3_*`` env vars).
* When ``SYNC_S3_BUCKET`` is set + creds resolve, the package
  registers an ``S3Backend`` instance under name ``"s3"`` so callers
  can ``sync.get("s3")``.
* Custom ``endpoint_url`` lets the backend talk to R2 / B2 / MinIO -
  AWS-S3 callers leave it unset so boto3 picks the regional default.

Spec reference: ``2026-04-19-mnemo-v2-design.md`` section 4.4.
"""

from __future__ import annotations

import asyncio

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from mnemo_mcp.sync.base import SyncBackend


def _bundle_key(prefix: str, sequence: int) -> str:
    """Return the S3 object key for a passport bundle at ``sequence``."""
    return f"{prefix.rstrip('/')}/seq-{sequence:06d}.bin"


def _parse_sequence(key: str, prefix: str) -> int | None:
    """Extract the integer sequence from ``<prefix>/seq-NNNNNN.bin``."""
    expected_prefix = prefix.rstrip("/") + "/"
    if not key.startswith(expected_prefix):
        return None
    tail = key[len(expected_prefix) :]
    if not tail.startswith("seq-") or not tail.endswith(".bin"):
        return None
    middle = tail[len("seq-") : -len(".bin")]
    try:
        return int(middle)
    except ValueError:
        return None


class S3Backend(SyncBackend):
    """:class:`SyncBackend` over a generic S3 / R2 / B2 / MinIO bucket.

    The bucket is treated as a flat key/value store rooted at
    ``<prefix>/`` (default ``passport/``). Each bundle uploaded by
    :meth:`push` lands at ``<prefix>/seq-NNNNNN.bin``; :meth:`pull` and
    :meth:`last_remote_sequence` discover bundles via ``ListObjectsV2``
    over the same prefix.
    """

    name = "s3"

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint_url: str | None = None,
        prefix: str = "passport/",
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/"
        self._endpoint_url = endpoint_url
        self._client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    async def push(self, bundle: bytes, sequence: int) -> None:
        """Upload ``bundle`` to ``<prefix>/seq-NNNNNN.bin``."""
        key = _bundle_key(self._prefix, sequence)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=bundle,
            )
        except ClientError as e:
            logger.error(
                f"S3Backend.push: failed bucket={self._bucket} key={key} err={e}"
            )
            raise

    async def pull(self, sequence: int | None = None) -> bytes | None:
        """Fetch a bundle by ``sequence``, or the latest when ``None``."""
        if sequence is None:
            sequence = await self.last_remote_sequence()
            if sequence == 0:
                return None
        key = _bundle_key(self._prefix, sequence)
        try:
            resp = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            return resp["Body"].read()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                return None
            logger.error(
                f"S3Backend.pull: failed bucket={self._bucket} key={key} err={e}"
            )
            raise

    async def last_remote_sequence(self) -> int:
        """Return the highest sequence number stored under ``<prefix>/``.

        Returns 0 when the bucket / prefix is empty (fresh backend).
        Pagination is handled via ``ContinuationToken`` so very large
        bucket histories do not silently truncate.
        """
        max_seq = 0
        continuation: str | None = None
        while True:
            kwargs: dict = {"Bucket": self._bucket, "Prefix": self._prefix}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            try:
                resp = await asyncio.to_thread(self._client.list_objects_v2, **kwargs)
            except ClientError as e:
                logger.error(
                    f"S3Backend.last_remote_sequence: list failed "
                    f"bucket={self._bucket} prefix={self._prefix} err={e}"
                )
                raise
            for obj in resp.get("Contents", []):
                seq = _parse_sequence(obj["Key"], self._prefix)
                if seq is not None and seq > max_seq:
                    max_seq = seq
            if not resp.get("IsTruncated"):
                break
            continuation = resp.get("NextContinuationToken")
            if not continuation:
                break
        return max_seq

    async def health_check(self) -> bool:
        """Cheap probe: HeadBucket. Returns False on 403 / 404 / network."""
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
            return True
        except ClientError:
            return False
        except Exception:
            return False
