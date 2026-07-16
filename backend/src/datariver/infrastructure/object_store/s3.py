from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import CompletedPartTypeDef

from datariver.application.dto import (
    CatalogExportArtifact,
    MultipartUpload,
    ObjectMetadata,
)
from datariver.application.errors import ExternalDependencyError
from datariver.domain.common import ValidationError
from datariver.domain.registration import CompletedUploadPart


class S3ObjectStore:
    def __init__(
        self,
        *,
        endpoint_url: str,
        public_endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        configuration = Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=15,
            retries={"max_attempts": 2, "mode": "standard"},
            s3={"addressing_style": "path"},
        )
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=configuration,
        )
        self._presign_client: S3Client = boto3.client(
            "s3",
            endpoint_url=public_endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=configuration,
        )

    async def create_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str,
        metadata: dict[str, str],
    ) -> MultipartUpload:
        try:
            response = await asyncio.to_thread(
                self._client.create_multipart_upload,
                Bucket=bucket,
                Key=object_key,
                ContentType=content_type,
                Metadata=metadata,
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Object upload could not be initiated.", error) from error
        return MultipartUpload(
            upload_id=str(response["UploadId"]), bucket=bucket, object_key=object_key
        )

    async def ensure_bucket(self, *, bucket: str, allowed_origins: Sequence[str]) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=bucket)
        except BotoCoreError as error:
            raise self._error("Object bucket availability could not be checked.", error) from error
        except ClientError as error:
            provider_code = str(error.response.get("Error", {}).get("Code", ""))
            status = int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if provider_code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
                raise self._error(
                    "Object bucket availability could not be checked.", error
                ) from error
            try:
                await asyncio.to_thread(self._client.create_bucket, Bucket=bucket)
            except (BotoCoreError, ClientError) as create_error:
                raise self._error(
                    "Object bucket could not be created.", create_error
                ) from create_error
        try:
            await asyncio.to_thread(
                self._client.put_bucket_cors,
                Bucket=bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedHeaders": ["*"],
                            "AllowedMethods": ["GET", "HEAD", "PUT"],
                            "AllowedOrigins": list(allowed_origins),
                            "ExposeHeaders": ["ETag", "x-amz-checksum-sha256"],
                            "MaxAgeSeconds": 600,
                        }
                    ]
                },
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Object bucket CORS policy could not be applied.", error) from error

    async def presign_upload_part(
        self,
        *,
        upload: MultipartUpload,
        part_number: int,
        expires_seconds: int,
        checksum_sha256: str | None = None,
    ) -> str:
        if not 1 <= part_number <= 10_000:
            raise ValueError("Multipart part number must be between 1 and 10000.")
        if not 60 <= expires_seconds <= 900:
            raise ValueError("Presigned upload URL lifetime must be between 60 and 900 seconds.")
        parameters: dict[str, Any] = {
            "Bucket": upload.bucket,
            "Key": upload.object_key,
            "UploadId": upload.upload_id,
            "PartNumber": part_number,
        }
        if checksum_sha256:
            parameters["ChecksumSHA256"] = checksum_sha256
        try:
            return await asyncio.to_thread(
                partial(
                    self._presign_client.generate_presigned_url,
                    "upload_part",
                    Params=parameters,
                    ExpiresIn=expires_seconds,
                    HttpMethod="PUT",
                )
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Upload URL could not be created.", error) from error

    async def complete_multipart_upload(
        self, *, upload: MultipartUpload, parts: Sequence[CompletedUploadPart]
    ) -> ObjectMetadata:
        if not parts or len(parts) > 10_000:
            raise ValueError("Multipart completion must contain between 1 and 10000 parts.")
        ordered = sorted(parts, key=lambda item: item.part_number)
        if len({part.part_number for part in ordered}) != len(ordered):
            raise ValueError("Multipart completion contains duplicate part numbers.")
        payload: list[CompletedPartTypeDef] = []
        for part in ordered:
            document: CompletedPartTypeDef = {
                "PartNumber": part.part_number,
                "ETag": part.etag,
            }
            if part.checksum_sha256:
                document["ChecksumSHA256"] = part.checksum_sha256
            payload.append(document)
        try:
            await asyncio.to_thread(
                self._client.complete_multipart_upload,
                Bucket=upload.bucket,
                Key=upload.object_key,
                UploadId=upload.upload_id,
                MultipartUpload={"Parts": payload},
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Object upload could not be completed.", error) from error
        return await self.head_object(bucket=upload.bucket, object_key=upload.object_key)

    async def abort_multipart_upload(self, *, upload: MultipartUpload) -> None:
        try:
            await asyncio.to_thread(
                self._client.abort_multipart_upload,
                Bucket=upload.bucket,
                Key=upload.object_key,
                UploadId=upload.upload_id,
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Object upload could not be aborted.", error) from error

    async def write_export(
        self,
        *,
        bucket: str,
        object_key: str,
        chunks: AsyncIterator[bytes],
        metadata: dict[str, str],
        maximum_bytes: int,
    ) -> CatalogExportArtifact:
        if not 1 <= maximum_bytes <= 5 * 1024 * 1024 * 1024:
            raise ValueError("Catalog export byte limit is outside the safe range.")
        upload = await self.create_multipart_upload(
            bucket=bucket,
            object_key=object_key,
            content_type="text/csv; charset=utf-8",
            metadata=metadata,
        )
        digest = hashlib.sha256()
        buffer = bytearray()
        total = 0
        parts: list[CompletedUploadPart] = []
        part_size = 8 * 1024 * 1024
        try:
            async for chunk in chunks:
                total += len(chunk)
                if total > maximum_bytes:
                    raise ValidationError(
                        "The catalog export exceeds the configured byte limit.",
                        details={"code": "EXPORT_BYTE_LIMIT"},
                    )
                digest.update(chunk)
                buffer.extend(chunk)
                while len(buffer) >= part_size:
                    part = bytes(buffer[:part_size])
                    del buffer[:part_size]
                    parts.append(
                        await self._upload_export_part(
                            upload=upload,
                            part_number=len(parts) + 1,
                            content=part,
                        )
                    )
            if buffer or not parts:
                parts.append(
                    await self._upload_export_part(
                        upload=upload,
                        part_number=len(parts) + 1,
                        content=bytes(buffer),
                    )
                )
            object_metadata = await self.complete_multipart_upload(upload=upload, parts=parts)
        except Exception:
            try:
                await self.abort_multipart_upload(upload=upload)
            except ExternalDependencyError:
                pass
            try:
                await self.delete_object(bucket=bucket, object_key=object_key)
            except ExternalDependencyError:
                pass
            raise
        if object_metadata.size_bytes != total:
            try:
                await self.delete_object(bucket=bucket, object_key=object_key)
            except ExternalDependencyError:
                pass
            raise ExternalDependencyError(
                "Catalog export object size did not reconcile.",
                dependency="object_store",
                retryable=True,
                provider_code="EXPORT_SIZE_MISMATCH",
            )
        return CatalogExportArtifact(
            size_bytes=total,
            content_sha256=digest.hexdigest(),
            provider_checksum=(f"etag:{object_metadata.etag}" if object_metadata.etag else None),
        )

    async def delete_export(self, *, bucket: str, object_key: str) -> None:
        await self.delete_object(bucket=bucket, object_key=object_key)

    async def _upload_export_part(
        self,
        *,
        upload: MultipartUpload,
        part_number: int,
        content: bytes,
    ) -> CompletedUploadPart:
        if not 1 <= part_number <= 10_000:
            raise ValidationError(
                "The catalog export exceeds the multipart part limit.",
                details={"code": "EXPORT_PART_LIMIT"},
            )
        try:
            response = await asyncio.to_thread(
                self._client.upload_part,
                Bucket=upload.bucket,
                Key=upload.object_key,
                UploadId=upload.upload_id,
                PartNumber=part_number,
                Body=content,
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Catalog export part could not be uploaded.", error) from error
        return CompletedUploadPart(
            part_number=part_number,
            etag=str(response["ETag"]).strip('"'),
        )

    async def head_object(self, *, bucket: str, object_key: str) -> ObjectMetadata:
        try:
            response = await asyncio.to_thread(
                self._client.head_object, Bucket=bucket, Key=object_key
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Object metadata could not be read.", error) from error
        return ObjectMetadata(
            bucket=bucket,
            object_key=object_key,
            size_bytes=int(response["ContentLength"]),
            content_type=str(response.get("ContentType", "application/octet-stream")),
            etag=str(response.get("ETag", "")).strip('"'),
            checksum_sha256=response.get("ChecksumSHA256"),
            user_metadata={
                str(key): str(value) for key, value in response.get("Metadata", {}).items()
            },
        )

    async def presign_download(
        self,
        *,
        bucket: str,
        object_key: str,
        download_name: str,
        expires_seconds: int,
    ) -> str:
        if not 60 <= expires_seconds <= 900:
            raise ValueError("Presigned download URL lifetime must be between 60 and 900 seconds.")
        safe_name = download_name.replace('"', "").replace("\r", "").replace("\n", "")[:500]
        try:
            return await asyncio.to_thread(
                partial(
                    self._presign_client.generate_presigned_url,
                    "get_object",
                    Params={
                        "Bucket": bucket,
                        "Key": object_key,
                        "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
                    },
                    ExpiresIn=expires_seconds,
                    HttpMethod="GET",
                )
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Download URL could not be created.", error) from error

    async def iter_object_chunks(
        self, *, bucket: str, object_key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        if not 64 * 1024 <= chunk_size <= 8 * 1024 * 1024:
            raise ValueError("Object stream chunk size is outside the safe range.")
        body: StreamingBody | None = None
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=bucket, Key=object_key
            )
            body = response["Body"]
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield bytes(chunk)
        except (BotoCoreError, ClientError) as error:
            raise self._error("Object content could not be streamed.", error) from error
        finally:
            if body is not None:
                await asyncio.to_thread(body.close)

    async def copy_object(
        self,
        *,
        source_bucket: str,
        source_key: str,
        destination_bucket: str,
        destination_key: str,
    ) -> ObjectMetadata:
        try:
            await asyncio.to_thread(
                self._client.copy_object,
                Bucket=destination_bucket,
                Key=destination_key,
                CopySource={"Bucket": source_bucket, "Key": source_key},
                MetadataDirective="COPY",
            )
        except (BotoCoreError, ClientError) as error:
            raise self._error("Validated object could not be promoted.", error) from error
        return await self.head_object(bucket=destination_bucket, object_key=destination_key)

    async def delete_object(self, *, bucket: str, object_key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=bucket, Key=object_key)
        except (BotoCoreError, ClientError) as error:
            raise self._error("Object cleanup could not be completed.", error) from error

    @staticmethod
    def _error(message: str, error: BaseException) -> ExternalDependencyError:
        provider_code = "S3_ERROR"
        retryable = True
        if isinstance(error, ClientError):
            provider_code = str(error.response.get("Error", {}).get("Code", provider_code))
            retryable = provider_code in {
                "InternalError",
                "RequestTimeout",
                "ServiceUnavailable",
                "SlowDown",
            }
        return ExternalDependencyError(
            message,
            dependency="object_store",
            retryable=retryable,
            provider_code=provider_code,
        )
