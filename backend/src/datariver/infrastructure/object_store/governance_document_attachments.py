from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody

from datariver.application.governance_document_attachments import (
    GovernanceDocumentAttachmentCollisionError,
    GovernanceDocumentAttachmentExternalError,
    GovernanceDocumentAttachmentReceipt,
    GovernanceDocumentAttachmentWrite,
    governance_document_attachment_key,
)

_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_CONFLICT_CODES = frozenset({"ConditionalRequestConflict", "PreconditionFailed"})
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
_RETRYABLE_CODES = frozenset({"InternalError", "RequestTimeout", "ServiceUnavailable", "SlowDown"})
_CONTENT_TYPE = "application/octet-stream"


class S3GovernanceDocumentAttachmentStore:
    """Create-only S3 adapter for one version-owned governance document attachment."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        client: Any | None = None,
    ) -> None:
        if _BUCKET_PATTERN.fullmatch(bucket) is None:
            raise ValueError("Governance document attachment bucket name is not S3-portable.")
        self._bucket = bucket
        configuration = Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=15,
            retries={"total_max_attempts": 1, "mode": "standard"},
            s3={"addressing_style": "path"},
        )
        self._client: Any = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url.rstrip("/"),
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=configuration,
        )

    async def ensure_attachment(
        self,
        write: GovernanceDocumentAttachmentWrite,
    ) -> GovernanceDocumentAttachmentReceipt:
        object_key = governance_document_attachment_key(
            workspace_id=write.workspace_id,
            document_id=write.document_id,
            version_id=write.version_id,
            attachment_id=write.attachment_id,
        )
        digest = write.content_sha256
        provider_checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
        metadata = {
            "contract": "governance-document-attachment-v1",
            "workspace-id": str(write.workspace_id),
            "document-id": str(write.document_id),
            "document-version-id": str(write.version_id),
            "attachment-id": str(write.attachment_id),
            "classification": write.classification,
            "content-sha256": digest,
            "size-bytes": str(len(write.content)),
        }
        try:
            response = await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=object_key,
                Body=write.content,
                ContentLength=len(write.content),
                ContentType=_CONTENT_TYPE,
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=provider_checksum,
                IfNoneMatch="*",
                Metadata=metadata,
            )
        except ClientError as error:
            provider_code = _provider_code(error)
            status = int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if provider_code in _CONFLICT_CODES or status in {409, 412}:
                return await self._reconcile_collision(
                    object_key=object_key,
                    content=write.content,
                    metadata=metadata,
                    provider_checksum=provider_checksum,
                    collision_provider_code=provider_code,
                )
            raise _external_error(
                "Governance document attachment write outcome is ambiguous.",
                error=error,
                ambiguous_commit=True,
            ) from error
        except BotoCoreError as error:
            raise _external_error(
                "Governance document attachment write outcome is ambiguous.",
                error=error,
                ambiguous_commit=True,
            ) from error

        version_id = str(response.get("VersionId") or "")
        if not version_id:
            raise GovernanceDocumentAttachmentExternalError(
                "Governance document attachment provider omitted the committed object version.",
                retryable=False,
                provider_code="GOVERNANCE_DOCUMENT_ATTACHMENT_VERSION_ID_MISSING",
                ambiguous_commit=True,
            )
        return await self._read_exact(
            object_key=object_key,
            version_id=version_id,
            content=write.content,
            metadata=metadata,
            provider_checksum=provider_checksum,
            mismatch_is_collision=False,
        )

    async def _reconcile_collision(
        self,
        *,
        object_key: str,
        content: bytes,
        metadata: dict[str, str],
        provider_checksum: str,
        collision_provider_code: str,
    ) -> GovernanceDocumentAttachmentReceipt:
        try:
            head = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=object_key,
                ChecksumMode="ENABLED",
            )
        except ClientError as error:
            if _provider_code(error) in _NOT_FOUND_CODES:
                raise GovernanceDocumentAttachmentCollisionError(
                    provider_code=collision_provider_code
                ) from error
            raise _external_error(
                "Governance document attachment collision could not be reconciled.",
                error=error,
                ambiguous_commit=False,
            ) from error
        except BotoCoreError as error:
            raise _external_error(
                "Governance document attachment collision could not be reconciled.",
                error=error,
                ambiguous_commit=False,
            ) from error

        version_id = str(head.get("VersionId") or "")
        if not version_id:
            raise GovernanceDocumentAttachmentCollisionError(
                provider_code="GOVERNANCE_DOCUMENT_ATTACHMENT_EXISTING_VERSION_ID_MISSING"
            )
        return await self._read_exact(
            object_key=object_key,
            version_id=version_id,
            content=content,
            metadata=metadata,
            provider_checksum=provider_checksum,
            mismatch_is_collision=True,
        )

    async def _read_exact(
        self,
        *,
        object_key: str,
        version_id: str,
        content: bytes,
        metadata: dict[str, str],
        provider_checksum: str,
        mismatch_is_collision: bool,
    ) -> GovernanceDocumentAttachmentReceipt:
        try:
            head = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=object_key,
                VersionId=version_id,
                ChecksumMode="ENABLED",
            )
        except (BotoCoreError, ClientError) as error:
            raise _external_error(
                "Governance document attachment exact-version metadata read-back failed.",
                error=error,
                ambiguous_commit=not mismatch_is_collision,
            ) from error

        etag = str(head.get("ETag") or "").strip('"')
        observed_checksum = str(head.get("ChecksumSHA256") or "")
        observed_metadata = {
            str(key).lower(): str(value) for key, value in (head.get("Metadata") or {}).items()
        }
        if (
            str(head.get("VersionId") or "") != version_id
            or head.get("ContentLength") != len(content)
            or str(head.get("ContentType") or "") != _CONTENT_TYPE
            or not etag
            or observed_checksum != provider_checksum
            or observed_metadata != metadata
        ):
            _raise_mismatch(mismatch_is_collision=mismatch_is_collision)

        body: StreamingBody | Any | None = None
        digest = hashlib.sha256()
        byte_count = 0
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=object_key,
                VersionId=version_id,
                ChecksumMode="ENABLED",
            )
            if (
                str(response.get("VersionId") or "") != version_id
                or str(response.get("ChecksumSHA256") or "") != provider_checksum
            ):
                _raise_mismatch(mismatch_is_collision=mismatch_is_collision)
            body = response["Body"]
            while True:
                chunk = await asyncio.to_thread(body.read, 64 * 1024)
                if not chunk:
                    break
                byte_count += len(chunk)
                if byte_count > len(content):
                    break
                digest.update(chunk)
        except (BotoCoreError, ClientError, KeyError) as error:
            raise _external_error(
                "Governance document attachment exact-version content read-back failed.",
                error=error,
                ambiguous_commit=not mismatch_is_collision,
            ) from error
        finally:
            if body is not None:
                await asyncio.to_thread(body.close)

        expected_digest = hashlib.sha256(content).hexdigest()
        if byte_count != len(content) or digest.hexdigest() != expected_digest:
            _raise_mismatch(mismatch_is_collision=mismatch_is_collision)
        return GovernanceDocumentAttachmentReceipt(
            bucket=self._bucket,
            object_key=object_key,
            provider_version_id=version_id,
            etag=etag,
            provider_checksum=observed_checksum,
            size_bytes=byte_count,
            content_sha256=digest.hexdigest(),
            metadata=observed_metadata,
        )


def _raise_mismatch(*, mismatch_is_collision: bool) -> None:
    if mismatch_is_collision:
        raise GovernanceDocumentAttachmentCollisionError(
            provider_code="GOVERNANCE_DOCUMENT_ATTACHMENT_EXISTING_OBJECT_MISMATCH"
        )
    raise GovernanceDocumentAttachmentExternalError(
        "Governance document attachment failed exact-version verification.",
        retryable=False,
        provider_code="GOVERNANCE_DOCUMENT_ATTACHMENT_READBACK_MISMATCH",
        ambiguous_commit=True,
    )


def _provider_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", "S3_ERROR"))


def _external_error(
    message: str,
    *,
    error: BaseException,
    ambiguous_commit: bool,
) -> GovernanceDocumentAttachmentExternalError:
    provider_code = "S3_ERROR"
    retryable = True
    if isinstance(error, ClientError):
        provider_code = _provider_code(error)
        retryable = provider_code in _RETRYABLE_CODES
    return GovernanceDocumentAttachmentExternalError(
        message,
        retryable=retryable,
        provider_code=provider_code,
        ambiguous_commit=ambiguous_commit,
    )
