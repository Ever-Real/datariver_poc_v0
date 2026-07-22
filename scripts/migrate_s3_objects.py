from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TRANSFER = TransferConfig(
    multipart_threshold=8 * 1024 * 1024,
    multipart_chunksize=8 * 1024 * 1024,
    max_concurrency=1,
    use_threads=False,
)


@dataclass(frozen=True)
class ManifestObject:
    bucket: str
    key: str
    size_bytes: int
    sha256: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy only PostgreSQL-manifest-owned objects between S3-compatible endpoints. "
            "The command never deletes source or target objects and refuses target mismatches."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-endpoint", required=True)
    parser.add_argument("--target-endpoint", required=True)
    parser.add_argument("--source-access-key-file", type=Path, required=True)
    parser.add_argument("--source-secret-key-file", type=Path, required=True)
    parser.add_argument("--target-access-key-file", type=Path)
    parser.add_argument("--target-secret-key-file", type=Path)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--temporary-directory", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Upload absent verified objects. Without this flag the command performs a full dry run."
        ),
    )
    return parser


def _endpoint(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("S3 endpoints must be credential-free absolute HTTP(S) origins.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("S3 endpoints cannot contain a path, query or fragment.")
    return value.rstrip("/")


def _secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Secret file is empty: {path}")
    return value


def load_manifest(path: Path) -> tuple[ManifestObject, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("Migration manifest must use schema_version 1.")
    for field in ("reference_count", "object_count", "malformed_count", "conflict_count"):
        value = raw.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Migration manifest {field} must be a non-negative integer.")
    if raw["malformed_count"] != 0:
        raise ValueError("Migration manifest contains malformed database references.")
    if raw["conflict_count"] != 0:
        raise ValueError("Migration manifest contains conflicting object evidence.")
    raw_objects = raw.get("objects")
    if not isinstance(raw_objects, list):
        raise ValueError("Migration manifest objects must be a list.")
    if raw["object_count"] != len(raw_objects):
        raise ValueError("Migration manifest object_count does not match objects.")
    if raw["reference_count"] < raw["object_count"]:
        raise ValueError("Migration manifest reference_count is smaller than object_count.")
    objects: list[ManifestObject] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_objects):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest object {index} must be a mapping.")
        bucket = item.get("bucket")
        key = item.get("key")
        size_bytes = item.get("size_bytes")
        digest = item.get("sha256")
        if not isinstance(bucket, str) or not bucket or any(ord(char) < 32 for char in bucket):
            raise ValueError(f"Manifest object {index} has an invalid bucket.")
        if not isinstance(key, str) or not key or any(ord(char) < 32 for char in key):
            raise ValueError(f"Manifest object {index} has an invalid key.")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
            raise ValueError(f"Manifest object {index} has an invalid size.")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError(f"Manifest object {index} has an invalid SHA-256.")
        identity = (bucket, key)
        if identity in seen:
            raise ValueError(f"Migration manifest contains a duplicate object: {bucket}/{key}")
        seen.add(identity)
        objects.append(ManifestObject(bucket=bucket, key=key, size_bytes=size_bytes, sha256=digest))
    return tuple(objects)


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


def _head(client: S3Client, item: ManifestObject) -> dict[str, Any] | None:
    try:
        return dict(client.head_object(Bucket=item.bucket, Key=item.key))
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        status = int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return None
        raise


def _stream_to_file_and_hash(
    client: S3Client,
    item: ManifestObject,
    destination: Path,
) -> tuple[int, str]:
    response = client.get_object(Bucket=item.bucket, Key=item.key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := body.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    finally:
        body.close()
    return size, digest.hexdigest()


def _stream_hash(client: S3Client, item: ManifestObject) -> tuple[int, str]:
    response = client.get_object(Bucket=item.bucket, Key=item.key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    return size, digest.hexdigest()


def _require_expected(item: ManifestObject, observed: tuple[int, str], *, location: str) -> None:
    if observed != (item.size_bytes, item.sha256):
        raise ValueError(
            f"{location} object does not match PostgreSQL manifest: {item.bucket}/{item.key}"
        )


def migrate_objects(
    *,
    source: S3Client,
    target: S3Client,
    objects: Sequence[ManifestObject],
    apply: bool,
    temporary_directory: Path | None,
) -> dict[str, int]:
    buckets = sorted({item.bucket for item in objects})
    for bucket in buckets:
        source.head_bucket(Bucket=bucket)
        target.head_bucket(Bucket=bucket)

    counts = {"verified_source": 0, "verified_existing": 0, "copied": 0, "planned": 0}
    for item in objects:
        source_head = _head(source, item)
        if source_head is None:
            raise ValueError(f"Source object is missing: {item.bucket}/{item.key}")
        if int(source_head.get("ContentLength", -1)) != item.size_bytes:
            raise ValueError(f"Source HEAD size mismatch: {item.bucket}/{item.key}")

        with tempfile.NamedTemporaryFile(
            prefix="datariver-s3-migration-",
            dir=temporary_directory,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            _require_expected(
                item,
                _stream_to_file_and_hash(source, item, temporary_path),
                location="Source",
            )
            counts["verified_source"] += 1

            target_head = _head(target, item)
            if target_head is not None:
                _require_expected(item, _stream_hash(target, item), location="Target")
                counts["verified_existing"] += 1
                continue
            if not apply:
                counts["planned"] += 1
                continue

            extra_args: dict[str, Any] = {}
            content_type = source_head.get("ContentType")
            metadata = source_head.get("Metadata")
            if isinstance(content_type, str) and content_type:
                extra_args["ContentType"] = content_type
            if isinstance(metadata, dict) and metadata:
                extra_args["Metadata"] = {str(key): str(value) for key, value in metadata.items()}
            target.upload_file(
                str(temporary_path),
                item.bucket,
                item.key,
                ExtraArgs=extra_args or None,
                Config=_TRANSFER,
            )
            _require_expected(item, _stream_hash(target, item), location="Target")
            counts["copied"] += 1
        finally:
            temporary_path.unlink(missing_ok=True)
    return counts


def main() -> None:
    arguments = _parser().parse_args()
    target_access_key_file = arguments.target_access_key_file or arguments.source_access_key_file
    target_secret_key_file = arguments.target_secret_key_file or arguments.source_secret_key_file
    objects = load_manifest(arguments.manifest)
    source = _client(
        endpoint=arguments.source_endpoint,
        region=arguments.region,
        access_key=_secret(arguments.source_access_key_file),
        secret_key=_secret(arguments.source_secret_key_file),
    )
    target = _client(
        endpoint=arguments.target_endpoint,
        region=arguments.region,
        access_key=_secret(target_access_key_file),
        secret_key=_secret(target_secret_key_file),
    )
    counts = migrate_objects(
        source=source,
        target=target,
        objects=objects,
        apply=arguments.apply,
        temporary_directory=arguments.temporary_directory,
    )
    print(json.dumps({"apply": arguments.apply, **counts}, sort_keys=True))


if __name__ == "__main__":
    main()
