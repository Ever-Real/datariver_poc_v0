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

from datariver.application.governance_document_artifacts import (
    GovernanceDocumentArtifactCollisionError,
    GovernanceDocumentArtifactReceipt,
    GovernanceDocumentArtifactStage,
    GovernanceDocumentArtifactWrite,
    GovernanceDocumentObjectReceipt,
    governance_document_artifact_keys,
)

_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_CONFLICT_CODES = frozenset({"ConditionalRequestConflict", "PreconditionFailed"})
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
_RETRYABLE_CODES = frozenset({"InternalError", "RequestTimeout", "ServiceUnavailable", "SlowDown"})


class S3GovernanceDocumentArtifactStore:
    """Version-pinned, create-only storage for governance document HTML and manifests."""

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
            raise ValueError("Governance document bucket name is not S3-portable.")
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

    async def ensure_version_artifacts(
        self,
        write: GovernanceDocumentArtifactWrite,
    ) -> GovernanceDocumentArtifactReceipt:
        keys = governance_document_artifact_keys(
            workspace_id=write.workspace_id,
            document_id=write.document_id,
            version_id=write.version_id,
        )
        common_metadata = {
            "contract": "governance-document-artifact-v1",
            "workspace-id": str(write.workspace_id),
            "document-id": str(write.document_id),
            "document-version-id": str(write.version_id),
            "document-version-number": str(write.version_number),
            "document-version-tag": write.version_tag,
            "sanitizer-policy-version": write.sanitizer_policy_version,
            "sanitizer-policy-sha256": write.sanitizer_policy_sha256,
            "classification": write.classification,
            "content-sha256": write.content_sha256,
            "manifest-sha256": write.manifest_sha256,
        }
        content = await self._write_one(
            stage=GovernanceDocumentArtifactStage.CONTENT,
            object_key=keys.content_key,
            content=write.content_html,
            content_type="application/octet-stream",
            metadata={**common_metadata, "artifact-kind": "content"},
            content_committed=False,
        )
        manifest = await self._write_one(
            stage=GovernanceDocumentArtifactStage.MANIFEST,
            object_key=keys.manifest_key,
            content=write.manifest_json,
            content_type="application/json",
            metadata={**common_metadata, "artifact-kind": "manifest"},
            content_committed=True,
        )
        return GovernanceDocumentArtifactReceipt(content=content, manifest=manifest)

    async def _write_one(
        self,
        *,
        stage: GovernanceDocumentArtifactStage,
        object_key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
        content_committed: bool,
    ) -> GovernanceDocumentObjectReceipt:
        digest = hashlib.sha256(content).hexdigest()
        expected_metadata = {**metadata, "artifact-sha256": digest}
        provider_checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
        try:
            response = await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=object_key,
                Body=content,
                ContentLength=len(content),
                ContentType=content_type,
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=provider_checksum,
                IfNoneMatch="*",
                Metadata=expected_metadata,
            )
        except ClientError as error:
            provider_code = _provider_code(error)
            status = int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if provider_code in _CONFLICT_CODES or status in {409, 412}:
                return await self._reconcile_collision(
                    stage=stage,
                    object_key=object_key,
                    content=content,
                    content_type=content_type,
                    expected_metadata=expected_metadata,
                    expected_provider_checksum=provider_checksum,
                    content_committed=content_committed,
                    collision_provider_code=provider_code,
                )
            raise _external_error(
                "Governance document artifact write outcome is ambiguous.",
                error=error,
                stage=stage,
                ambiguous_commit=True,
                content_committed=content_committed,
            ) from error
        except BotoCoreError as error:
            raise _external_error(
                "Governance document artifact write outcome is ambiguous.",
                error=error,
                stage=stage,
                ambiguous_commit=True,
                content_committed=content_committed,
            ) from error

        version_id = str(response.get("VersionId") or "")
        if not version_id:
            raise _structured_external_error(
                "Governance document provider omitted the committed object version.",
                stage=stage,
                retryable=False,
                provider_code="GOVERNANCE_DOCUMENT_VERSION_ID_MISSING",
                ambiguous_commit=True,
                content_committed=content_committed,
            )
        return await self._read_exact(
            stage=stage,
            object_key=object_key,
            version_id=version_id,
            content=content,
            content_type=content_type,
            expected_metadata=expected_metadata,
            expected_provider_checksum=provider_checksum,
            content_committed=content_committed,
            mismatch_is_collision=False,
        )

    async def _reconcile_collision(
        self,
        *,
        stage: GovernanceDocumentArtifactStage,
        object_key: str,
        content: bytes,
        content_type: str,
        expected_metadata: dict[str, str],
        expected_provider_checksum: str,
        content_committed: bool,
        collision_provider_code: str,
    ) -> GovernanceDocumentObjectReceipt:
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=object_key,
                ChecksumMode="ENABLED",
            )
        except ClientError as error:
            if _provider_code(error) in _NOT_FOUND_CODES:
                raise GovernanceDocumentArtifactCollisionError(
                    stage=stage,
                    content_committed=content_committed,
                    provider_code=collision_provider_code,
                ) from error
            raise _external_error(
                "Governance document artifact collision could not be reconciled.",
                error=error,
                stage=stage,
                ambiguous_commit=False,
                content_committed=content_committed,
            ) from error
        except BotoCoreError as error:
            raise _external_error(
                "Governance document artifact collision could not be reconciled.",
                error=error,
                stage=stage,
                ambiguous_commit=False,
                content_committed=content_committed,
            ) from error
        version_id = str(response.get("VersionId") or "")
        if not version_id:
            raise GovernanceDocumentArtifactCollisionError(
                stage=stage,
                content_committed=content_committed,
                provider_code="GOVERNANCE_DOCUMENT_EXISTING_VERSION_ID_MISSING",
            )
        return await self._read_exact(
            stage=stage,
            object_key=object_key,
            version_id=version_id,
            content=content,
            content_type=content_type,
            expected_metadata=expected_metadata,
            expected_provider_checksum=expected_provider_checksum,
            content_committed=content_committed,
            mismatch_is_collision=True,
        )

    async def _read_exact(
        self,
        *,
        stage: GovernanceDocumentArtifactStage,
        object_key: str,
        version_id: str,
        content: bytes,
        content_type: str,
        expected_metadata: dict[str, str],
        expected_provider_checksum: str,
        content_committed: bool,
        mismatch_is_collision: bool,
    ) -> GovernanceDocumentObjectReceipt:
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
                "Governance document exact-version metadata read-back failed.",
                error=error,
                stage=stage,
                ambiguous_commit=not mismatch_is_collision,
                content_committed=content_committed,
            ) from error

        etag = str(head.get("ETag") or "").strip('"')
        observed_checksum = str(head.get("ChecksumSHA256") or "")
        observed_metadata = {
            str(key).lower(): str(value) for key, value in (head.get("Metadata") or {}).items()
        }
        mismatch = (
            str(head.get("VersionId") or "") != version_id
            or head.get("ContentLength") != len(content)
            or str(head.get("ContentType") or "") != content_type
            or not etag
            or observed_checksum != expected_provider_checksum
            or observed_metadata != expected_metadata
        )
        if mismatch:
            self._raise_mismatch(
                stage=stage,
                content_committed=content_committed,
                mismatch_is_collision=mismatch_is_collision,
            )

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
                or str(response.get("ChecksumSHA256") or "") != expected_provider_checksum
            ):
                self._raise_mismatch(
                    stage=stage,
                    content_committed=content_committed,
                    mismatch_is_collision=mismatch_is_collision,
                )
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
                "Governance document exact-version content read-back failed.",
                error=error,
                stage=stage,
                ambiguous_commit=not mismatch_is_collision,
                content_committed=content_committed,
            ) from error
        finally:
            if body is not None:
                await asyncio.to_thread(body.close)

        if byte_count != len(content) or digest.hexdigest() != hashlib.sha256(content).hexdigest():
            self._raise_mismatch(
                stage=stage,
                content_committed=content_committed,
                mismatch_is_collision=mismatch_is_collision,
            )
        return GovernanceDocumentObjectReceipt(
            bucket=self._bucket,
            object_key=object_key,
            provider_version_id=version_id,
            etag=etag,
            provider_checksum=observed_checksum,
            size_bytes=byte_count,
            content_sha256=digest.hexdigest(),
            metadata=observed_metadata,
        )

    @staticmethod
    def _raise_mismatch(
        *,
        stage: GovernanceDocumentArtifactStage,
        content_committed: bool,
        mismatch_is_collision: bool,
    ) -> None:
        if mismatch_is_collision:
            raise GovernanceDocumentArtifactCollisionError(
                stage=stage,
                content_committed=content_committed,
                provider_code="GOVERNANCE_DOCUMENT_EXISTING_OBJECT_MISMATCH",
            )
        raise _structured_external_error(
            "Governance document committed artifact failed exact-version verification.",
            stage=stage,
            retryable=False,
            provider_code="GOVERNANCE_DOCUMENT_ARTIFACT_READBACK_MISMATCH",
            ambiguous_commit=True,
            content_committed=content_committed,
        )


def _provider_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", "S3_ERROR"))


def _external_error(
    message: str,
    *,
    error: BaseException,
    stage: GovernanceDocumentArtifactStage,
    ambiguous_commit: bool,
    content_committed: bool,
) -> Exception:
    provider_code = "S3_ERROR"
    retryable = True
    if isinstance(error, ClientError):
        provider_code = _provider_code(error)
        retryable = provider_code in _RETRYABLE_CODES
    return _structured_external_error(
        message,
        stage=stage,
        retryable=retryable,
        provider_code=provider_code,
        ambiguous_commit=ambiguous_commit,
        content_committed=content_committed,
    )


def _structured_external_error(
    message: str,
    *,
    stage: GovernanceDocumentArtifactStage,
    retryable: bool,
    provider_code: str,
    ambiguous_commit: bool,
    content_committed: bool,
) -> Exception:
    from datariver.application.governance_document_artifacts import (
        GovernanceDocumentArtifactExternalError,
    )

    return GovernanceDocumentArtifactExternalError(
        message,
        stage=stage,
        retryable=retryable,
        provider_code=provider_code,
        ambiguous_commit=ambiguous_commit,
        content_committed=content_committed,
    )
