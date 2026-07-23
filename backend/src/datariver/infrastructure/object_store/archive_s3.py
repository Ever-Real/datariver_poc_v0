from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody

from datariver.application.errors import ExternalDependencyError
from datariver.domain.common import canonical_json_hash, uuid7
from datariver.domain.retention import (
    ArchiveCapability,
    ArchiveRetentionMode,
    ArchiveRetentionObservation,
    ArchiveWriteReceipt,
)

_MAXIMUM_EVIDENCE_BYTES = 1024 * 1024
_DENIED_CODES = frozenset({"AccessDenied"})


class S3ImmutableArchiveStore:
    """A dedicated COMPLIANCE Object-Lock boundary with no delete API."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        bucket: str,
        prefix: str,
        access_key: str,
        secret_key: str,
        encryption_profile_fingerprint: str,
        client: Any | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url.rstrip("/")
        self._region = region
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._encryption_profile_fingerprint = encryption_profile_fingerprint
        self._configuration_fingerprint = canonical_json_hash(
            {
                "contract": "S3_COMPLIANCE_ARCHIVE_V1",
                "endpoint_url": self._endpoint_url,
                "region": region,
                "bucket": bucket,
                "prefix": self._prefix,
                "encryption_profile_fingerprint": encryption_profile_fingerprint,
            }
        )
        configuration = Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=15,
            retries={"total_max_attempts": 1, "mode": "standard"},
            s3={"addressing_style": "path"},
        )
        self._client: Any = client or boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=configuration,
        )
        self._cached_capability: ArchiveCapability | None = None

    @property
    def configuration_fingerprint(self) -> str:
        return self._configuration_fingerprint

    async def verify_capability(self) -> ArchiveCapability:
        now = datetime.now(UTC)
        if self._cached_capability is not None and now < self._cached_capability.expires_at:
            return self._cached_capability
        try:
            versioning = await asyncio.to_thread(
                self._client.get_bucket_versioning, Bucket=self._bucket
            )
            object_lock = await asyncio.to_thread(
                self._client.get_object_lock_configuration, Bucket=self._bucket
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Archive bucket capability could not be read.", error) from error
        versioning_enabled = versioning.get("Status") == "Enabled"
        lock_configuration = object_lock.get("ObjectLockConfiguration", {})
        object_lock_enabled = lock_configuration.get("ObjectLockEnabled") == "Enabled"
        if not versioning_enabled or not object_lock_enabled:
            raise ExternalDependencyError(
                "Archive bucket does not provide versioning and Object Lock.",
                dependency="immutable_archive",
                retryable=False,
                provider_code="ARCHIVE_OBJECT_LOCK_NOT_ENABLED",
            )

        challenge = secrets.token_bytes(32)
        challenge_sha256 = hashlib.sha256(challenge).hexdigest()
        object_key = f"{self._prefix}/_capability-probes/{uuid7()}.bin"
        retain_until = now + timedelta(days=2)
        receipt = await self.write_archive(
            object_key=object_key,
            chunks=_one_chunk(challenge),
            size_bytes=len(challenge),
            sha256=challenge_sha256,
            retain_until=retain_until,
            metadata={"probe-contract": "archive-probe-v1"},
        )
        readback_sha256, readback_bytes = await self._readback_digest(
            object_key=object_key, version_id=receipt.object_version_id
        )
        retention = await self.read_retention(
            object_key=object_key, version_id=receipt.object_version_id
        )
        shorten_denied = await self._retention_shorten_is_denied(
            object_key=object_key,
            version_id=receipt.object_version_id,
            retain_until=now + timedelta(hours=1),
        )
        delete_denied = await self._retained_delete_is_denied(
            object_key=object_key, version_id=receipt.object_version_id
        )
        # S3 LastModified has whole-second precision. Use the same precision so a persisted
        # attestation can be compared to the provider's authoritative write timestamp later.
        observed_at = datetime.now(UTC).replace(microsecond=0)
        capability = ArchiveCapability(
            configuration_fingerprint=self._configuration_fingerprint,
            challenge_hash=challenge_sha256,
            observed_at=observed_at,
            expires_at=observed_at + timedelta(minutes=10),
            versioning_enabled=True,
            object_lock_enabled=True,
            compliance_retention_supported=(
                retention.retention_mode is ArchiveRetentionMode.COMPLIANCE
                and retention.retention_until == retain_until
            ),
            checksum_sha256_supported=receipt.content_sha256 == challenge_sha256,
            full_readback_verified=(
                readback_bytes == len(challenge) and readback_sha256 == challenge_sha256
            ),
            retention_shorten_denied=shorten_denied,
            retained_version_delete_denied=delete_denied,
        )
        capability.assert_usable(now=observed_at)
        self._cached_capability = capability
        return capability

    async def find_archive(
        self,
        *,
        object_key: str,
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        expected_metadata: dict[str, str],
    ) -> ArchiveWriteReceipt | None:
        """Read a deterministic locked version before any retrying PutObject."""
        self._validate_write(
            object_key=object_key,
            size_bytes=size_bytes,
            sha256=sha256,
            retain_until=retain_until,
            metadata=expected_metadata,
        )
        return await self._read_archive_receipt(
            object_key=object_key,
            expected_version_id=None,
            size_bytes=size_bytes,
            sha256=sha256,
            retain_until=retain_until,
            expected_metadata=expected_metadata,
            require_capability_attestation=True,
        )

    async def _read_archive_receipt(
        self,
        *,
        object_key: str,
        expected_version_id: str | None,
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        expected_metadata: dict[str, str],
        require_capability_attestation: bool,
    ) -> ArchiveWriteReceipt | None:
        request: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": object_key,
            "ChecksumMode": "ENABLED",
        }
        if expected_version_id is not None:
            request["VersionId"] = expected_version_id
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                **request,
            )
        except ClientError as error:
            if _provider_code(error) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise self._error("Immutable archive lookup failed.", error) from error
        except BotoCoreError as error:
            raise self._error("Immutable archive lookup failed.", error) from error
        version_id = str(response.get("VersionId") or "")
        provider_checksum = str(response.get("ChecksumSHA256") or "")
        last_modified = response.get("LastModified")
        metadata = response.get("Metadata")
        expected_checksum = base64.b64encode(bytes.fromhex(sha256)).decode("ascii")
        byte_count = response.get("ContentLength")
        if (
            not version_id
            or provider_checksum != expected_checksum
            or not isinstance(byte_count, int)
            or byte_count != size_bytes
            or not isinstance(last_modified, datetime)
            or last_modified.tzinfo is None
            or not isinstance(metadata, dict)
            or (expected_version_id is not None and version_id != expected_version_id)
            or any(metadata.get(key) != value for key, value in expected_metadata.items())
        ):
            raise ExternalDependencyError(
                "Existing immutable archive evidence does not match its deterministic command.",
                dependency="immutable_archive",
                retryable=False,
                provider_code="ARCHIVE_EXISTING_EVIDENCE_MISMATCH",
            )
        write_interval_start = last_modified.astimezone(UTC).replace(microsecond=0)
        retention = await self.read_retention(object_key=object_key, version_id=version_id)
        if (
            retention.retention_mode is not ArchiveRetentionMode.COMPLIANCE
            or retention.retention_until != retain_until
        ):
            raise ExternalDependencyError(
                "Existing immutable archive retention does not match its command.",
                dependency="immutable_archive",
                retryable=False,
                provider_code="ARCHIVE_EXISTING_RETENTION_MISMATCH",
            )
        return ArchiveWriteReceipt(
            object_bucket=self._bucket,
            object_key=object_key,
            object_version_id=version_id,
            byte_count=byte_count,
            content_sha256=sha256,
            provider_checksum=provider_checksum,
            retention_mode=ArchiveRetentionMode.COMPLIANCE,
            retention_until=retention.retention_until,
            legal_hold=retention.legal_hold,
            observed_at=write_interval_start,
            capability_attestation_id=_capability_attestation_id(
                metadata, required=require_capability_attestation
            ),
        )

    async def write_archive(
        self,
        *,
        object_key: str,
        chunks: AsyncIterator[bytes],
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        metadata: dict[str, str],
    ) -> ArchiveWriteReceipt:
        self._validate_write(
            object_key=object_key,
            size_bytes=size_bytes,
            sha256=sha256,
            retain_until=retain_until,
            metadata=metadata,
        )
        content = bytearray()
        async for chunk in chunks:
            content.extend(chunk)
            if len(content) > _MAXIMUM_EVIDENCE_BYTES:
                raise ValueError("Immutable evidence exceeds the one MiB execution bound.")
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if len(content) != size_bytes or actual_sha256 != sha256:
            raise ValueError("Immutable evidence size or checksum does not match its command.")
        encoded_checksum = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
        try:
            response = await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=object_key,
                Body=bytes(content),
                ContentLength=size_bytes,
                ContentType="application/x-ndjson",
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=encoded_checksum,
                Metadata=metadata,
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=retain_until,
                IfNoneMatch="*",
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error(
                "Immutable archive object could not be written.",
                error,
                ambiguous_commit=_write_may_have_committed(error),
            ) from error
        version_id = str(response.get("VersionId") or "")
        if not version_id:
            raise ExternalDependencyError(
                "Archive provider did not return the required object version.",
                dependency="immutable_archive",
                retryable=False,
                provider_code="ARCHIVE_WRITE_EVIDENCE_INCOMPLETE",
                ambiguous_commit=True,
            )
        try:
            receipt = await self._read_archive_receipt(
                object_key=object_key,
                expected_version_id=version_id,
                size_bytes=size_bytes,
                sha256=sha256,
                retain_until=retain_until,
                expected_metadata=metadata,
                require_capability_attestation="capability-attestation-id" in metadata,
            )
        except ExternalDependencyError as error:
            raise ExternalDependencyError(
                "Archive write committed but its exact version read-back failed.",
                dependency="immutable_archive",
                retryable=bool(error.details.get("retryable", False)),
                provider_code=str(error.details.get("provider_code") or error.code),
                ambiguous_commit=True,
            ) from error
        if receipt is None:
            raise ExternalDependencyError(
                "Archive write committed without immediately readable version evidence.",
                dependency="immutable_archive",
                retryable=False,
                provider_code="ARCHIVE_WRITE_READBACK_PENDING",
                ambiguous_commit=True,
            )
        return receipt

    async def iter_archive_chunks(
        self, *, object_key: str, version_id: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        if not 64 * 1024 <= chunk_size <= 1024 * 1024:
            raise ValueError("Immutable archive read chunk size is outside the safe range.")
        self._validate_object_key(object_key)
        body: StreamingBody | Any | None = None
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=object_key,
                VersionId=version_id,
                ChecksumMode="ENABLED",
            )
            body = response["Body"]
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield bytes(chunk)
        except (BotoCoreError, ClientError) as error:
            raise self._error("Immutable archive readback failed.", error) from error
        finally:
            if body is not None:
                await asyncio.to_thread(body.close)

    async def read_retention(
        self, *, object_key: str, version_id: str
    ) -> ArchiveRetentionObservation:
        self._validate_object_key(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object_retention,
                Bucket=self._bucket,
                Key=object_key,
                VersionId=version_id,
            )
            legal_hold = await asyncio.to_thread(
                self._client.get_object_legal_hold,
                Bucket=self._bucket,
                Key=object_key,
                VersionId=version_id,
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Immutable archive retention could not be read.", error) from error
        retention = response.get("Retention", {})
        mode = str(retention.get("Mode") or "")
        retain_until = retention.get("RetainUntilDate")
        if mode != "COMPLIANCE" or not isinstance(retain_until, datetime):
            raise ExternalDependencyError(
                "Archive retention readback is incomplete.",
                dependency="immutable_archive",
                retryable=False,
                provider_code="ARCHIVE_RETENTION_EVIDENCE_INCOMPLETE",
            )
        return ArchiveRetentionObservation(
            retention_mode=ArchiveRetentionMode.COMPLIANCE,
            retention_until=retain_until,
            legal_hold=legal_hold.get("LegalHold", {}).get("Status") == "ON",
            observed_at=datetime.now(UTC),
        )

    async def _readback_digest(self, *, object_key: str, version_id: str) -> tuple[str, int]:
        digest = hashlib.sha256()
        byte_count = 0
        async for chunk in self.iter_archive_chunks(
            object_key=object_key, version_id=version_id, chunk_size=64 * 1024
        ):
            byte_count += len(chunk)
            digest.update(chunk)
        return digest.hexdigest(), byte_count

    async def _retention_shorten_is_denied(
        self, *, object_key: str, version_id: str, retain_until: datetime
    ) -> bool:
        try:
            await asyncio.to_thread(
                self._client.put_object_retention,
                Bucket=self._bucket,
                Key=object_key,
                VersionId=version_id,
                Retention={"Mode": "COMPLIANCE", "RetainUntilDate": retain_until},
            )
        except ClientError as error:
            return _provider_code(error) in _DENIED_CODES
        except BotoCoreError as error:
            raise self._error("Archive retention denial probe failed.", error) from error
        return False

    async def _retained_delete_is_denied(self, *, object_key: str, version_id: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=object_key,
                VersionId=version_id,
            )
        except ClientError as error:
            return _provider_code(error) in _DENIED_CODES
        except BotoCoreError as error:
            raise self._error("Archive retained-delete denial probe failed.", error) from error
        return False

    def _validate_write(
        self,
        *,
        object_key: str,
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        metadata: dict[str, str],
    ) -> None:
        self._validate_object_key(object_key)
        if not 1 <= size_bytes <= _MAXIMUM_EVIDENCE_BYTES:
            raise ValueError("Immutable evidence size is outside the one MiB execution bound.")
        if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError("Immutable evidence checksum must be lowercase SHA-256.")
        if retain_until.tzinfo is None or retain_until <= datetime.now(UTC):
            raise ValueError("Immutable evidence retention deadline must be in the future.")
        if len(metadata) > 16 or any(
            not key or len(key) > 64 or len(value) > 512 for key, value in metadata.items()
        ):
            raise ValueError("Immutable evidence metadata exceeds its bounded contract.")

    def _validate_object_key(self, object_key: str) -> None:
        if (
            not object_key.startswith(f"{self._prefix}/")
            or len(object_key) > 1024
            or ".." in object_key.split("/")
            or "//" in object_key
        ):
            raise ValueError("Immutable archive object key is outside the configured prefix.")

    @staticmethod
    def _error(
        message: str, error: BaseException, *, ambiguous_commit: bool = False
    ) -> ExternalDependencyError:
        provider_code = "S3_ARCHIVE_ERROR"
        retryable = True
        if isinstance(error, ClientError):
            provider_code = _provider_code(error)
            retryable = provider_code in {
                "InternalError",
                "RequestTimeout",
                "ServiceUnavailable",
                "SlowDown",
            }
        return ExternalDependencyError(
            message,
            dependency="immutable_archive",
            retryable=retryable,
            provider_code=provider_code,
            ambiguous_commit=ambiguous_commit,
        )


def _provider_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", "S3_ARCHIVE_ERROR"))


def _write_may_have_committed(error: BaseException) -> bool:
    return isinstance(error, (BotoCoreError, ClientError))


def _capability_attestation_id(metadata: dict[str, Any], *, required: bool = True) -> UUID | None:
    raw_value = metadata.get("capability-attestation-id")
    if raw_value is None and not required:
        return None
    try:
        return UUID(str(raw_value))
    except (TypeError, ValueError) as error:
        raise ExternalDependencyError(
            "Archive object is missing its exact capability attestation binding.",
            dependency="immutable_archive",
            retryable=False,
            provider_code="ARCHIVE_CAPABILITY_ATTESTATION_INVALID",
        ) from error


async def _one_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content
