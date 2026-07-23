from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from botocore.exceptions import ClientError


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "reconcile_manual_receipts.py"
    spec = importlib.util.spec_from_file_location("reconcile_manual_receipts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Body(BytesIO):
    pass


class _Client:
    def __init__(
        self,
        objects: dict[str, tuple[bytes, dict[str, str]]],
        *,
        force_list_truncated: bool = False,
    ) -> None:
        self.objects = dict(objects)
        self.force_list_truncated = force_list_truncated
        self.mutations = 0

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        prefix = str(kwargs["Prefix"])
        maximum = int(kwargs["MaxKeys"])
        keys = sorted(key for key in self.objects if key.startswith(prefix))
        selected = keys[:maximum]
        truncated = self.force_list_truncated or len(keys) > len(selected)
        return {
            "Contents": [{"Key": key, "Size": len(self.objects[key][0])} for key in selected],
            "IsTruncated": truncated,
            "NextContinuationToken": "next" if truncated else None,
        }

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        try:
            value, metadata = self.objects[Key]
        except KeyError as error:
            response: Any = {
                "Error": {"Code": "NoSuchKey"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            }
            raise ClientError(response, "HeadObject") from error
        return {
            "ContentLength": len(value),
            "ContentType": "text/csv; charset=utf-8",
            "Metadata": metadata,
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        return {"Body": _Body(self.objects[Key][0])}


def _reference(
    module: ModuleType,
    *,
    key: str,
    value: bytes,
    submission_id: str = "83f19e25-2ced-4c76-95f9-17a19c62e139",
    serial_number: int = 17,
) -> Any:
    return module.DatabaseReference(
        submission_id=submission_id,
        asset_id="c355d879-8a69-457a-b867-0ec228945170",
        serial_number=serial_number,
        key=key,
        size_bytes=len(value),
        sha256=hashlib.sha256(value).hexdigest(),
        source_version="catalog-v17",
        provider_source_version="b" * 64,
    )


def _metadata(
    *,
    value: bytes,
    workspace_id: str = "91146047-ebce-4c49-894c-3d89ca3ac39f",
    submission_id: str = "83f19e25-2ced-4c76-95f9-17a19c62e139",
    serial_number: int = 17,
) -> dict[str, str]:
    return {
        "workspace-id": workspace_id,
        "asset-id": "c355d879-8a69-457a-b867-0ec228945170",
        "submission-id": submission_id,
        "serial-number": str(serial_number),
        "content-sha256": hashlib.sha256(value).hexdigest(),
        "content-size": str(len(value)),
        "source-version": "catalog-v17",
        "provider-source-version": "b" * 64,
        "content-kind": "manual-metadata-csv-v1",
    }


def _manifest(module: ModuleType, references: tuple[Any, ...]) -> Any:
    return module.DatabaseManifest(
        workspace_id="91146047-ebce-4c49-894c-3d89ca3ac39f",
        bucket="datariver-infoschema",
        prefix="UPLOAD_METADATA_MANUAL_",
        total_reference_count=len(references),
        database_truncated=False,
        references=references,
    )


def test_database_manifest_sql_is_bounded_repeatable_read_only_and_complete() -> None:
    sql_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "export_manual_receipt_reconciliation_manifest.sql"
    )
    sql = sql_path.read_text(encoding="utf-8")

    assert "\\set QUIET 1" in sql
    assert "REPEATABLE READ READ ONLY" in sql
    assert "governance.manual_metadata_submissions" in sql
    assert "workspace_id = :'workspace_id'::uuid" in sql
    assert "bucket = :'bucket'::text" in sql
    assert "left(object_key, length(:'prefix'::text)) = :'prefix'::text" in sql
    assert "LIMIT (SELECT maximum_references + 1 FROM settings)" in sql
    assert "'database_truncated'" in sql
    for field in (
        "'submission_id'",
        "'asset_id'",
        "'serial_number'",
        "'key'",
        "'size_bytes'",
        "'sha256'",
        "'source_version'",
        "'provider_source_version'",
    ):
        assert field in sql
    assert all(token not in sql.upper() for token in ("DELETE FROM", "UPDATE ", "INSERT INTO"))


def test_lost_response_candidate_is_reported_but_never_called_an_orphan() -> None:
    module = _module()
    value = b"lost-response"
    key = "UPLOAD_METADATA_MANUAL_260723_000017.csv"
    client = _Client({key: (value, _metadata(value=value))})

    report = module.reconcile(
        client=client,
        manifest=_manifest(module, ()),
        maximum_objects=1_000,
        maximum_total_bytes=64 * 1024 * 1024,
    )

    assert report["classification_allowed"] is True
    assert report["counts"] == {"UNREFERENCED_EXACT_METADATA_CANDIDATE": 1}
    assert report["objects"][0]["status"] == "UNREFERENCED_EXACT_METADATA_CANDIDATE"
    assert "orphan" not in json.dumps(report).lower()
    assert client.mutations == 0


def test_ambiguous_commit_with_database_reference_reconciles_as_present() -> None:
    module = _module()
    value = b"commit-may-have-succeeded"
    key = "UPLOAD_METADATA_MANUAL_260723_000017.csv"
    reference = _reference(module, key=key, value=value)
    client = _Client({key: (value, _metadata(value=value))})

    report = module.reconcile(
        client=client,
        manifest=_manifest(module, (reference,)),
        maximum_objects=1_000,
        maximum_total_bytes=64 * 1024 * 1024,
    )

    assert report["classification_allowed"] is True
    assert report["counts"] == {"DB_REFERENCE_PRESENT": 1}
    assert report["objects"][0]["status"] == "DB_REFERENCE_PRESENT"
    assert report["objects"][0]["submission_id"] == reference.submission_id
    assert client.mutations == 0


def test_database_reference_missing_and_integrity_mismatch_are_distinct() -> None:
    module = _module()
    expected = b"expected"
    missing_key = "UPLOAD_METADATA_MANUAL_260723_000017.csv"
    mismatch_key = "UPLOAD_METADATA_MANUAL_260723_000018.csv"
    missing = _reference(module, key=missing_key, value=expected)
    mismatch = _reference(
        module,
        key=mismatch_key,
        value=expected,
        submission_id="5f522983-cf95-4dd5-9d56-7149415441d9",
        serial_number=18,
    )
    observed = b"tampered"
    client = _Client(
        {
            mismatch_key: (
                observed,
                _metadata(
                    value=observed,
                    submission_id=mismatch.submission_id,
                    serial_number=18,
                ),
            )
        }
    )

    report = module.reconcile(
        client=client,
        manifest=_manifest(module, (missing, mismatch)),
        maximum_objects=1_000,
        maximum_total_bytes=64 * 1024 * 1024,
    )

    assert report["counts"] == {
        "DB_REFERENCE_INTEGRITY_MISMATCH": 1,
        "DB_REFERENCE_MISSING": 1,
    }


@pytest.mark.parametrize("truncated_source", ["database", "s3", "bytes"])
def test_any_truncation_refuses_all_candidate_and_missing_classification(
    truncated_source: str,
) -> None:
    module = _module()
    value = b"bounded"
    key = "UPLOAD_METADATA_MANUAL_260723_000017.csv"
    reference = _reference(module, key=key, value=value)
    manifest = _manifest(module, (reference,))
    if truncated_source == "database":
        manifest = module.DatabaseManifest(
            workspace_id=manifest.workspace_id,
            bucket=manifest.bucket,
            prefix=manifest.prefix,
            total_reference_count=2,
            database_truncated=True,
            references=manifest.references,
        )
    client = _Client(
        {key: (value, _metadata(value=value))},
        force_list_truncated=truncated_source == "s3",
    )
    byte_limit = len(value) - 1 if truncated_source == "bytes" else 64 * 1024 * 1024

    report = module.reconcile(
        client=client,
        manifest=manifest,
        maximum_objects=1_000,
        maximum_total_bytes=byte_limit,
    )

    assert report["classification_allowed"] is False
    assert report["objects"] == []
    assert report["counts"] == {}
    assert any(truncated_source.upper() in reason for reason in report["refusal_reasons"])


def test_malformed_metadata_is_not_an_unreferenced_candidate() -> None:
    module = _module()
    value = b"malformed"
    key = "UPLOAD_METADATA_MANUAL_260723_000017.csv"
    metadata = _metadata(value=value)
    metadata["workspace-id"] = str(UUID(int=0))
    client = _Client({key: (value, metadata)})

    report = module.reconcile(
        client=client,
        manifest=_manifest(module, ()),
        maximum_objects=1_000,
        maximum_total_bytes=64 * 1024 * 1024,
    )

    assert report["counts"] == {"MALFORMED_OR_AMBIGUOUS_OBJECT": 1}


def test_manifest_loader_rejects_duplicate_keys_and_inconsistent_truncation(
    tmp_path: Path,
) -> None:
    module = _module()
    value = b"value"
    reference = {
        "submission_id": "83f19e25-2ced-4c76-95f9-17a19c62e139",
        "asset_id": "c355d879-8a69-457a-b867-0ec228945170",
        "serial_number": 17,
        "key": "UPLOAD_METADATA_MANUAL_260723_000017.csv",
        "size_bytes": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
        "source_version": "catalog-v17",
        "provider_source_version": "b" * 64,
    }
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_id": "91146047-ebce-4c49-894c-3d89ca3ac39f",
                "bucket": "datariver-infoschema",
                "prefix": "UPLOAD_METADATA_MANUAL_",
                "total_reference_count": 2,
                "database_truncated": False,
                "references": [reference, reference],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"duplicate|truncation"):
        module.load_database_manifest(path)


def test_source_contains_no_mutating_s3_calls_and_secret_is_never_returned() -> None:
    source_path = Path(__file__).resolve().parents[3] / "scripts" / "reconcile_manual_receipts.py"
    source = source_path.read_text(encoding="utf-8")

    for operation in (
        ".delete_object(",
        ".put_object(",
        ".copy_object(",
        ".upload_file(",
        ".create_multipart_upload(",
    ):
        assert operation not in source
    assert "print(json.dumps(report, sort_keys=True))" in source
    assert "str(error)" not in source
