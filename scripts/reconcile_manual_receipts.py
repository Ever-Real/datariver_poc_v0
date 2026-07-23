from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MANUAL_KEY = re.compile(r"UPLOAD_METADATA_MANUAL_[0-9]{6}_([0-9]{6})\.csv\Z")
_EXPECTED_METADATA_KEYS = frozenset(
    {
        "workspace-id",
        "asset-id",
        "submission-id",
        "serial-number",
        "content-sha256",
        "content-size",
        "source-version",
        "provider-source-version",
        "content-kind",
    }
)
_MAXIMUM_OBJECTS = 1_000
_MAXIMUM_TOTAL_BYTES = 1024 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DatabaseReference:
    submission_id: str
    asset_id: str
    serial_number: int
    key: str
    size_bytes: int
    sha256: str
    source_version: str
    provider_source_version: str


@dataclass(frozen=True)
class DatabaseManifest:
    workspace_id: str
    bucket: str
    prefix: str
    total_reference_count: int
    database_truncated: bool
    references: tuple[DatabaseReference, ...]


@dataclass(frozen=True)
class ListedObject:
    key: str
    size_bytes: int


@dataclass(frozen=True)
class ReceiptMetadata:
    workspace_id: str
    asset_id: str
    submission_id: str
    serial_number: int
    content_sha256: str
    content_size: int
    source_version: str
    provider_source_version: str


@dataclass(frozen=True)
class VerifiedObject:
    key: str
    listed_size: int
    observed_size: int | None
    observed_sha256: str | None
    metadata: ReceiptMetadata | None
    metadata_raw: Mapping[str, str]
    evidence_errors: tuple[str, ...]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only reconciliation of a bounded Manual-registration receipt prefix against "
            "a PostgreSQL manifest. The command only reports evidence; it never changes objects "
            "or database records."
        )
    )
    parser.add_argument("--database-manifest", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--access-key-file", type=Path, required=True)
    parser.add_argument("--secret-key-file", type=Path, required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--maximum-objects", type=int, default=_MAXIMUM_OBJECTS)
    parser.add_argument("--maximum-total-bytes", type=int, default=64 * 1024 * 1024)
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


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping.")
    return cast(Mapping[str, object], value)


def _string(
    value: object,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"{field} is invalid.")
    return value


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{field} is invalid.")
    return value


def _uuid(value: object, *, field: str) -> str:
    candidate = _string(value, field=field, maximum=36)
    try:
        canonical = str(UUID(candidate))
    except ValueError as error:
        raise ValueError(f"{field} is invalid.") from error
    if canonical != candidate:
        raise ValueError(f"{field} must use canonical UUID notation.")
    return canonical


def _sha256(value: object, *, field: str) -> str:
    candidate = _string(value, field=field, maximum=64)
    if _SHA256.fullmatch(candidate) is None:
        raise ValueError(f"{field} is invalid.")
    return candidate


def _reference(raw: object, *, index: int, prefix: str) -> DatabaseReference:
    item = _mapping(raw, field=f"references[{index}]")
    key = _string(item.get("key"), field=f"references[{index}].key", maximum=1_024)
    if not key.startswith(prefix) or key.startswith("/"):
        raise ValueError(f"references[{index}].key is outside the manifest prefix.")
    return DatabaseReference(
        submission_id=_uuid(item.get("submission_id"), field=f"references[{index}].submission_id"),
        asset_id=_uuid(item.get("asset_id"), field=f"references[{index}].asset_id"),
        serial_number=_integer(
            item.get("serial_number"),
            field=f"references[{index}].serial_number",
            minimum=1,
        ),
        key=key,
        size_bytes=_integer(
            item.get("size_bytes"), field=f"references[{index}].size_bytes", minimum=1
        ),
        sha256=_sha256(item.get("sha256"), field=f"references[{index}].sha256"),
        source_version=_string(
            item.get("source_version"),
            field=f"references[{index}].source_version",
            maximum=255,
        ),
        provider_source_version=_sha256(
            item.get("provider_source_version"),
            field=f"references[{index}].provider_source_version",
        ),
    )


def load_database_manifest(path: Path) -> DatabaseManifest:
    raw = _mapping(json.loads(path.read_text(encoding="utf-8")), field="manifest")
    if raw.get("schema_version") != 1:
        raise ValueError("Database manifest must use schema_version 1.")
    workspace_id = _uuid(raw.get("workspace_id"), field="workspace_id")
    bucket = _string(raw.get("bucket"), field="bucket", maximum=255)
    prefix = _string(raw.get("prefix"), field="prefix", maximum=1_024)
    total_reference_count = _integer(
        raw.get("total_reference_count"), field="total_reference_count"
    )
    database_truncated = raw.get("database_truncated")
    if not isinstance(database_truncated, bool):
        raise ValueError("database_truncated must be a boolean.")
    raw_references = raw.get("references")
    if not isinstance(raw_references, list) or len(raw_references) > _MAXIMUM_OBJECTS:
        raise ValueError("references must be a list of at most 1000 records.")
    references = tuple(
        _reference(item, index=index, prefix=prefix) for index, item in enumerate(raw_references)
    )
    keys = [reference.key for reference in references]
    submission_ids = [reference.submission_id for reference in references]
    serial_numbers = [reference.serial_number for reference in references]
    if (
        len(set(keys)) != len(keys)
        or len(set(submission_ids)) != len(submission_ids)
        or len(set(serial_numbers)) != len(serial_numbers)
    ):
        raise ValueError("Database manifest contains duplicate reference identity.")
    if database_truncated:
        if total_reference_count <= len(references):
            raise ValueError("Database manifest truncation evidence is inconsistent.")
    elif total_reference_count != len(references):
        raise ValueError("Database manifest reference count is inconsistent.")
    return DatabaseManifest(
        workspace_id=workspace_id,
        bucket=bucket,
        prefix=prefix,
        total_reference_count=total_reference_count,
        database_truncated=database_truncated,
        references=references,
    )


def _scan_prefix(
    *,
    client: S3Client,
    bucket: str,
    prefix: str,
    maximum_objects: int,
) -> tuple[tuple[ListedObject, ...], bool, tuple[str, ...]]:
    objects: list[ListedObject] = []
    seen_keys: set[str] = set()
    seen_tokens: set[str] = set()
    continuation_token: str | None = None
    while len(objects) < maximum_objects:
        remaining = maximum_objects - len(objects)
        parameters: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": remaining,
        }
        if continuation_token is not None:
            parameters["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**parameters)
        raw_contents = response.get("Contents", [])
        if not isinstance(raw_contents, list):
            return tuple(objects), True, ("S3_LIST_MALFORMED",)
        for raw_item in raw_contents:
            if not isinstance(raw_item, dict):
                return tuple(objects), True, ("S3_LIST_MALFORMED",)
            key = raw_item.get("Key")
            size = raw_item.get("Size")
            if (
                not isinstance(key, str)
                or not key.startswith(prefix)
                or key.startswith("/")
                or len(key) > 1_024
                or any(ord(char) < 32 or ord(char) == 127 for char in key)
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or key in seen_keys
            ):
                return tuple(objects), True, ("S3_LIST_MALFORMED_OR_REPEATED",)
            seen_keys.add(key)
            objects.append(ListedObject(key=key, size_bytes=size))
            if len(objects) == maximum_objects:
                break
        is_truncated = response.get("IsTruncated")
        if not isinstance(is_truncated, bool):
            return tuple(objects), True, ("S3_LIST_MALFORMED",)
        if not is_truncated:
            return tuple(objects), False, ()
        next_token = response.get("NextContinuationToken")
        if (
            len(objects) == maximum_objects
            or not isinstance(next_token, str)
            or not next_token
            or next_token in seen_tokens
        ):
            return tuple(objects), True, ("S3_TRUNCATED",)
        seen_tokens.add(next_token)
        continuation_token = next_token
    return tuple(objects), True, ("S3_TRUNCATED",)


def _metadata(raw: object, *, key: str) -> tuple[ReceiptMetadata | None, tuple[str, ...]]:
    if not isinstance(raw, dict) or any(
        not isinstance(name, str) or not isinstance(value, str) for name, value in raw.items()
    ):
        return None, ("HEAD_METADATA_MALFORMED",)
    metadata = {name.lower(): value for name, value in raw.items()}
    if set(metadata) != _EXPECTED_METADATA_KEYS:
        return None, ("HEAD_METADATA_KEYS_MISMATCH",)
    try:
        workspace_id = _uuid(metadata.get("workspace-id"), field="workspace-id")
        asset_id = _uuid(metadata.get("asset-id"), field="asset-id")
        submission_id = _uuid(metadata.get("submission-id"), field="submission-id")
        serial_number = _integer(
            int(metadata["serial-number"]),
            field="serial-number",
            minimum=1,
        )
        if str(serial_number) != metadata["serial-number"]:
            raise ValueError("serial-number is not canonical.")
        content_size = _integer(
            int(metadata["content-size"]),
            field="content-size",
            minimum=1,
        )
        if str(content_size) != metadata["content-size"]:
            raise ValueError("content-size is not canonical.")
        content_sha256 = _sha256(metadata.get("content-sha256"), field="content-sha256")
        source_version = _string(
            metadata.get("source-version"), field="source-version", maximum=255
        )
        provider_source_version = _sha256(
            metadata.get("provider-source-version"), field="provider-source-version"
        )
        if metadata.get("content-kind") != "manual-metadata-csv-v1":
            raise ValueError("content-kind is invalid.")
        key_match = _MANUAL_KEY.fullmatch(key)
        if key_match is None or int(key_match.group(1)) != serial_number:
            raise ValueError("object key and serial-number do not reconcile.")
    except (KeyError, TypeError, ValueError):
        return None, ("HEAD_METADATA_VALUES_MALFORMED",)
    return (
        ReceiptMetadata(
            workspace_id=workspace_id,
            asset_id=asset_id,
            submission_id=submission_id,
            serial_number=serial_number,
            content_sha256=content_sha256,
            content_size=content_size,
            source_version=source_version,
            provider_source_version=provider_source_version,
        ),
        (),
    )


def _head(
    client: S3Client,
    *,
    bucket: str,
    key: str,
) -> Mapping[str, object] | None:
    try:
        return cast(Mapping[str, object], client.head_object(Bucket=bucket, Key=key))
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        status = int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return None
        raise


def _stream_hash(
    client: S3Client,
    *,
    bucket: str,
    key: str,
    maximum_bytes: int,
) -> tuple[int, str]:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        while True:
            raw_chunk = body.read(_CHUNK_BYTES)
            if not raw_chunk:
                break
            if not isinstance(raw_chunk, bytes):
                raise ValueError("S3 object body returned a non-byte chunk.")
            size += len(raw_chunk)
            if size > maximum_bytes:
                raise ValueError("S3 object exceeded its bounded listed size.")
            digest.update(raw_chunk)
    finally:
        body.close()
    return size, digest.hexdigest()


def _verify_object(
    *,
    client: S3Client,
    bucket: str,
    item: ListedObject,
) -> VerifiedObject:
    errors: list[str] = []
    metadata_raw: Mapping[str, str] = {}
    parsed_metadata: ReceiptMetadata | None = None
    observed_size: int | None = None
    observed_sha256: str | None = None
    try:
        head = _head(client, bucket=bucket, key=item.key)
        if head is None:
            errors.append("LISTED_OBJECT_HEAD_MISSING")
        else:
            content_length = head.get("ContentLength")
            if (
                not isinstance(content_length, int)
                or isinstance(content_length, bool)
                or content_length < 0
                or content_length != item.size_bytes
            ):
                errors.append("LIST_HEAD_SIZE_MISMATCH")
            content_type = head.get("ContentType")
            if content_type != "text/csv; charset=utf-8":
                errors.append("HEAD_CONTENT_TYPE_MISMATCH")
            raw_metadata = head.get("Metadata")
            if isinstance(raw_metadata, dict) and all(
                isinstance(name, str) and isinstance(value, str)
                for name, value in raw_metadata.items()
            ):
                metadata_raw = {name.lower(): value for name, value in raw_metadata.items()}
            parsed_metadata, metadata_errors = _metadata(raw_metadata, key=item.key)
            errors.extend(metadata_errors)
            observed_size, observed_sha256 = _stream_hash(
                client,
                bucket=bucket,
                key=item.key,
                maximum_bytes=item.size_bytes,
            )
            if observed_size != item.size_bytes:
                errors.append("LIST_CONTENT_SIZE_MISMATCH")
            if parsed_metadata is not None and (
                parsed_metadata.content_size != observed_size
                or parsed_metadata.content_sha256 != observed_sha256
            ):
                errors.append("METADATA_CONTENT_INTEGRITY_MISMATCH")
    except (BotoCoreError, ClientError, KeyError, TypeError, ValueError):
        errors.append("S3_READ_OR_INTEGRITY_FAILURE")
    return VerifiedObject(
        key=item.key,
        listed_size=item.size_bytes,
        observed_size=observed_size,
        observed_sha256=observed_sha256,
        metadata=parsed_metadata,
        metadata_raw=metadata_raw,
        evidence_errors=tuple(sorted(set(errors))),
    )


def _expected_metadata(
    reference: DatabaseReference,
    *,
    workspace_id: str,
) -> dict[str, str]:
    return {
        "workspace-id": workspace_id,
        "asset-id": reference.asset_id,
        "submission-id": reference.submission_id,
        "serial-number": str(reference.serial_number),
        "content-sha256": reference.sha256,
        "content-size": str(reference.size_bytes),
        "source-version": reference.source_version,
        "provider-source-version": reference.provider_source_version,
        "content-kind": "manual-metadata-csv-v1",
    }


def _report_item(
    *,
    key: str,
    status: str,
    reference: DatabaseReference | None,
    verified: VerifiedObject | None,
    reasons: Sequence[str] = (),
) -> dict[str, object]:
    document: dict[str, object] = {"key": key, "status": status}
    if reference is not None:
        document["submission_id"] = reference.submission_id
        document["serial_number"] = reference.serial_number
        document["database_size_bytes"] = reference.size_bytes
        document["database_sha256"] = reference.sha256
    elif verified is not None and verified.metadata is not None:
        document["submission_id"] = verified.metadata.submission_id
        document["serial_number"] = verified.metadata.serial_number
    if verified is not None:
        document["observed_size_bytes"] = verified.observed_size
        document["observed_sha256"] = verified.observed_sha256
    combined_reasons = sorted(
        set(reasons) | (set(verified.evidence_errors) if verified is not None else set())
    )
    if combined_reasons:
        document["reason_codes"] = combined_reasons
    return document


def reconcile(
    *,
    client: S3Client,
    manifest: DatabaseManifest,
    maximum_objects: int,
    maximum_total_bytes: int,
) -> dict[str, object]:
    if not 1 <= maximum_objects <= _MAXIMUM_OBJECTS:
        raise ValueError("maximum_objects must be between 1 and 1000.")
    if not 1 <= maximum_total_bytes <= _MAXIMUM_TOTAL_BYTES:
        raise ValueError("maximum_total_bytes must be between 1 byte and 1 GiB.")
    listed, s3_truncated, scan_reasons = _scan_prefix(
        client=client,
        bucket=manifest.bucket,
        prefix=manifest.prefix,
        maximum_objects=maximum_objects,
    )
    listed_bytes = sum(item.size_bytes for item in listed)
    refusal_reasons: list[str] = list(scan_reasons)
    if manifest.database_truncated:
        refusal_reasons.append("DATABASE_TRUNCATED")
    if s3_truncated and "S3_TRUNCATED" not in refusal_reasons:
        refusal_reasons.append("S3_TRUNCATED")
    if listed_bytes > maximum_total_bytes:
        refusal_reasons.append("S3_BYTES_LIMIT_EXCEEDED")
    if refusal_reasons:
        return {
            "schema_version": 1,
            "mode": "READ_ONLY_FAIL_CLOSED",
            "workspace_id": manifest.workspace_id,
            "bucket": manifest.bucket,
            "prefix": manifest.prefix,
            "classification_allowed": False,
            "refusal_reasons": sorted(set(refusal_reasons)),
            "database_reference_count": len(manifest.references),
            "database_total_reference_count": manifest.total_reference_count,
            "listed_object_count": len(listed),
            "listed_total_bytes": listed_bytes,
            "counts": {},
            "objects": [],
        }

    verified_objects = tuple(
        _verify_object(client=client, bucket=manifest.bucket, item=item) for item in listed
    )
    reference_by_key = {reference.key: reference for reference in manifest.references}
    reference_by_id = {reference.submission_id: reference for reference in manifest.references}
    reference_by_serial = {reference.serial_number: reference for reference in manifest.references}
    verified_by_key = {item.key: item for item in verified_objects}
    objects: list[dict[str, object]] = []
    for key in sorted(set(reference_by_key) | set(verified_by_key)):
        reference = reference_by_key.get(key)
        verified = verified_by_key.get(key)
        if verified is None:
            assert reference is not None
            objects.append(
                _report_item(
                    key=key,
                    status="DB_REFERENCE_MISSING",
                    reference=reference,
                    verified=None,
                    reasons=("S3_OBJECT_NOT_LISTED",),
                )
            )
            continue
        if reference is not None:
            expected_metadata = _expected_metadata(reference, workspace_id=manifest.workspace_id)
            matches = (
                not verified.evidence_errors
                and verified.observed_size == reference.size_bytes
                and verified.observed_sha256 == reference.sha256
                and dict(verified.metadata_raw) == expected_metadata
            )
            objects.append(
                _report_item(
                    key=key,
                    status=(
                        "DB_REFERENCE_PRESENT" if matches else "DB_REFERENCE_INTEGRITY_MISMATCH"
                    ),
                    reference=reference,
                    verified=verified,
                    reasons=(() if matches else ("DATABASE_EVIDENCE_MISMATCH",)),
                )
            )
            continue
        metadata = verified.metadata
        collides_with_reference = metadata is not None and (
            metadata.submission_id in reference_by_id
            or metadata.serial_number in reference_by_serial
        )
        candidate = (
            not verified.evidence_errors
            and metadata is not None
            and metadata.workspace_id == manifest.workspace_id
            and not collides_with_reference
        )
        objects.append(
            _report_item(
                key=key,
                status=(
                    "UNREFERENCED_EXACT_METADATA_CANDIDATE"
                    if candidate
                    else "MALFORMED_OR_AMBIGUOUS_OBJECT"
                ),
                reference=None,
                verified=verified,
                reasons=(
                    ()
                    if candidate
                    else (
                        "WORKSPACE_OR_REFERENCE_IDENTITY_MISMATCH"
                        if metadata is not None
                        else "METADATA_NOT_PROVABLE",
                    )
                ),
            )
        )

    counts = dict(sorted(Counter(str(item["status"]) for item in objects).items()))
    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "READ_ONLY_FAIL_CLOSED",
        "workspace_id": manifest.workspace_id,
        "bucket": manifest.bucket,
        "prefix": manifest.prefix,
        "classification_allowed": True,
        "refusal_reasons": [],
        "database_reference_count": len(manifest.references),
        "database_total_reference_count": manifest.total_reference_count,
        "listed_object_count": len(listed),
        "listed_total_bytes": listed_bytes,
        "verified_content_bytes": sum(item.observed_size or 0 for item in verified_objects),
        "counts": counts,
        "objects": objects,
    }
    return report


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    manifest = load_database_manifest(arguments.database_manifest)
    client = _client(
        endpoint=arguments.endpoint,
        region=arguments.region,
        access_key=_secret(arguments.access_key_file),
        secret_key=_secret(arguments.secret_key_file),
    )
    report = reconcile(
        client=client,
        manifest=manifest,
        maximum_objects=arguments.maximum_objects,
        maximum_total_bytes=arguments.maximum_total_bytes,
    )
    print(json.dumps(report, sort_keys=True))
    if not report["classification_allowed"]:
        return 2
    counts = cast(Mapping[str, int], report["counts"])
    return 0 if set(counts).issubset({"DB_REFERENCE_PRESENT"}) else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BotoCoreError, ClientError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "error": "MANUAL_RECEIPT_RECONCILIATION_FAILED",
                    "error_type": type(error).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
