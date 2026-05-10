"""Tests for the Phase 2 S3 sync backend.

Uses ``moto[s3]`` for an in-memory S3 fixture so tests run offline /
deterministic. Real-bucket integration sits behind the ``integration``
marker (skipped by default per pyproject.toml addopts).

Covers:
- ``push`` writes to ``<prefix>/seq-NNNNNN.bin`` exactly.
- ``pull(sequence)`` returns the bytes at that sequence; ``pull(None)``
  returns the latest.
- ``last_remote_sequence`` returns max sequence + 0 when empty.
- Custom ``endpoint_url`` is forwarded to boto3 (R2 / B2 / MinIO path).
- ``health_check`` returns False on missing bucket / 403.
- Unrelated keys under the same prefix are ignored (not all objects
  follow the seq- naming convention).
"""

from __future__ import annotations

from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from mnemo_mcp.sync.s3 import S3Backend, _bundle_key, _parse_sequence

_BUCKET = "mnemo-test-bucket"
_PREFIX = "passport/"


@pytest.fixture
def s3_client() -> Iterator[object]:
    """Yield a moto-backed boto3 S3 client + create the test bucket."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        yield client


@pytest.fixture
def backend(s3_client) -> S3Backend:  # noqa: ARG001 - s3_client patches boto3
    return S3Backend(
        bucket=_BUCKET,
        region="us-east-1",
        access_key_id="testing",
        secret_access_key="testing",
        prefix=_PREFIX,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_bundle_key_format() -> None:
    assert _bundle_key("passport/", 1) == "passport/seq-000001.bin"
    assert _bundle_key("passport", 12345) == "passport/seq-012345.bin"
    # Strips trailing slashes consistently.
    assert _bundle_key("passport//", 7) == "passport/seq-000007.bin"


def test_parse_sequence_round_trip() -> None:
    assert _parse_sequence("passport/seq-000001.bin", "passport/") == 1
    assert _parse_sequence("passport/seq-999999.bin", "passport/") == 999999
    # Non-matching keys return None.
    assert _parse_sequence("other/seq-000001.bin", "passport/") is None
    assert _parse_sequence("passport/random.txt", "passport/") is None
    assert _parse_sequence("passport/seq-bad.bin", "passport/") is None


# ---------------------------------------------------------------------------
# push / pull / sequence discovery
# ---------------------------------------------------------------------------


async def test_s3_push_writes_correct_key(backend: S3Backend, s3_client) -> None:
    bundle = b"opaque-bundle-bytes"
    await backend.push(bundle, sequence=1)

    obj = s3_client.get_object(Bucket=_BUCKET, Key="passport/seq-000001.bin")
    assert obj["Body"].read() == bundle


async def test_s3_pull_returns_latest_when_sequence_none(backend: S3Backend) -> None:
    await backend.push(b"v1", sequence=1)
    await backend.push(b"v2", sequence=2)
    await backend.push(b"v3", sequence=3)

    latest = await backend.pull(sequence=None)
    assert latest == b"v3"


async def test_s3_pull_with_specific_sequence(backend: S3Backend) -> None:
    await backend.push(b"first", sequence=1)
    await backend.push(b"second", sequence=2)

    assert await backend.pull(sequence=1) == b"first"
    assert await backend.pull(sequence=2) == b"second"


async def test_s3_pull_missing_sequence_returns_none(backend: S3Backend) -> None:
    assert await backend.pull(sequence=99) is None


async def test_s3_pull_empty_bucket_returns_none(backend: S3Backend) -> None:
    assert await backend.pull(sequence=None) is None


async def test_s3_last_remote_sequence_with_no_objects(backend: S3Backend) -> None:
    assert await backend.last_remote_sequence() == 0


async def test_s3_last_remote_sequence_with_objects(backend: S3Backend) -> None:
    await backend.push(b"one", sequence=1)
    await backend.push(b"two", sequence=12)
    await backend.push(b"three", sequence=5)
    assert await backend.last_remote_sequence() == 12


async def test_s3_last_remote_sequence_ignores_non_bundle_keys(
    backend: S3Backend, s3_client
) -> None:
    """Random objects under the prefix do not break sequence detection."""
    await backend.push(b"only one", sequence=7)
    s3_client.put_object(Bucket=_BUCKET, Key="passport/manifest.txt", Body=b"junk")
    s3_client.put_object(Bucket=_BUCKET, Key="passport/seq-bad.bin", Body=b"junk")
    assert await backend.last_remote_sequence() == 7


async def test_s3_push_overwrites_same_sequence(backend: S3Backend, s3_client) -> None:
    await backend.push(b"v1", sequence=1)
    await backend.push(b"v2", sequence=1)
    obj = s3_client.get_object(Bucket=_BUCKET, Key="passport/seq-000001.bin")
    assert obj["Body"].read() == b"v2"


# ---------------------------------------------------------------------------
# health_check + endpoint propagation
# ---------------------------------------------------------------------------


async def test_s3_health_check_returns_true_on_existing_bucket(
    backend: S3Backend,
) -> None:
    assert await backend.health_check() is True


async def test_s3_health_check_returns_false_on_missing_bucket(s3_client) -> None:
    bad_backend = S3Backend(
        bucket="nonexistent-bucket-zzz",
        region="us-east-1",
        access_key_id="testing",
        secret_access_key="testing",
    )
    assert await bad_backend.health_check() is False


def test_s3_custom_endpoint_passed_to_boto3() -> None:
    """R2 / B2 / MinIO endpoint forwarded so boto3 hits the right host."""
    with mock_aws():
        backend = S3Backend(
            bucket="bucket",
            region="auto",
            access_key_id="k",
            secret_access_key="s",
            endpoint_url="https://accountid.r2.cloudflarestorage.com",
        )
        assert backend._client.meta.endpoint_url == (
            "https://accountid.r2.cloudflarestorage.com"
        )
