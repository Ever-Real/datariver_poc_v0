from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe a non-production S3-compatible endpoint with temporary objects, then clean "
            "them up. Credentials are accepted only through files."
        )
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--public-endpoint", required=True)
    parser.add_argument("--access-key-file", required=True, type=Path)
    parser.add_argument("--secret-key-file", required=True, type=Path)
    parser.add_argument("--quarantine-bucket", required=True)
    parser.add_argument("--accepted-bucket", required=True)
    parser.add_argument("--allowed-origin", required=True)
    parser.add_argument("--region", default="us-east-1")
    return parser


def _endpoint(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("S3 endpoints must be credential-free absolute HTTP(S) origins.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("S3 endpoints must not contain a path, query or fragment.")
    return value.rstrip("/")


def _secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Secret file is empty: {path}")
    return value


def _client(*, endpoint: str, region: str, access_key: str, secret_key: str) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=_endpoint(endpoint),
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=30,
            retries={"max_attempts": 2, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


def _http(request: Request) -> tuple[int, dict[str, str]]:
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - validated local/private URL
            return response.status, {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as error:
        try:
            return error.code, {key.lower(): value for key, value in error.headers.items()}
        finally:
            error.close()


def _object_bytes(client: S3Client, *, bucket: str, key: str) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        return bytes(body.read())
    finally:
        body.close()


def probe(
    *,
    client: S3Client,
    public_endpoint: str,
    quarantine_bucket: str,
    accepted_bucket: str,
    allowed_origin: str,
) -> dict[str, Any]:
    public_origin = _endpoint(public_endpoint)
    client.head_bucket(Bucket=quarantine_bucket)
    client.head_bucket(Bucket=accepted_bucket)

    run_id = secrets.token_hex(12)
    prefix = f"datariver-contract-probe/{run_id}"
    presigned_key = f"{prefix}/presigned.bin"
    multipart_key = f"{prefix}/multipart.bin"
    copied_key = f"{prefix}/copied.bin"
    cleanup = (
        (quarantine_bucket, presigned_key),
        (quarantine_bucket, multipart_key),
        (accepted_bucket, copied_key),
    )
    cleanup_errors: list[str] = []
    try:
        anonymous_status, _ = _http(
            Request(  # noqa: S310 - public_origin is validated by _endpoint
                f"{public_origin}/{quote(accepted_bucket, safe='')}", method="HEAD"
            )
        )
        if anonymous_status not in {401, 403}:
            raise RuntimeError(f"Anonymous bucket access was not denied: HTTP {anonymous_status}")

        presigned_value = b"datariver-presigned-contract-probe-v1"
        presigned_sha256 = hashlib.sha256(presigned_value).hexdigest()
        presigned_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": quarantine_bucket,
                "Key": presigned_key,
                "ContentType": "application/octet-stream",
                "Metadata": {"sha256": presigned_sha256},
            },
            ExpiresIn=60,
        )
        presigned_status, _ = _http(
            Request(  # noqa: S310 - boto3 generated from the validated endpoint
                presigned_url,
                data=presigned_value,
                method="PUT",
                headers={
                    "Content-Type": "application/octet-stream",
                    "x-amz-meta-sha256": presigned_sha256,
                },
            )
        )
        if presigned_status not in {200, 204}:
            raise RuntimeError(f"Presigned PUT failed: HTTP {presigned_status}")
        if _object_bytes(client, bucket=quarantine_bucket, key=presigned_key) != presigned_value:
            raise RuntimeError("Presigned PUT read-back mismatch.")

        multipart_value = b"m" * (5 * 1024 * 1024 + 17)
        multipart_sha256 = hashlib.sha256(multipart_value).hexdigest()
        initiated = client.create_multipart_upload(
            Bucket=quarantine_bucket,
            Key=multipart_key,
            ContentType="application/octet-stream",
            Metadata={"sha256": multipart_sha256},
        )
        upload_id = str(initiated["UploadId"])
        try:
            part = client.upload_part(
                Bucket=quarantine_bucket,
                Key=multipart_key,
                PartNumber=1,
                UploadId=upload_id,
                Body=multipart_value,
            )
            client.complete_multipart_upload(
                Bucket=quarantine_bucket,
                Key=multipart_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": [{"ETag": str(part["ETag"]), "PartNumber": 1}]},
            )
        except Exception:
            client.abort_multipart_upload(
                Bucket=quarantine_bucket,
                Key=multipart_key,
                UploadId=upload_id,
            )
            raise
        if _object_bytes(client, bucket=quarantine_bucket, key=multipart_key) != multipart_value:
            raise RuntimeError("Multipart upload read-back mismatch.")

        client.copy_object(
            Bucket=accepted_bucket,
            Key=copied_key,
            CopySource={"Bucket": quarantine_bucket, "Key": multipart_key},
            MetadataDirective="COPY",
        )
        copied_value = _object_bytes(client, bucket=accepted_bucket, key=copied_key)
        if hashlib.sha256(copied_value).hexdigest() != multipart_sha256:
            raise RuntimeError("Server-side copy SHA-256 mismatch.")

        cors_status, cors_headers = _http(
            Request(  # noqa: S310 - public_origin is validated by _endpoint
                f"{public_origin}/{quote(quarantine_bucket, safe='')}/{quote(presigned_key)}",
                method="OPTIONS",
                headers={
                    "Origin": allowed_origin,
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": "content-type,x-amz-meta-sha256",
                },
            )
        )
        if cors_status != 204 or cors_headers.get("access-control-allow-origin") != allowed_origin:
            raise RuntimeError("CORS preflight did not return the exact allowed origin.")

        return {
            "anonymous_denied": True,
            "authenticated_buckets": 2,
            "presigned_put_verified": True,
            "multipart_bytes_verified": len(multipart_value),
            "server_side_copy_verified": True,
            "cors_origin_verified": allowed_origin,
        }
    finally:
        for bucket, key in cleanup:
            try:
                client.delete_object(Bucket=bucket, Key=key)
            except Exception as error:  # pragma: no cover - runtime cleanup evidence
                cleanup_errors.append(f"{bucket}/{key}: {type(error).__name__}")
        if cleanup_errors:
            raise RuntimeError(f"S3 probe cleanup failed: {', '.join(cleanup_errors)}")


def main() -> None:
    arguments = _parser().parse_args()
    client = _client(
        endpoint=arguments.endpoint,
        region=arguments.region,
        access_key=_secret(arguments.access_key_file),
        secret_key=_secret(arguments.secret_key_file),
    )
    result = probe(
        client=client,
        public_endpoint=arguments.public_endpoint,
        quarantine_bucket=arguments.quarantine_bucket,
        accepted_bucket=arguments.accepted_bucket,
        allowed_origin=arguments.allowed_origin,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
