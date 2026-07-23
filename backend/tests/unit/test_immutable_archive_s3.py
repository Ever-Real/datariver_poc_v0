import base64
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from datariver.application.errors import ExternalDependencyError
from datariver.infrastructure.object_store.archive_s3 import S3ImmutableArchiveStore


class _Body:
    def __init__(self, content: bytes) -> None:
        self._stream = BytesIO(content)

    def read(self, size: int) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()


class _LockedS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.destructive_probe_calls = 0
        self.head_requests: list[dict[str, Any]] = []

    def get_bucket_versioning(self, **kwargs: Any) -> dict[str, str]:
        assert kwargs["Bucket"] == "immutable-audit"
        return {"Status": "Enabled"}

    def get_object_lock_configuration(self, **kwargs: Any) -> dict[str, object]:
        assert kwargs["Bucket"] == "immutable-audit"
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        assert kwargs["IfNoneMatch"] == "*"
        if any(key == str(kwargs["Key"]) for key, _version in self.objects):
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        content = bytes(kwargs["Body"])
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
        assert kwargs["ChecksumSHA256"] == checksum
        key = (str(kwargs["Key"]), "version-1")
        self.objects[key] = {
            "content": content,
            "retain_until": kwargs["ObjectLockRetainUntilDate"],
            "metadata": kwargs["Metadata"],
            "checksum": checksum,
            "last_modified": datetime.now(UTC).replace(microsecond=0),
        }
        return {"VersionId": "version-1", "ChecksumSHA256": checksum}

    def get_object(self, **kwargs: Any) -> dict[str, object]:
        value = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {"Body": _Body(value["content"]), "ChecksumSHA256": value["checksum"]}

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        self.head_requests.append(dict(kwargs))
        matches = [
            (version, value)
            for (key, version), value in self.objects.items()
            if key == str(kwargs["Key"])
        ]
        if not matches:
            raise ClientError({"Error": {"Code": "404", "Message": "missing"}}, "HeadObject")
        version, value = matches[-1]
        return {
            "VersionId": version,
            "ContentLength": len(value["content"]),
            "ChecksumSHA256": value["checksum"],
            "Metadata": value["metadata"],
            "LastModified": value["last_modified"],
        }

    def get_object_retention(self, **kwargs: Any) -> dict[str, object]:
        value = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {"Retention": {"Mode": "COMPLIANCE", "RetainUntilDate": value["retain_until"]}}

    def get_object_legal_hold(self, **kwargs: Any) -> dict[str, object]:
        del kwargs
        return {"LegalHold": {"Status": "OFF"}}

    def put_object_retention(self, **kwargs: Any) -> None:
        del kwargs
        self.destructive_probe_calls += 1
        raise _access_denied("PutObjectRetention")

    def delete_object(self, **kwargs: Any) -> None:
        del kwargs
        self.destructive_probe_calls += 1
        raise _access_denied("DeleteObject")


def _access_denied(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, operation)


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content[:3]
    yield content[3:]


@pytest.mark.asyncio
async def test_capability_probe_requires_real_compliance_denials_and_is_cached() -> None:
    client = _LockedS3Client()
    store = S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="secret",
        encryption_profile_fingerprint="a" * 64,
        client=client,
    )

    first = await store.verify_capability()
    second = await store.verify_capability()

    first.assert_usable(now=datetime.now(UTC))
    assert first == second
    probe = next(
        value for (key, _version), value in client.objects.items() if "_capability-probes" in key
    )
    assert first.challenge_hash == hashlib.sha256(probe["content"]).hexdigest()
    assert client.destructive_probe_calls == 2
    assert first.retention_shorten_denied
    assert first.retained_version_delete_denied


@pytest.mark.asyncio
async def test_archive_write_and_full_versioned_readback_are_exact() -> None:
    client = _LockedS3Client()
    store = S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="secret",
        encryption_profile_fingerprint="a" * 64,
        client=client,
    )
    content = b"immutable evidence\n"
    digest = hashlib.sha256(content).hexdigest()
    retain_until = datetime.now(UTC) + timedelta(days=365)
    attestation_id = uuid4()

    receipt = await store.write_archive(
        object_key="evidence/workspace/job/1/evidence.jsonl",
        chunks=_chunks(content),
        size_bytes=len(content),
        sha256=digest,
        retain_until=retain_until,
        metadata={
            "command-hash": "b" * 64,
            "capability-attestation-id": str(attestation_id),
        },
    )
    readback = bytearray()
    async for chunk in store.iter_archive_chunks(
        object_key=receipt.object_key,
        version_id=receipt.object_version_id,
        chunk_size=64 * 1024,
    ):
        readback.extend(chunk)
    retention = await store.read_retention(
        object_key=receipt.object_key, version_id=receipt.object_version_id
    )

    assert bytes(readback) == content
    assert receipt.content_sha256 == digest
    assert receipt.provider_checksum == base64.b64encode(bytes.fromhex(digest)).decode("ascii")
    assert receipt.retention_until == retain_until
    assert receipt.observed_at.microsecond == 0
    assert receipt.capability_attestation_id == attestation_id
    assert any(
        request.get("VersionId") == receipt.object_version_id for request in client.head_requests
    )
    assert retention.retention_until == retain_until

    recovered = await store.find_archive(
        object_key=receipt.object_key,
        size_bytes=len(content),
        sha256=digest,
        retain_until=retain_until,
        expected_metadata={
            "command-hash": "b" * 64,
            "capability-attestation-id": str(attestation_id),
        },
    )
    assert recovered is not None
    assert recovered.object_version_id == receipt.object_version_id
    assert recovered.capability_attestation_id == attestation_id
    with pytest.raises(ExternalDependencyError) as duplicate:
        await store.write_archive(
            object_key=receipt.object_key,
            chunks=_chunks(content),
            size_bytes=len(content),
            sha256=digest,
            retain_until=retain_until,
            metadata={
                "command-hash": "b" * 64,
                "capability-attestation-id": str(attestation_id),
            },
        )
    assert duplicate.value.details["provider_code"] == "PreconditionFailed"
    assert sum(key == receipt.object_key for key, _version in client.objects) == 1
    assert (
        await store.find_archive(
            object_key="evidence/workspace/job/missing.jsonl",
            size_bytes=len(content),
            sha256=digest,
            retain_until=retain_until,
            expected_metadata={"command-hash": "b" * 64},
        )
        is None
    )


@pytest.mark.asyncio
async def test_archive_write_rejects_unbounded_or_mismatched_payload_before_provider_call() -> None:
    client = _LockedS3Client()
    store = S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="secret",
        encryption_profile_fingerprint="a" * 64,
        client=client,
    )

    with pytest.raises(ValueError, match="checksum"):
        await store.write_archive(
            object_key="evidence/workspace/job/1/evidence.jsonl",
            chunks=_chunks(b"content"),
            size_bytes=7,
            sha256="f" * 64,
            retain_until=datetime.now(UTC) + timedelta(days=1),
            metadata={},
        )
    assert not client.objects


@pytest.mark.asyncio
async def test_archive_lookup_rejects_missing_exact_capability_binding() -> None:
    client = _LockedS3Client()
    store = S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="secret",
        encryption_profile_fingerprint="a" * 64,
        client=client,
    )
    content = b"unbound immutable evidence\n"
    digest = hashlib.sha256(content).hexdigest()
    retain_until = datetime.now(UTC) + timedelta(days=365)
    receipt = await store.write_archive(
        object_key="evidence/workspace/job/unbound/evidence.jsonl",
        chunks=_chunks(content),
        size_bytes=len(content),
        sha256=digest,
        retain_until=retain_until,
        metadata={"command-hash": "b" * 64},
    )
    assert receipt.capability_attestation_id is None

    with pytest.raises(ExternalDependencyError) as missing:
        await store.find_archive(
            object_key=receipt.object_key,
            size_bytes=len(content),
            sha256=digest,
            retain_until=retain_until,
            expected_metadata={"command-hash": "b" * 64},
        )
    assert missing.value.details["provider_code"] == "ARCHIVE_CAPABILITY_ATTESTATION_INVALID"


def test_archive_client_configuration_disables_automatic_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    client = _LockedS3Client()

    def client_factory(*args: Any, **kwargs: Any) -> _LockedS3Client:
        del args
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        "datariver.infrastructure.object_store.archive_s3.boto3.client", client_factory
    )
    S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="secret",
        encryption_profile_fingerprint="a" * 64,
    )

    assert captured["config"].retries["total_max_attempts"] == 1
