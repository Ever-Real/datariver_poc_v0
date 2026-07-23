from __future__ import annotations

import asyncio
import os
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError

from datariver.application.dto import CatalogExportArtifact
from datariver.domain.common import ConflictError
from datariver.infrastructure.object_store.s3 import S3ObjectStore

_ENABLED = os.getenv("DATARIVER_S3_RECEIPT_TEST_ENABLED") == "1"
pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason="Set DATARIVER_S3_RECEIPT_TEST_ENABLED=1 for the isolated live S3 gate.",
)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for the live S3 receipt gate.")
    return value


@pytest.mark.asyncio
async def test_live_s3_immutable_receipt_is_create_only_and_fully_read_back() -> None:
    endpoint = _required("DATARIVER_S3_RECEIPT_TEST_ENDPOINT")
    bucket = _required("DATARIVER_S3_RECEIPT_TEST_BUCKET")
    if not bucket.startswith("datariver-live-test-"):
        raise RuntimeError("The live S3 gate requires an isolated datariver-live-test-* bucket.")
    access_key = (
        Path(_required("DATARIVER_S3_RECEIPT_TEST_ACCESS_KEY_FILE"))
        .read_text(encoding="utf-8")
        .strip()
    )
    secret_key = (
        Path(_required("DATARIVER_S3_RECEIPT_TEST_SECRET_KEY_FILE"))
        .read_text(encoding="utf-8")
        .strip()
    )
    region = os.getenv("DATARIVER_S3_RECEIPT_TEST_REGION", "us-east-1")
    store = S3ObjectStore(
        endpoint_url=endpoint,
        public_endpoint_url=endpoint,
        region=region,
        access_key=access_key,
        secret_key=secret_key,
    )
    cleanup = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    object_key = "manual-receipts/concurrent.csv"
    content = b"asset_urn,description\nurn:li:dataset:test,verified\n"
    bucket_created = False
    try:
        try:
            await asyncio.to_thread(cleanup.head_bucket, Bucket=bucket)
        except ClientError as error:
            status = int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if status != 404:
                raise
        else:
            raise RuntimeError("The isolated live S3 test bucket already exists.")
        await store.ensure_bucket(bucket=bucket, allowed_origins=(), manage_cors=False)
        bucket_created = True
        outcomes = await asyncio.gather(
            *(
                store.write_immutable_receipt(
                    bucket=bucket,
                    object_key=object_key,
                    content=content,
                    metadata={"contract": "manual-metadata-v1"},
                    maximum_bytes=1024,
                )
                for _ in range(2)
            ),
            return_exceptions=True,
        )
        artifacts = [value for value in outcomes if isinstance(value, CatalogExportArtifact)]
        conflicts = [value for value in outcomes if isinstance(value, ConflictError)]
        assert len(artifacts) == 1
        assert len(conflicts) == 1
        assert artifacts[0].size_bytes == len(content)
        assert len(artifacts[0].content_sha256) == 64

        readback = bytearray()
        async for chunk in store.iter_object_chunks(
            bucket=bucket,
            object_key=object_key,
            chunk_size=64 * 1024,
        ):
            readback.extend(chunk)
        assert bytes(readback) == content
    finally:
        if bucket_created:
            try:
                await store.delete_object(bucket=bucket, object_key=object_key)
            finally:
                await asyncio.to_thread(cleanup.delete_bucket, Bucket=bucket)
